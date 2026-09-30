"""
Jobs API Routes
Create and manage HLD generation jobs
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List
import uuid
from datetime import datetime, timezone

from database import get_db
from schemas.job import (
    JobCreateRequest,
    JobResponse,
    JobListResponse,
    JobDetailResponse,
    JobStatusResponse
)
from models.job import Job, JobDocument
from models.document import Document
from models.user import User
from auth.dependencies import get_current_active_user
from config import settings
from services.product_profile_catalog import get_profile_loader
from services.job_artifacts import owned_output_path
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])


def download_available(job: Job) -> bool:
    if job.status != "completed" or not job.output_path:
        return False
    output_file = owned_output_path(job.id, job.output_path)
    return output_file is not None and output_file.is_file()


def public_error_message(job_status: str, error_message: Optional[str]) -> Optional[str]:
    if job_status == "failed" and error_message:
        return "Generation failed. Please try again or contact support."
    return error_message


def public_job_metadata(metadata: Optional[dict]) -> Optional[dict]:
    if not metadata:
        return None
    public = {key: metadata[key] for key in ("duration_seconds", "document_count") if key in metadata}
    pipeline_log = metadata.get("pipeline_log")
    if isinstance(pipeline_log, list):
        public["pipeline_log"] = []
        for item in pipeline_log:
            if not isinstance(item, dict):
                continue
            entry = {key: item[key] for key in ("stage", "label", "percent", "timestamp", "message") if key in item}
            if entry.get("stage") == "failed":
                entry["message"] = "Generation failed."
            public["pipeline_log"].append(entry)
    return public


def dispatch_celery_task(job_id: str):
    """Dispatch job to Celery worker and store task ID on Job row."""
    import asyncio
    from database import AsyncSessionLocal
    from sqlalchemy import select as sa_select

    try:
        from tasks.hld_generation import generate_hld_task
        celery_task = generate_hld_task.apply_async(args=[job_id], retry=False)
        logger.info(f"Job {job_id} dispatched to Celery (task_id: {celery_task.id})")

        # Write celery_task_id back to Job row so cancel/monitoring works
        async def _store_task_id():
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    sa_select(Job).where(Job.id == uuid.UUID(job_id))
                )
                job = result.scalar_one_or_none()
                if job:
                    job.celery_task_id = celery_task.id
                    await db.commit()

        # Run in a fresh event loop (this runs in a sync BackgroundTask thread)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_store_task_id())
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Failed to dispatch job {job_id} to Celery: {e}")
        # Mark job as failed so it doesn't stay "queued" forever
        async def _mark_dispatch_failed():
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    sa_select(Job).where(Job.id == uuid.UUID(job_id))
                )
                job = result.scalar_one_or_none()
                if job and job.status == "queued":
                    job.status = "failed"
                    job.error_message = f"Failed to dispatch to worker: {e}"
                    await db.commit()

        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_mark_dispatch_failed())
            loop.close()
        except Exception:
            logger.error(f"Additionally failed to mark job {job_id} as failed")


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new HLD generation job

    - Validates product exists
    - Validates all documents exist and belong to user
    - Creates job with queued status
    - Links documents to job
    - TODO: Enqueue Celery task
    """
    # Only profiles with valid JSON and a matching product ID can start jobs.
    if request.product_id not in get_profile_loader().list_products():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{request.product_id}' not found"
        )

    # Validate all documents exist and belong to user
    for doc_id in request.document_ids:
        result = await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.tenant_id == current_user.tenant_id,
                Document.user_id == current_user.id
            )
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{doc_id}' not found"
            )

    # Check per-user concurrent job limit first
    user_active_result = await db.execute(
        select(func.count()).select_from(Job).where(
            Job.user_id == current_user.id,
            Job.status.in_(["queued", "running"])
        )
    )
    user_active_jobs = user_active_result.scalar()
    max_per_user = settings.MAX_CONCURRENT_JOBS_PER_USER  # default 5

    if user_active_jobs >= max_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You have {user_active_jobs} active jobs (limit: {max_per_user}). "
                   f"Please wait for a job to complete before starting a new one."
        )

    # Check global concurrent job limit
    # Use a fresh count right before insert to minimize TOCTOU window
    active_count_result = await db.execute(
        select(func.count()).select_from(Job).where(
            Job.status.in_(["queued", "running"])
        )
    )
    active_jobs = active_count_result.scalar()
    max_concurrent = settings.DEFAULT_TENANT_MAX_CONCURRENT_JOBS  # default 10

    if active_jobs >= max_concurrent:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"System is at capacity ({max_concurrent} concurrent jobs). Please try again later."
        )

    # Create job
    job = Job(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        product_id=request.product_id,
        product_profile_file=f"{request.product_id}.json",
        user_prompt=request.user_prompt,
        status="queued",
        config=request.config,
        output_format="docx",
        progress_percent=0
    )

    db.add(job)
    await db.flush()  # Flush to get job.id

    # Link documents to job
    for idx, doc_id in enumerate(request.document_ids):
        job_doc = JobDocument(
            job_id=job.id,
            document_id=doc_id,
            document_order=idx
        )
        db.add(job_doc)

    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task in background (after response is sent)
    background_tasks.add_task(dispatch_celery_task, str(job.id))

    return JobResponse(
        id=job.id,
        user_id=job.user_id,
        product_id=job.product_id,
        product_profile_file=job.product_profile_file,
        status=job.status,
        celery_task_id=job.celery_task_id,
        pipeline_stage=job.pipeline_stage,
        progress_percent=job.progress_percent,
        download_available=download_available(job),
        output_format=job.output_format,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=public_error_message(job.status, job.error_message),
        created_at=job.created_at,
        updated_at=job.updated_at,
        document_count=len(request.document_ids),
        duration_seconds=None
    )


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List user's jobs

    - Paginated results
    - Filter by status
    - Returns job metadata
    """
    # Validate pagination
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    # Build query
    query = select(Job).where(
        Job.tenant_id == current_user.tenant_id,
        Job.user_id == current_user.id
    )

    if status_filter:
        query = query.where(Job.status == status_filter)

    # Get total count
    count_query = select(func.count()).select_from(Job).where(
        Job.tenant_id == current_user.tenant_id,
        Job.user_id == current_user.id
    )
    if status_filter:
        count_query = count_query.where(Job.status == status_filter)

    result = await db.execute(count_query)
    total_count = result.scalar()

    # Get paginated results
    query = query.order_by(Job.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    # Convert to response models
    job_responses = []
    for job in jobs:
        # Calculate duration if completed
        duration_seconds = None
        if job.started_at and job.completed_at:
            duration_seconds = int((job.completed_at - job.started_at).total_seconds())

        # Get document count
        result = await db.execute(
            select(func.count()).select_from(JobDocument).where(JobDocument.job_id == job.id)
        )
        document_count = result.scalar()

        job_responses.append(JobResponse(
            id=job.id,
            user_id=job.user_id,
            product_id=job.product_id,
            product_profile_file=job.product_profile_file,
            status=job.status,
            celery_task_id=job.celery_task_id,
            pipeline_stage=job.pipeline_stage,
            progress_percent=job.progress_percent,
            download_available=download_available(job),
            output_format=job.output_format,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=public_error_message(job.status, job.error_message),
            created_at=job.created_at,
            updated_at=job.updated_at,
            document_count=document_count,
            duration_seconds=duration_seconds
        ))

    total_pages = (total_count + page_size - 1) // page_size

    return JobListResponse(
        jobs=job_responses,
        count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed job information

    - Returns job details
    - Includes associated documents
    - Includes pipeline state
    """
    result = await db.execute(
        select(Job).where(
            Job.id == job_id,
            Job.tenant_id == current_user.tenant_id,
            Job.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    # Get associated documents
    result = await db.execute(
        select(Document, JobDocument).join(
            JobDocument, JobDocument.document_id == Document.id
        ).where(
            JobDocument.job_id == job_id
        ).order_by(JobDocument.document_order)
    )
    docs = result.all()

    documents = []
    for doc, job_doc in docs:
        documents.append({
            "id": str(doc.id),
            "original_filename": doc.original_filename,
            "document_type": doc.document_type,
            "document_label": doc.document_label,
            "order": job_doc.document_order
        })

    # Calculate duration
    duration_seconds = None
    if job.started_at and job.completed_at:
        duration_seconds = int((job.completed_at - job.started_at).total_seconds())

    return JobDetailResponse(
        id=job.id,
        user_id=job.user_id,
        product_id=job.product_id,
        product_profile_file=job.product_profile_file,
        status=job.status,
        celery_task_id=job.celery_task_id,
        pipeline_stage=job.pipeline_stage,
        progress_percent=job.progress_percent,
        download_available=download_available(job),
        output_format=job.output_format,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=public_error_message(job.status, job.error_message),
        created_at=job.created_at,
        updated_at=job.updated_at,
        document_count=len(documents),
        duration_seconds=duration_seconds,
        config=job.config,
        job_metadata=public_job_metadata(job.job_metadata),
        documents=documents
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get lightweight job status (for polling)

    - Returns only status and progress
    - Optimized for frequent polling
    """
    result = await db.execute(
        select(
            Job.id,
            Job.status,
            Job.pipeline_stage,
            Job.progress_percent,
            Job.error_message
        ).where(
            Job.id == job_id,
            Job.tenant_id == current_user.tenant_id,
            Job.user_id == current_user.id
        )
    )
    row = result.one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    return JobStatusResponse(
        id=row[0],
        status=row[1],
        pipeline_stage=row[2],
        progress_percent=row[3],
        error_message=public_error_message(row[1], row[4])
    )


@router.get("/{job_id}/download", response_class=FileResponse)
async def download_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Download the generated HLD document"""
    result = await db.execute(
        select(Job).where(
            Job.id == job_id,
            Job.tenant_id == current_user.tenant_id,
            Job.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        logger.warning(f"Download failed: Job {job_id} not found for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    if job.status != "completed":
        logger.warning(f"Download failed: Job {job_id} has status '{job.status}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is in '{job.status}' status. Only completed jobs can be downloaded."
        )

    if not job.output_path:
        logger.warning(f"Download failed: Job {job_id} has no output_path")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Output path not found for this job"
        )

    file_path = owned_output_path(job.id, job.output_path)
    if file_path is None or not file_path.is_file():
        logger.warning("Download failed: output is unavailable for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated file not found on server",
        )

    filename = file_path.name
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a job

    - Only queued or running jobs can be cancelled
    - Revokes Celery task if task ID is available
    - Updates status to cancelled
    """
    result = await db.execute(
        select(Job).where(
            Job.id == job_id,
            Job.tenant_id == current_user.tenant_id,
            Job.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    if job.status not in ["queued", "running"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only queued or running jobs can be cancelled"
        )

    # Revoke Celery task to actually stop the worker
    if job.celery_task_id:
        try:
            from celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
            logger.info(f"Revoked Celery task {job.celery_task_id} for job {job_id}")
        except Exception as e:
            logger.warning(f"Failed to revoke Celery task {job.celery_task_id}: {e}")

    # CRITICAL: Clean up Cognee dataset before marking as cancelled
    # Prevents orphaned datasets that could contaminate future jobs
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(job)

    logger.info(f"Job {job_id} cancelled successfully")

    # Return success response (204 No Content is correct for DELETE)


@router.post("/recover-stale", status_code=status.HTTP_200_OK)
async def recover_stale_jobs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recover stale jobs stuck in 'queued' or 'running' state.

    Jobs older than 2 hours in queued/running are marked as failed.
    This frees up concurrency slots consumed by zombie jobs.
    Tenant admins can recover their tenant's jobs; super admins can recover
    all tenants' jobs; regular users can recover only their own.
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)

    # Build query based on role
    query = select(Job).where(
        Job.status.in_(["queued", "running"]),
        Job.created_at < cutoff,
    )
    if current_user.role != "super_admin":
        query = query.where(Job.tenant_id == current_user.tenant_id)
    if current_user.role not in ("admin", "super_admin"):
        query = query.where(Job.user_id == current_user.id)

    result = await db.execute(query)
    stale_jobs = result.scalars().all()

    recovered = []
    for job in stale_jobs:
        # Try to revoke Celery task
        if job.celery_task_id:
            try:
                from celery_app import celery_app
                celery_app.control.revoke(job.celery_task_id, terminate=True)
            except Exception:
                pass

        previous_status = job.status
        job.status = "failed"
        job.error_message = f"Recovered: job was stuck in '{previous_status}' for over 2 hours"
        job.completed_at = datetime.now(timezone.utc)
        recovered.append(str(job.id))

    await db.commit()

    return {
        "recovered_count": len(recovered),
        "recovered_job_ids": recovered,
    }
