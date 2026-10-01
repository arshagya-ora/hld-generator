"""
Simplified Master Orchestrator for ArchDraft.

Sequential pipeline matching the debugger pattern:
1. Document Analyzer → Extract knowledge
2. Blueprint Agent → Create generation plan
3. Retrieval Agent → Execute RAG queries
4. Content Generation → Generate sections
5. Assembly Agent → Compile final document

NO complex LangGraph state mapping - just simple dictionary passing.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Setup paths
ORCHESTRATOR_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ORCHESTRATOR_DIR.parent
PROJECT_PARENT = PROJECT_DIR.parent

for _path in (PROJECT_PARENT, PROJECT_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

# Register hld_generator_v2 as 'hld_generator'
import importlib.util as _ilu
_hld_init = PROJECT_DIR / '__init__.py'
if _hld_init.exists() and 'hld_generator' not in sys.modules:
    _spec = _ilu.spec_from_file_location(
        'hld_generator', str(_hld_init),
        submodule_search_locations=[str(PROJECT_DIR)]
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules['hld_generator'] = _mod
    _spec.loader.exec_module(_mod)

# Imports
from hld_generator.agents.document_analyzer.agent import DocumentAnalyzerAgent
from hld_generator.agents.blueprint.agent import BlueprintAgent
from hld_generator.agents.retrieval.agent import RetrievalAgent
from hld_generator.agents.content_generation.agent import ContentGenerationAgent
from hld_generator.agents.assembly.agent import AssemblyAgent
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class _LLMWrapper:
    """
    Wrapper to bridge OCI client to chat() interface.
    Assembly Agent expects: chat(system_prompt, user_prompt) -> str
    """
    def __init__(self, adapter):
        self._adapter = adapter

    async def chat(self, system_prompt: str = "", user_prompt: str = "") -> str:
        return await self._adapter.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )


class MasterOrchestrator:
    """
    Master orchestrator that chains all agents together.

    Simple, debugger-style approach - no complex LangGraph state mapping.
    """

    def __init__(
        self,
        oci_client=None,
        rag_working_dir: str = "./rag_storage",
        output_dir: str = "./outputs",
    ):
        """
        Initialize the orchestrator.

        Args:
            oci_client: OCI OpenAI client (optional, will initialize if not provided)
            rag_working_dir: Base directory for RAG storage
            output_dir: Output directory for final documents
        """
        self.oci_client = oci_client
        self.rag_working_dir = rag_working_dir
        self.output_dir = output_dir

        # Initialize OCI services if not provided
        if not self.oci_client:
            self._initialize_oci_services()

    def _initialize_oci_services(self):
        """Initialize OCI services (only if not already provided)."""
        try:
            from hld_generator.backend.services.oci_client import (
                initialize_oci_services,
                get_oci_client,
            )

            logger.info("Initializing OCI services...")
            initialize_oci_services()

            if not self.oci_client:
                self.oci_client = get_oci_client()

            logger.info("OCI services initialized")

            # Cleanup old logs periodically (reduces disk usage)
            self._cleanup_old_logs()

        except Exception as e:
            logger.error(f"Failed to initialize OCI services: {e}")
            raise

    def _cleanup_old_logs(self):
        """Clean up old application log files to prevent disk space issues."""
        try:
            from hld_generator.shared.logging_config import cleanup_old_logs, MAX_LOG_FILES

            log_dirs = [
                Path("./logs"),
                Path("./backend/logs"),
                Path("./orchestrator/logs"),
            ]

            for log_dir in log_dirs:
                if log_dir.exists():
                    cleanup_old_logs(log_dir, MAX_LOG_FILES)

        except Exception as e:
            # Non-fatal error, just log it
            logger.debug(f"Log cleanup warning: {e}")

    async def _cleanup_dataset(self, dataset_name: str, document_path: Optional[str] = None):
        """
        Clean up image files after job completion.

        This is called automatically after each HLD generation job to free storage.
        Deletes:
        - Extracted images in ./images/source-docs/<dataset_name>/
        - Parsed images in ./images/parsed/<document_stem>/
        """
        import shutil

        logger.info("")
        logger.info("=" * 80)
        logger.info("CLEANUP: Deleting job data")
        logger.info("=" * 80)

        freed_space_mb = 0

        # Delete extracted images for this dataset (check multiple possible locations)
        image_base_dirs = ["./images", "./backend/images", "./orchestrator/images"]
        for base_dir in image_base_dirs:
            try:
                images_dir = Path(base_dir) / "source-docs" / dataset_name
                if images_dir.exists() and images_dir.is_dir():
                    # Calculate size before deletion
                    size_bytes = sum(f.stat().st_size for f in images_dir.rglob('*') if f.is_file())
                    size_mb = size_bytes / (1024 * 1024)

                    shutil.rmtree(images_dir)
                    freed_space_mb += size_mb
                    logger.info(f"Deleted extracted images: {images_dir} ({size_mb:.1f} MB)")
            except Exception as cleanup_error:
                logger.warning(f"Image cleanup error for {base_dir} (non-fatal): {cleanup_error}")

        # 3. Delete parsed images for this document (if document_path provided)
        if document_path:
            doc_stem = Path(document_path).stem
            for base_dir in image_base_dirs:
                try:
                    parsed_images_dir = Path(base_dir) / "parsed" / doc_stem
                    if parsed_images_dir.exists() and parsed_images_dir.is_dir():
                        # Calculate size before deletion
                        size_bytes = sum(f.stat().st_size for f in parsed_images_dir.rglob('*') if f.is_file())
                        size_mb = size_bytes / (1024 * 1024)

                        shutil.rmtree(parsed_images_dir)
                        freed_space_mb += size_mb
                        logger.info(f"Deleted parsed images: {parsed_images_dir} ({size_mb:.1f} MB)")
                except Exception as cleanup_error:
                    logger.warning(f"Parsed image cleanup error for {base_dir} (non-fatal): {cleanup_error}")

        logger.info(f"Total storage freed: ~{freed_space_mb:.1f} MB")
        logger.info("=" * 80)
        logger.info("")

    async def run(
        self,
        document_path: Optional[str] = None,
        product_name: str = "AUTO",
        dataset_name: str = "main_dataset",
        knowledge_base: Optional[Any] = None,
        image_inventory: Optional[Dict[str, Any]] = None,
        parsed_content: Optional[str] = None,
        structured_intent: Optional[Dict[str, Any]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Run the complete HLD generation pipeline.

        Args:
            document_path: Path to input document (.docx / .pdf)
            product_name: Product to focus on (AUTO = auto-detect)
            dataset_name: Dataset name for job isolation (used in cleanup)
            knowledge_base: Pre-computed DocumentKnowledgeBase model (if analyzer already ran)
            image_inventory: Pre-computed image inventory dictionary
            parsed_content: Pre-computed parsed text content

        Returns:
            Complete pipeline output with all agent results
        """
        logger.info("=" * 80)
        logger.info("ARCHDRAFT - MASTER ORCHESTRATOR")
        logger.info("=" * 80)
        logger.info(f"Document: {Path(document_path).name if document_path else 'Pre-computed Knowledge'}")
        logger.info(f"Product: {product_name}")
        logger.info(f"Dataset: {dataset_name}")
        logger.info("=" * 80)
        logger.info("")

        # Helper to emit progress
        async def _emit(stage: str, percent: int, message: str = ""):
            if progress_callback:
                try:
                    await progress_callback(stage, percent, message)
                except Exception:
                    pass

        # Initialize results container
        results = {
            "document_path": document_path,
            "product": product_name,
            "dataset": dataset_name,
            "errors": [],
            "warnings": [],
        }

        # ============================================================
        # STAGE 1: Document Analyzer
        # ============================================================
        logger.info("=" * 80)
        logger.info("STAGE 1: DOCUMENT ANALYZER")
        logger.info("=" * 80)
        await _emit("analyzing", 17, "Analyzing documents and extracting knowledge...")

        if knowledge_base and image_inventory:
            logger.info("Using provided pre-computed knowledge base and image inventory")
            # Parse content is also needed but optional
            if not parsed_content:
                parsed_content = ""
                logger.warning("No parsed content provided with knowledge base")
        else:
            if not document_path:
                error_msg = "No document_path provided and no pre-computed knowledge available"
                logger.error(f"{error_msg}")
                results["errors"].append(error_msg)
                results["pipeline_status"] = "failed_at_analyzer"
                await self._cleanup_dataset(dataset_name, document_path)
                return results

            try:
                # DocumentAnalyzerAgent creates its own tools internally
                analyzer_agent = DocumentAnalyzerAgent()

                logger.info("Running Document Analyzer...")
                knowledge_base, image_inventory = await analyzer_agent.run(
                    document_path=document_path,
                    dataset_name=dataset_name,
                    selected_product_name=product_name,
                )

                # Access parsed_content from internal state
                parsed_content = analyzer_agent._last_state.get("parsed_content", "")
            except Exception as e:
                error_msg = f"Document Analyzer failed: {e}"
                logger.error(f"{error_msg}")
                results["errors"].append(error_msg)
                results["pipeline_status"] = "failed_at_analyzer"
                await self._cleanup_dataset(dataset_name, document_path)
                return results

        logger.info(f"Document Analysis Complete")
        # Ensure knowledgebase is a dict for downstream if it came as a model
        kb_data = knowledge_base if isinstance(knowledge_base, dict) else knowledge_base.model_dump()
        
        logger.info(f"   Products: {len(kb_data.get('products', {}))}")
        logger.info(f"   Sites: {len(kb_data.get('sites', []))}")
        logger.info(f"   Tables: {len(kb_data.get('tables', []))}")
        logger.info(f"   Images: {image_inventory.get('total_images_extracted', 0) if image_inventory else 0}")
        logger.info(f"   Parsed Content: {len(parsed_content):,} chars")
        logger.info("")

        results["stage_1_analyzer"] = {
            "knowledge_base": kb_data,
            "image_inventory": image_inventory,
            "parsed_content": parsed_content,
        }

        # ============================================================
        # STAGE 2: Blueprint Agent
        # ============================================================
        logger.info("=" * 80)
        logger.info("STAGE 2: BLUEPRINT AGENT")
        logger.info("=" * 80)
        await _emit("blueprint", 27, "Creating document blueprint and section plan...")

        try:
            blueprint_agent = BlueprintAgent()

            logger.info("Running Blueprint Agent...")
            # CRITICAL: Pass product_id to Blueprint for consistency
            # This ensures Blueprint uses the user-selected product (job.product_id)
            # instead of auto-detecting from keywords (which can be wrong)
            blueprint_output = await blueprint_agent.run(
                knowledge_base=kb_data,
                image_inventory=image_inventory,
                structured_intent=structured_intent,
                product_id=product_name,  # From initial state (job.product_id passed as product_name)
            )

            sections = blueprint_output.get("sections", [])
            included_sections = [s for s in sections if s.get("include", True)]
            can_proceed = blueprint_output.get("can_proceed", True)
            clarifications = blueprint_output.get("clarifications", [])

            logger.info(f"Blueprint Generation Complete")
            logger.info(f"   Blueprint ID: {blueprint_output.get('blueprint_id')}")
            logger.info(f"   Product: {blueprint_output.get('product')}")
            logger.info(f"   Sections: {len(sections)} total, {len(included_sections)} included")
            logger.info(f"   Can Proceed: {can_proceed}")

            if clarifications:
                logger.warning(f"   Clarifications: {len(clarifications)}")
            logger.info("")

            results["stage_2_blueprint"] = {
                "blueprint_output": blueprint_output,
            }

            # Store product name from blueprint output for retrieval stage
            selected_product = blueprint_output.get("product", product_name)

            # Check if we can proceed
            if not can_proceed:
                logger.warning("Cannot proceed - critical clarifications needed")
                results["pipeline_status"] = "awaiting_clarifications"
                results["warnings"].append("Critical clarifications needed before proceeding")
                await self._cleanup_dataset(dataset_name, document_path)
                return results

        except Exception as e:
            error_msg = f"Blueprint Agent failed: {e}"
            logger.error(f"{error_msg}")
            results["errors"].append(error_msg)
            results["pipeline_status"] = "failed_at_blueprint"
            await self._cleanup_dataset(dataset_name, document_path)
            return results

        # ============================================================
        # STAGE 3: Retrieval Agent
        # ============================================================
        logger.info("=" * 80)
        logger.info("STAGE 3: RETRIEVAL AGENT")
        logger.info("=" * 80)
        await _emit("retrieving", 47, "Retrieving relevant content from knowledge base...")

        try:
            from hld_generator.shared.multi_product_rag_wrapper import MultiProductRAGWrapper

            rag_wrapper = MultiProductRAGWrapper(
                oci_client=self.oci_client,
                base_working_dir=self.rag_working_dir,
            )

            retrieval_agent = RetrievalAgent(
                rag_anything_client=rag_wrapper,
            )

            logger.info("Running Retrieval Agent...")
            retrieval_state = {
                "blueprint": blueprint_output,
                "product_id": selected_product,
                "document_knowledge_base": kb_data,
                "current_section_id": None,
                "query_execution_log": [],
                "rag_results": {},
                "retrieval_metrics": None,
                "retrieval_complete": False,
                "errors": []
            }

            retrieval_result = await retrieval_agent.ainvoke(retrieval_state)

            rag_results = retrieval_result.get("rag_results", {})
            retrieval_metrics = retrieval_result.get("retrieval_metrics")
            retrieval_errors = retrieval_result.get("errors", [])

            logger.info(f"Retrieval Complete")
            logger.info(f"   Sections: {len(rag_results)}")
            if retrieval_metrics:
                logger.info(f"   Queries: {retrieval_metrics.get('total_queries_executed', 0)}")
                logger.info(f"   Chunks: {retrieval_metrics.get('total_chunks_retrieved', 0)}")

            if retrieval_errors:
                logger.warning(f"   Errors: {len(retrieval_errors)}")
                results["warnings"].extend(retrieval_errors)
            logger.info("")

            results["stage_3_retrieval"] = {
                "rag_results": rag_results,
                "retrieval_metrics": retrieval_metrics,
            }

        except Exception as e:
            error_msg = f"Retrieval Agent failed: {e}"
            logger.error(f"{error_msg}")
            results["errors"].append(error_msg)
            results["warnings"].append("Proceeding without retrieval results")
            rag_results = {}

        # ============================================================
        # STAGE 4: Content Generation
        # ============================================================
        logger.info("=" * 80)
        logger.info("STAGE 4: CONTENT GENERATION")
        logger.info("=" * 80)
        await _emit("generating_sections", 62, "Generating HLD section content...")

        try:
            from hld_generator.external.oci_adapters import OCILLMAdapter

            llm_adapter = OCILLMAdapter()
            llm_wrapper = _LLMWrapper(llm_adapter)

            content_agent = ContentGenerationAgent(
                llm_client=llm_wrapper,
            )

            logger.info("Running Content Generation...")
            content_state = {
                "blueprint": blueprint_output,
                "rag_results": rag_results,
                "final_image_library": image_inventory or {},
                "project_context": kb_data,
                "parsed_content": parsed_content,
                "structured_intent": structured_intent,
                "generation_queue": [],
                "current_section_index": 0,
                "current_section_id": None,
                "current_strategy": None,
                "generated_sections": {},
                "generation_complete": False,
                "errors": [],
                "warnings": [],
            }

            content_result = await content_agent.ainvoke(content_state)

            generated_sections = content_result.get("generated_sections", {})
            content_errors = content_result.get("errors", [])
            generation_complete = content_result.get("generation_complete", False)

            logger.info(f"Content Generation Complete")
            logger.info(f"   Sections Generated: {len(generated_sections)}")

            for i, (sec_id, sec) in enumerate(list(generated_sections.items())[:5], 1):
                logger.info(
                    f"   [{sec.get('section_number', '?')}] {sec.get('title', sec_id)[:50]} "
                    f"({sec.get('word_count', 0)} words)"
                )

            if len(generated_sections) > 5:
                logger.info(f"   ... and {len(generated_sections) - 5} more sections")

            if content_errors:
                logger.warning(f"   Errors: {len(content_errors)}")
                results["errors"].extend(content_errors)
            logger.info("")

            results["stage_4_content"] = {
                "generated_sections": generated_sections,
                "generation_complete": generation_complete,
            }

            # Check if we have sections to assemble
            if not generated_sections:
                logger.error("No sections generated - cannot proceed to assembly")
                results["pipeline_status"] = "failed_at_content_generation"
                await self._cleanup_dataset(dataset_name, document_path)
                return results

        except Exception as e:
            error_msg = f"Content Generation failed: {e}"
            logger.error(f"{error_msg}")
            results["errors"].append(error_msg)
            results["pipeline_status"] = "failed_at_content_generation"
            await self._cleanup_dataset(dataset_name, document_path)
            return results

        # ============================================================
        # STAGE 5: Assembly
        # ============================================================
        logger.info("=" * 80)
        logger.info("STAGE 5: ASSEMBLY")
        logger.info("=" * 80)
        await _emit("assembling", 90, "Assembling final document...")

        try:
            assembly_agent = AssemblyAgent(
                llm_client=llm_wrapper,
                output_dir=self.output_dir,
                output_formats=["markdown", "docx"],
            )

            logger.info("Running Assembly Agent...")
            assembly_state = {
                "blueprint": blueprint_output,
                "generated_sections": generated_sections,
                "final_image_library": image_inventory or {},
                "project_context": kb_data,
                "parsed_content": parsed_content,
                "structured_intent": structured_intent,
                "llm_client": llm_wrapper,
                "output_dir": self.output_dir,
                "output_formats": ["markdown", "docx"],
                "compiled_content": None,
                "figure_references": [],
                "table_references": [],
                "section_references": [],
                "toc_content": None,
                "list_of_figures": None,
                "list_of_tables": None,
                "executive_summary": None,
                "appendices_content": None,
                "exported_files": {},
                "quality_checks": [],
                "assembled_document": None,
                "assembly_complete": False,
                "errors": [],
                "warnings": [],
            }

            assembly_result = await assembly_agent.ainvoke(assembly_state)

            exported_files = assembly_result.get("exported_files", {})
            assembly_errors = assembly_result.get("errors", [])
            quality_checks = assembly_result.get("quality_checks", [])

            logger.info(f"Assembly Complete")
            logger.info(f"   Assembly result keys: {list(assembly_result.keys())}")

            if exported_files:
                logger.info(f"   Exported Files:")
                for fmt, path in exported_files.items():
                    logger.info(f"     {fmt.upper()}: {path}")
            else:
                logger.warning("   No files exported!")
                logger.warning(f"   Assembly state had output_formats: {assembly_state.get('output_formats')}")
                logger.warning(f"   Blueprint customer_name: {assembly_state.get('blueprint', {}).get('customer_name')}")
                logger.warning(f"   Blueprint product: {assembly_state.get('blueprint', {}).get('product')}")
                logger.warning("   This indicates export_documents_node failed")

            if quality_checks:
                passed = [c for c in quality_checks if c.get("passed")]
                failed = [c for c in quality_checks if not c.get("passed")]
                logger.info(f"   Quality Checks: {len(passed)}/{len(quality_checks)} passed")

            if assembly_errors:
                logger.warning(f"   Errors: {len(assembly_errors)}")
                results["errors"].extend(assembly_errors)
            logger.info("")

            results["stage_5_assembly"] = {
                "exported_files": exported_files,
                "quality_checks": quality_checks,
            }

            results["pipeline_status"] = "completed"

        except Exception as e:
            error_msg = f"Assembly Agent failed: {e}"
            logger.error(f"{error_msg}")
            results["errors"].append(error_msg)
            results["pipeline_status"] = "failed_at_assembly"
            await self._cleanup_dataset(dataset_name, document_path)
            return results

        # ============================================================
        # Final Summary
        # ============================================================
        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Status: {results['pipeline_status']}")
        logger.info(f"Errors: {len(results['errors'])}")
        logger.info(f"Warnings: {len(results['warnings'])}")

        if exported_files:
            logger.info(f"Final Document: {exported_files.get('markdown', 'Not generated')}")

        logger.info("=" * 80)

        # Cleanup: Delete Cognee dataset and images to free storage
        await self._cleanup_dataset(dataset_name, document_path)

        return results


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="ArchDraft - Master Orchestrator"
    )
    parser.add_argument(
        "document",
        type=str,
        help="Path to input document (.docx / .pdf)"
    )
    parser.add_argument(
        "--product",
        type=str,
        default="AUTO",
        help="Product to focus on (default: AUTO = auto-detect)"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="main_dataset",
        help="Cognee dataset name (default: main_dataset)"
    )
    parser.add_argument(
        "--rag-dir",
        type=str,
        default=os.getenv("RAG_WORKING_DIR", "./rag_storage"),
        help="RAG storage directory (default: ./rag_storage)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./outputs",
        help="Output directory (default: ./outputs)"
    )

    args = parser.parse_args()

    # Create orchestrator
    orchestrator = MasterOrchestrator(
        rag_working_dir=args.rag_dir,
        output_dir=args.output_dir,
    )

    # Run pipeline
    results = await orchestrator.run(
        document_path=args.document,
        product_name=args.product,
        dataset_name=args.dataset,
    )

    # Print final status
    if results["pipeline_status"] == "completed":
        sys.exit(0)
    else:
        logger.error(f"Pipeline failed: {results['pipeline_status']}")
        for error in results["errors"]:
            logger.error(f"  - {error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
