"""
HLD Generation Celery Task
Async task for generating HLD documents
"""
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import traceback
import uuid
from typing import Dict, Any, List, Optional

from celery import Task
from celery_app import celery_app

logger = logging.getLogger(__name__)
from sqlalchemy import select

from database import AsyncSessionLocal
from models.job import Job, JobDocument
from models.document import Document
from services.orchestrator_wrapper import (
    OrchestratorWrapper,
    DocumentProcessor,
    create_initial_state,
    PIPELINE_STAGES,
)
from services.encryption import encryption_service
from services.job_artifacts import owned_output_path

# Intent Interpreter (Phase 1 - Critical Innovation)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.intent_interpreter.interpreter import IntentInterpreter

# Minimum interval (seconds) between progress DB writes to avoid SQLite lock contention
_PROGRESS_DB_WRITE_INTERVAL = 3.0


class HLDGenerationTask(Task):
    """
    Custom Celery task for HLD generation
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails — safely handles event loop lifecycle"""
        job_id = args[0] if args else None
        if job_id:
            # Use new_event_loop instead of asyncio.run() to avoid
            # "cannot be called from a running event loop" errors
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._mark_job_failed(job_id, str(exc), str(einfo)))
            except Exception as e:
                logger.error(f"Failed to mark job {job_id} as failed in on_failure handler: {e}")
            finally:
                loop.close()

    async def _mark_job_failed(self, job_id: str, error_message: str, traceback_str: str):
        """Mark job as failed in database"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()

            if job:
                job.status = "failed"
                job.error_message = error_message
                job.error_traceback = traceback_str
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()


@celery_app.task(
    bind=True,
    base=HLDGenerationTask,
    name="tasks.hld_generation.generate_hld",
    max_retries=3,
    default_retry_delay=60
)
def generate_hld_task(self, job_id: str) -> Dict[str, Any]:
    """
    Generate HLD document (Celery task)
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(_generate_hld_async(job_id, self))
        return result
    except Exception as e:
        logger.error(f"HLD generation failed for job {job_id}: {e}")
        raise
    finally:
        loop.close()


async def _generate_hld_async(job_id: str, task: Task) -> Dict[str, Any]:
    """
    Async implementation of HLD generation with granular progress updates
    """
    # Pipeline log accumulates events for the frontend activity feed
    pipeline_log: List[Dict[str, Any]] = []
    _last_db_write_time = 0.0  # track last DB write to throttle

    async def on_progress_update(stage: str, percent: int, message: str = ""):
        """Update job progress in database and append to pipeline log.

        Throttled: DB writes happen at most every _PROGRESS_DB_WRITE_INTERVAL seconds
        to avoid hammering SQLite with concurrent writes from multiple jobs.
        Stage transitions (different stage name) always write immediately.
        """
        nonlocal _last_db_write_time
        now = datetime.now(timezone.utc)

        # Resolve human-readable label from PIPELINE_STAGES
        label = stage
        for s in PIPELINE_STAGES:
            if s["key"] == stage:
                label = s["label"]
                break

        # Append log entry (always, even if DB write is skipped)
        pipeline_log.append({
            "stage": stage,
            "label": label,
            "percent": percent,
            "message": message or label,
            "timestamp": now.isoformat(),
        })

        # Always update Celery state (writes to Redis, fast)
        task.update_state(
            state='PROGRESS',
            meta={
                'stage': stage,
                'percent': percent,
                'message': message,
                'job_id': job_id
            }
        )

        # Throttle DB writes: skip if same stage and interval not elapsed
        current_time = time.monotonic()
        is_stage_change = (
            len(pipeline_log) <= 1 or
            pipeline_log[-1]["stage"] != pipeline_log[-2]["stage"]
        )
        if not is_stage_change and (current_time - _last_db_write_time) < _PROGRESS_DB_WRITE_INTERVAL:
            return  # skip DB write, Celery state is already updated

        # Write to database with retry for SQLite locking
        for attempt in range(3):
            try:
                async with AsyncSessionLocal() as progress_db:
                    result = await progress_db.execute(
                        select(Job).where(Job.id == uuid.UUID(job_id))
                    )
                    progress_job = result.scalar_one_or_none()

                    if progress_job:
                        progress_job.pipeline_stage = stage
                        progress_job.progress_percent = percent
                        progress_job.job_metadata = {
                            **(progress_job.job_metadata or {}),
                            "pipeline_log": pipeline_log,
                        }
                        await progress_db.commit()
                _last_db_write_time = time.monotonic()
                break  # success
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))  # backoff: 0.5s, 1.0s
                    continue
                logger.warning(f"Progress DB write failed for job {job_id}: {e}")
                break

    async with AsyncSessionLocal() as db:
        # Fetch job
        result = await db.execute(
            select(Job).where(Job.id == uuid.UUID(job_id))
        )
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Guard: if job was cancelled or failed before worker picked it up, abort
        if job.status not in ("queued", "running"):
            logger.warning(f"Job {job_id} has status '{job.status}', skipping execution")
            return {"status": "skipped", "job_id": job_id, "reason": f"Job status is '{job.status}'"}

        # Defense-in-depth: re-check global concurrent running count
        # This catches TOCTOU races where multiple jobs slipped through the API check
        from sqlalchemy import func as sa_func
        running_count_result = await db.execute(
            select(sa_func.count()).select_from(Job).where(
                Job.status == "running"
            )
        )
        running_count = running_count_result.scalar()
        # Allow this job to proceed only if running count is below hard limit
        # (the job is still "queued" at this point so it's not counted)
        HARD_CONCURRENCY_LIMIT = 12  # slight headroom over configured 10
        if running_count >= HARD_CONCURRENCY_LIMIT:
            logger.warning(f"Job {job_id}: {running_count} jobs already running, exceeds hard limit {HARD_CONCURRENCY_LIMIT}")
            job.status = "queued"  # Re-queue for retry
            job.error_message = "System at capacity, will retry"
            await db.commit()
            raise task.retry(countdown=30, max_retries=5)

        # Update job status to running
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.pipeline_stage = "queued"
        job.progress_percent = 0
        await db.commit()

        try:
            # Fetch job documents
            result = await db.execute(
                select(Document, JobDocument)
                .join(JobDocument, JobDocument.document_id == Document.id)
                .where(JobDocument.job_id == job.id)
                .order_by(JobDocument.document_order)
            )
            docs = result.all()
            documents = [doc for doc, _ in docs]

            # ===== STEP 0: INTERPRET USER INTENT (Critical Innovation) =====
            user_prompt = job.user_prompt or ""
            structured_intent = None

            if user_prompt.strip():
                await on_progress_update("document_processing", 2, "Interpreting user instructions...")
                try:
                    interpreter = IntentInterpreter()

                    # Get available components from the local product profile.
                    from agents.blueprint.tools.product_profile_loader import ProductProfileLoader
                    profile = ProductProfileLoader().load_product_profile(job.product_id)
                    available_components = profile.metadata.get("network_functions", [])

                    # Get document filenames for data source mapping
                    doc_filenames = [
                        getattr(doc, 'original_filename', f'doc_{i}')
                        for i, doc in enumerate(documents)
                    ]

                    structured_intent = await interpreter.interpret(
                        user_prompt=user_prompt,
                        product=job.product_id,
                        available_components=available_components,
                        document_filenames=doc_filenames,
                    )

                    logger.info(f"Intent interpreted: type={structured_intent.intent_type}, "
                                f"components={structured_intent.component_scope.include}")
                except Exception as e:
                    logger.warning(f"Intent interpretation failed (non-fatal): {e}")
                    structured_intent = None

            # Process all documents (with per-document progress)
            await on_progress_update("document_processing", 5, f"Starting document processing ({len(documents)} document(s))...")

            processor = DocumentProcessor(
                job_id=str(job.id),
                documents=documents,
                encryption_service=encryption_service,
                product_name=job.product_id,
                on_progress_update=on_progress_update,
                structured_intent=structured_intent,
            )

            # Log dataset isolation info for debugging
            logger.info(f"📦 Using product-level Cognee dataset: '{processor.dataset_name}'")
            logger.info(f"🔒 Dataset isolation: Each product has its own isolated dataset")
            logger.info(f"🗑️  Dataset will be cleared before indexing to prevent stale data contamination")

            processing_results = await processor.process_all()
            cognee_dataset_name = processing_results["dataset_name"]

            logger.info(f"✓ Document processing complete. Dataset used: '{cognee_dataset_name}'")

            await on_progress_update("document_processing", 15, "Document processing complete")

            # Create initial state with pre-computed knowledge
            initial_state = create_initial_state(
                job_id=str(job.id),
                product_id=job.product_id,
                product_profile_file=job.product_profile_file,
                cognee_dataset_name=cognee_dataset_name,
                config=job.config
            )

            # Add pre-computed knowledge to state
            initial_state.update({
                "knowledge_base": processing_results["knowledge_base"],
                "image_inventory": processing_results["image_inventory"],
                "parsed_content": processing_results["parsed_content"],
                "structured_intent": structured_intent.model_dump() if structured_intent else None,
                "user_prompt": user_prompt,
            })

            # Run orchestrator (it emits its own progress callbacks for each stage)
            orchestrator = OrchestratorWrapper(
                on_progress_update=on_progress_update
            )

            final_state = await orchestrator.run(
                initial_state=initial_state,
            )

            # Get output path from final state
            assembly_results = final_state.get("stage_5_assembly", {})
            exported_files = assembly_results.get("exported_files", {})
            output_path = exported_files.get("docx") or exported_files.get("markdown")

            if not output_path:
                output_path = final_state.get("output_path")

            if not output_path:
                # Enhanced error diagnostics
                logger.error("=" * 80)
                logger.error("ORCHESTRATOR OUTPUT PATH MISSING")
                logger.error("=" * 80)
                logger.error(f"Final state keys: {list(final_state.keys())}")
                logger.error(f"stage_5_assembly: {assembly_results}")
                logger.error(f"exported_files: {exported_files}")
                logger.error(f"pipeline_status: {final_state.get('pipeline_status')}")
                logger.error(f"errors: {final_state.get('errors', [])}")
                logger.error("=" * 80)

                # Include diagnostic info in error message
                error_details = []
                if final_state.get('errors'):
                    error_details.append(f"Pipeline errors: {final_state['errors']}")
                if final_state.get('pipeline_status'):
                    error_details.append(f"Pipeline status: {final_state['pipeline_status']}")

                error_msg = "Orchestrator did not return output path in expected format."
                if error_details:
                    error_msg += " " + " | ".join(error_details)

                raise ValueError(error_msg)

            # Update job with results
            job.status = "completed"
            job.output_path = str(output_path)
            job.progress_percent = 100
            job.pipeline_stage = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.current_state = final_state

            # Calculate metadata
            duration_seconds = int(
                (job.completed_at - job.started_at).total_seconds()
            )

            # Add final log entry
            pipeline_log.append({
                "stage": "completed",
                "label": "Completed",
                "percent": 100,
                "message": f"HLD generated successfully in {duration_seconds}s",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            job.job_metadata = {
                "duration_seconds": duration_seconds,
                "document_count": len(documents),
                "cognee_dataset": cognee_dataset_name,
                "final_state_keys": list(final_state.keys()),
                "pipeline_log": pipeline_log,
            }

            await db.commit()

            return {
                "status": "success",
                "job_id": str(job.id),
                "output_path": output_path,
                "duration_seconds": duration_seconds
            }

        except Exception as e:
            # Add error to pipeline log
            pipeline_log.append({
                "stage": "failed",
                "label": "Failed",
                "percent": job.progress_percent or 0,
                "message": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Mark job as failed
            job.status = "failed"
            job.error_message = str(e)
            job.error_traceback = traceback.format_exc()
            job.completed_at = datetime.now(timezone.utc)
            job.job_metadata = {
                **(job.job_metadata or {}),
                "pipeline_log": pipeline_log,
            }
            await db.commit()

            raise


@celery_app.task(name="tasks.hld_generation.cleanup_old_jobs")
def cleanup_old_jobs_task(days: int = 30, tenant_id: Optional[str] = None):
    """
    Cleanup old completed/failed jobs (Celery task)

    Args:
        days: Delete jobs older than this many days
        tenant_id: Optional tenant filter (None = all tenants, admin only)
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(_cleanup_old_jobs_async(days, tenant_id))
    finally:
        loop.close()


async def _cleanup_old_jobs_async(days: int, tenant_id: Optional[str] = None):
    """
    Async cleanup implementation - deletes old jobs and all associated files.

    Args:
        days: Delete jobs older than this many days
        tenant_id: Optional tenant filter (None = all tenants, admin only)
    """
    import shutil
    from datetime import timedelta

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    logger.info(f"Starting cleanup of jobs older than {days} days (cutoff: {cutoff_date})")
    if tenant_id:
        logger.info(f"Filtering by tenant_id: {tenant_id}")

    async with AsyncSessionLocal() as db:
        # Build query with optional tenant filtering
        query = select(Job).where(
            Job.status.in_(["completed", "failed"]),
            Job.completed_at < cutoff_date
        )

        # CRITICAL: Filter by tenant if specified (prevents cross-tenant deletion)
        if tenant_id is not None:
            query = query.where(Job.tenant_id == tenant_id)

        result = await db.execute(query)
        old_jobs = result.scalars().all()

        logger.info(f"Found {len(old_jobs)} old jobs to clean up")

        deleted_count = 0
        files_deleted = 0

        for job in old_jobs:
            logger.info(f"Cleaning up job {job.id}")

            # Older shared paths cannot be attributed to a job safely.
            if job.output_path and owned_output_path(job.id, job.output_path) is None:
                logger.warning("Skipping job %s with an output requiring manual migration", job.id)
                continue

            # 1. Delete primary output file (existing logic)
            if job.output_path:
                output_path = owned_output_path(job.id, job.output_path)
                if output_path and output_path.exists():
                    try:
                        output_path.unlink()
                        files_deleted += 1
                        logger.info(f"  Deleted output file: {output_path}")
                    except Exception as e:
                        logger.warning(f"  Failed to delete output file {output_path}: {e}")

            # 2. NEW: Delete image directories associated with this job
            image_patterns = [
                f"backend/images/source-docs/*{job.id}*",
                f"images/source-docs/*{job.id}*",
            ]
            for pattern in image_patterns:
                for img_dir in Path(".").glob(pattern):
                    if img_dir.is_dir():
                        try:
                            shutil.rmtree(img_dir)
                            files_deleted += 1
                            logger.info(f"  Deleted image directory: {img_dir}")
                        except Exception as e:
                            logger.warning(f"  Failed to delete image directory {img_dir}: {e}")

            # 3. NEW: Delete related output file variants (markdown + docx)
            if job.output_path:
                try:
                    output_path = owned_output_path(job.id, job.output_path)
                    if output_path is None:
                        raise ValueError("Output path is outside the job directory")
                    base_name = output_path.stem
                    output_dir = output_path.parent

                    for variant in output_dir.glob(f"{base_name}.*"):
                        if variant.exists() and variant != output_path:
                            try:
                                variant.unlink()
                                files_deleted += 1
                                logger.info(f"  Deleted output variant: {variant}")
                            except Exception as e:
                                logger.warning(f"  Failed to delete variant {variant}: {e}")
                except Exception as e:
                    logger.warning(f"  Error processing output variants: {e}")

            # 4. Delete job from database (existing)
            await db.delete(job)
            deleted_count += 1

        await db.commit()
        logger.info(f"Cleanup complete: {deleted_count} jobs and {files_deleted} files deleted")
