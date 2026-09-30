"""
Document Analyzer Agent - Main implementation.

This agent analyzes documents (PID, RFP, specifications) and extracts
structured project knowledge using a three-phase adaptive discovery pipeline.

The agent can run standalone or as a node in the multi-agent orchestrator.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
import asyncio

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from hld_generator.agents.document_analyzer.state.schema import AnalyzerState
from hld_generator.agents.document_analyzer.state.models import DocumentKnowledgeBase
from hld_generator.agents.document_analyzer.graph.builder import build_agent_graph
from hld_generator.agents.document_analyzer.graph import nodes
from hld_generator.agents.document_analyzer.tools.parser_wrapper import ParserWrapper
from hld_generator.agents.document_analyzer.tools.llm_helper import LLMHelper
from hld_generator.shared.logging_config import setup_logger

# Image module imports (graceful fallback if not configured)
try:
    from hld_generator.shared.vision_wrapper import OCIVisionWrapper
    from hld_generator.agents.document_analyzer.tools.image_extractor import ImageExtractor
    from hld_generator.agents.document_analyzer.phases.image_analysis import ImageAnalysisPhase
    IMAGE_MODULE_AVAILABLE = True
except ImportError as e:
    IMAGE_MODULE_AVAILABLE = False
    _IMAGE_IMPORT_ERROR = str(e)


class DocumentAnalyzerAgent:
    """
    Document Analyzer Agent for intelligent document processing.

    **New Architecture (Cognee-free):**
    - Parses DOCX/PDF documents using Docling
    - Semantic chunking preserves topic boundaries
    - Direct LLM extraction from chunks (parallel for speed)
    - Intelligent merging with conflict resolution
    - Outputs structured DocumentKnowledgeBase

    **Usage:**

    Standalone execution:
    ```python
    agent = DocumentAnalyzerAgent()
    result = await agent.run("document.docx", "my_dataset")
    print(result.products)
    ```

    In orchestrator:
    ```python
    agent = DocumentAnalyzerAgent()
    kb, images = await agent.run(document_path, dataset_name, product_name)
    ```
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the Document Analyzer Agent.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Initialize logger
        self.logger = setup_logger(__name__)

        # Initialize core tools
        self.parser = ParserWrapper()
        self.llm_helper = LLMHelper()

        # Initialize image module (graceful fallback)
        self.image_analysis_phase = None
        if IMAGE_MODULE_AVAILABLE:
            try:
                vision = OCIVisionWrapper()
                extractor = ImageExtractor()
                # Note: ImageAnalysisPhase no longer needs cognee_wrapper
                self.image_analysis_phase = ImageAnalysisPhase(
                    vision_wrapper=vision,
                    cognee_wrapper=None,  # No longer used
                    image_extractor=extractor,
                )
                self.logger.info("Image analysis module initialized")
            except Exception as e:
                self.logger.warning(f"Image module init failed (non-fatal): {e}")
                self.image_analysis_phase = None
        else:
            self.logger.info(f"Image module not available: {_IMAGE_IMPORT_ERROR}")

        # Initialize nodes with tools (new signature)
        nodes.initialize_tools(
            parser=self.parser,
            image_analysis_phase=self.image_analysis_phase,
            llm_helper=self.llm_helper,
        )

        # Build LangGraph
        self.graph = build_agent_graph()
    
    async def run(
        self,
        document_path: str,
        dataset_name: str,
        selected_product_name: str,
        document_type: Optional[str] = None,
        document_paths: Optional[List[str]] = None,
        structured_intent: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> tuple[DocumentKnowledgeBase, Optional[Dict[str, Any]]]:
        """
        Run the document analysis pipeline (standalone execution).

        Args:
            document_path: Path to primary DOCX/PDF document
            dataset_name: Unique identifier for Cognee dataset
            selected_product_name: Product name to focus analysis on
            document_type: Optional document type (auto-detected if None)
            document_paths: Optional list of additional document paths.
                            When provided, ALL documents are parsed and their
                            content is merged before analysis.  document_path
                            is still required as the primary doc (and is
                            automatically included in the list).
            **kwargs: Additional configuration options

        Returns:
            Tuple of (DocumentKnowledgeBase, Optional[image_inventory dict])

        Raises:
            FileNotFoundError: If document doesn't exist
            ValueError: If document format unsupported
            Exception: If analysis fails
        """
        # Build the full list of document paths
        all_paths = list(document_paths) if document_paths else []
        if document_path not in all_paths:
            all_paths.insert(0, document_path)

        self.logger.info("=" * 60)
        self.logger.info("Document Analyzer Agent - Starting Analysis")
        self.logger.info("=" * 60)
        if len(all_paths) == 1:
            self.logger.info(f"Document: {Path(document_path).name}")
        else:
            self.logger.info(f"Documents ({len(all_paths)}):")
            for p in all_paths:
                self.logger.info(f"  • {Path(p).name}")
        self.logger.info(f"Dataset: {dataset_name}")
        self.logger.info(f"Product Focus: {selected_product_name}")
        self.logger.info("=" * 60)

        # Extraction metadata
        extraction_metadata = {
            "product_hint": kwargs.get("product_hint")
        }

        # Initialize state
        initial_state: AnalyzerState = {
            "document_path": document_path,
            "document_paths": all_paths if len(all_paths) > 1 else None,
            "document_type": document_type,
            "dataset_name": dataset_name,
            "selected_product_name": selected_product_name,
            "cognee_indexed": False,
            "parsed_content": None,
            "parsed_tables": None,
            "image_dir": None,
            "document_structure": {},
            "content_categories": [],
            "discovered_entities": [],
            "planned_queries": [],
            "executed_queries": [],
            "raw_extractions": {},
            "knowledge_base": None,
            "completeness_score": 0.0,
            "missing_items": [],
            "extracted_images": [],
            "image_inventory": None,
            "converter_result": None,
            "current_phase": "init",
            "structured_intent": structured_intent,
            "agentic_retrieval": None,
            "extraction_metadata": extraction_metadata,
            "errors": [],
            "warnings": []
        }
        
        # Execute graph
        try:
            final_state = await self.graph.ainvoke(initial_state)

            # Store final state for internal use (preserves parsed_content, etc.)
            self._last_state = final_state

            # Check for errors
            if final_state.get("errors"):
                self.logger.warning(f"Completed with {len(final_state['errors'])} errors:")
                for error in final_state["errors"]:
                    self.logger.warning(f"   - {error}")

            # Extract knowledge base and image inventory
            kb_dict = final_state.get("knowledge_base")
            if not kb_dict:
                raise ValueError("Analysis completed but no knowledge base generated")

            knowledge_base = DocumentKnowledgeBase(**kb_dict)
            image_inventory = final_state.get("image_inventory")

            self.logger.info("=" * 60)
            self.logger.info("Analysis Complete")
            self.logger.info("=" * 60)

            return knowledge_base, image_inventory
            
        except Exception as e:
            self.logger.error(f"Analysis failed: {str(e)}")
            raise
    
# CLI helper
async def main_cli():
    """CLI entry point for standalone testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Document Analyzer Agent")
    parser.add_argument("document", help="Path to DOCX/PDF document")
    parser.add_argument("--dataset", default="analyzed_doc", help="Dataset name")
    parser.add_argument("--product", required=True, help="Target product name to focus analysis (REQUIRED)")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()

    # Run agent
    agent = DocumentAnalyzerAgent()
    result, image_inventory = await agent.run(
        args.document,
        args.dataset,
        args.product
    )

    # Save output
    if args.output:
        Path(args.output).write_text(result.model_dump_json(indent=2))
        print(f"\nResults saved to: {args.output}")
    else:
        print("\n" + "=" * 60)
        print("Knowledge Base Summary:")
        print("=" * 60)
        print(f"Document Type: {result.document_intelligence.document_type}")
        print(f"Products: {', '.join(result.document_intelligence.primary_products) if result.document_intelligence.primary_products else 'None'}")
        print(f"Sites: {len(result.sites)}")
        print(f"Completeness: {result.knowledge_graph_stats.get('completeness_score', 'N/A')}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main_cli())
