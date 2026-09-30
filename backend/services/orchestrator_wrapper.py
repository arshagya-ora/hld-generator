"""
Orchestrator Wrapper Service
Wraps the existing LangGraph master_graph with web-specific features
"""
import sys
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from datetime import datetime, timezone
import uuid

from config import settings
from services.job_artifacts import job_output_dir

# Add parent directory to path to import existing orchestrator
backend_dir = Path(__file__).parent.parent
hld_generator_root = backend_dir.parent
sys.path.insert(0, str(hld_generator_root))

# Import existing orchestrator (DO NOT MODIFY - just wrap it)
from orchestrator.master_orchestrator import MasterOrchestrator


# Pipeline stage definitions with human-readable labels
PIPELINE_STAGES = [
    {"key": "queued", "label": "Queued", "percent": 0},
    {"key": "document_processing", "label": "Processing Documents", "percent": 5},
    {"key": "analyzing", "label": "Analyzing Documents", "percent": 17},
    {"key": "blueprint", "label": "Creating Blueprint", "percent": 27},
    {"key": "retrieving", "label": "Retrieving Content", "percent": 47},
    {"key": "generating_sections", "label": "Generating Sections", "percent": 62},
    {"key": "assembling", "label": "Assembling Document", "percent": 90},
    {"key": "completed", "label": "Completed", "percent": 100},
]


class OrchestratorWrapper:
    """
    Wraps the existing LangGraph orchestrator for web usage

    Key features:
    - Progress callbacks for real-time updates
    - Pipeline log for activity feed
    - State checkpointing for resume capability
    - Error handling and logging
    - Zero modifications to existing orchestrator code
    """

    def __init__(
        self,
        on_progress_update: Optional[Callable] = None
    ):
        """
        Initialize orchestrator wrapper

        Args:
            on_progress_update: Callback for progress updates (stage, percent, message)
        """
        self.on_progress_update = on_progress_update
        self.orchestrator = None

    def _get_orchestrator(self, job_id: str):
        """Build the MasterOrchestrator instance"""
        if not self.orchestrator:
            rag_working_dir = settings.RAG_WORKING_DIR
            output_dir = str(job_output_dir(uuid.UUID(job_id)))

            # Get initialized OCI client
            from services.oci_client import get_oci_client

            try:
                oci_client = get_oci_client()

                # Initialize MasterOrchestrator
                self.orchestrator = MasterOrchestrator(
                    oci_client=oci_client,
                    rag_working_dir=rag_working_dir,
                    output_dir=output_dir
                )
            except RuntimeError as e:
                # OCI services not initialized
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Creating orchestrator without OCI services: {e}")
                self.orchestrator = MasterOrchestrator(
                    rag_working_dir=rag_working_dir,
                    output_dir=output_dir
                )

        return self.orchestrator

    async def run(
        self,
        initial_state: Dict[str, Any],
        checkpoint_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Run the HLD generation pipeline
        """
        # Get orchestrator
        orchestrator = self._get_orchestrator(initial_state["job_id"])

        try:
            # Get pre-computed knowledge from initial_state
            knowledge_base = initial_state.get("knowledge_base")
            image_inventory = initial_state.get("image_inventory")
            parsed_content = initial_state.get("parsed_content")
            cognee_dataset_name = initial_state.get("cognee_dataset_name")
            product_id = initial_state.get("product_id")
            structured_intent = initial_state.get("structured_intent")

            # Build a progress callback that MasterOrchestrator can call
            async def orchestrator_progress(stage: str, percent: int, message: str = ""):
                if self.on_progress_update:
                    await self.on_progress_update(stage, percent, message)

            results = await orchestrator.run(
                knowledge_base=knowledge_base,
                image_inventory=image_inventory,
                parsed_content=parsed_content,
                product_name=product_id,
                dataset_name=cognee_dataset_name,
                structured_intent=structured_intent,
                progress_callback=orchestrator_progress,
            )

            # Update progress to completed
            if self.on_progress_update:
                await self.on_progress_update("completed", 100, "HLD generation complete")

            return results

        except Exception as e:
            raise


class DocumentProcessor:
    """
    Process multiple documents for a job
    """

    def __init__(
        self,
        job_id: str,
        documents: list,
        encryption_service,
        product_name: str = "Unknown Product",
        on_progress_update: Optional[Callable] = None,
        structured_intent: Optional[Dict[str, Any]] = None,
    ):
        self.job_id = job_id
        self.documents = documents
        self.encryption_service = encryption_service
        self.product_name = product_name
        # CRITICAL FIX: Per-job AND per-product dataset isolation with timestamp
        # Format: {product_id}_job_{job_id}_{timestamp_ms}
        # Examples: "DSR_job_abc123_1709876543210", "Sessions_job_def456_1709876543211"
        # Each job gets its OWN isolated dataset to prevent cross-job contamination
        # Timestamp ensures uniqueness even if job_id is reused
        # Dataset is deleted after job completion (see hld_generation.py cleanup)
        # This prevents BOTH cross-product AND cross-job data leakage
        import time
        timestamp = int(time.time() * 1000)  # millisecond precision
        self.dataset_name = f"{product_name}_job_{job_id}_{timestamp}"
        self.on_progress_update = on_progress_update
        self.structured_intent = structured_intent

    async def _emit(self, stage: str, percent: int, message: str = ""):
        if self.on_progress_update:
            try:
                await self.on_progress_update(stage, percent, message)
            except Exception:
                pass

    async def process_all(self) -> Dict[str, Any]:
        """
        Process all documents and create unified knowledge graph.

        NOTE: Document Analyzer now supports multi-document processing with parallel
        parsing (new in concurrency update). All documents are processed in a SINGLE
        analyzer.run() call which:
        - Parses all documents in parallel (asyncio.gather)
        - Indexes them sequentially in Cognee (required - Cognee doesn't support parallel add/cognify)
        - Returns merged knowledge base
        """
        # Import Document Analyzer agent
        sys.path.insert(0, str(hld_generator_root / "agents" / "document_analyzer"))
        from agent import DocumentAnalyzerAgent

        total_docs = len(self.documents)

        await self._emit(
            "document_processing",
            5,
            f"Starting document processing (1 document(s))..."
        )

        # Decrypt all documents to temporary files
        decrypted_paths = []
        for idx, document in enumerate(self.documents):
            doc_name = getattr(document, 'original_filename', f'Document {idx + 1}')
            await self._emit(
                "document_processing",
                5 + int((idx / max(total_docs, 1)) * 5),
                f"Decrypting document {idx + 1}/{total_docs}: {doc_name}"
            )

            decrypted_path = await self.encryption_service.get_decrypted_file_path(
                document.storage_path
            )
            decrypted_paths.append(decrypted_path)

        try:
            # Process ALL documents in single analyzer call
            analyzer = DocumentAnalyzerAgent()

            await self._emit(
                "document_processing",
                10,
                f"Analyzing {total_docs} document(s) (parsing in parallel)..."
            )

            # Use document_paths for multi-doc or document_path for single-doc
            # Pass structured_intent so agentic_retrieval_node can use it
            intent_dict = None
            if self.structured_intent is not None:
                # Convert Pydantic model to dict if needed
                if hasattr(self.structured_intent, 'model_dump'):
                    intent_dict = self.structured_intent.model_dump()
                else:
                    intent_dict = self.structured_intent

            if len(decrypted_paths) == 1:
                kb, img_inv = await analyzer.run(
                    document_path=str(decrypted_paths[0]),
                    dataset_name=self.dataset_name,
                    selected_product_name=self.product_name,
                    document_type=self.documents[0].document_type,
                    structured_intent=intent_dict,
                )
            else:
                kb, img_inv = await analyzer.run(
                    document_path=str(decrypted_paths[0]),  # Primary document (required)
                    document_paths=[str(p) for p in decrypted_paths],
                    dataset_name=self.dataset_name,
                    selected_product_name=self.product_name,
                    document_type="multi_document",
                    structured_intent=intent_dict,
                )

            # Capture parsed content from analyzer's internal state
            all_parsed_content = analyzer._last_state.get("parsed_content", "")

            # KB is already merged by analyzer for multi-doc
            aggregated_kb = kb.model_dump()

            # Images are already merged by analyzer
            combined_images = img_inv if img_inv else {
                "total_images_extracted": 0,
                "images": []
            }

            # Update all documents with Cognee dataset name
            for document in self.documents:
                document.cognee_dataset_name = self.dataset_name

        finally:
            # Clean up all temporary decrypted files
            for decrypted_path in decrypted_paths:
                try:
                    decrypted_path.unlink(missing_ok=True)
                except PermissionError:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        f"Could not delete temp file {decrypted_path} — it may still be in use."
                    )

        await self._emit("document_processing", 15, f"All {total_docs} document(s) processed")

        return {
            "dataset_name": self.dataset_name,
            "knowledge_base": aggregated_kb,
            "image_inventory": combined_images,
            "parsed_content": all_parsed_content if isinstance(all_parsed_content, str) else "\n\n".join(all_parsed_content)
        }


def create_initial_state(
    job_id: str,
    product_id: str,
    product_profile_file: str,
    cognee_dataset_name: str,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create initial state for orchestrator
    """
    config = config or {}
    return {
        "job_id": job_id,
        "product_id": product_id,
        "product_profile_file": product_profile_file,
        "cognee_dataset_name": cognee_dataset_name,
        "output_format": config.get("output_format", "docx"),
        "include_diagrams": config.get("include_diagrams", True),
        "verbosity": config.get("verbosity", "medium"),
        "current_stage": "initializing",
        "progress_percent": 0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
