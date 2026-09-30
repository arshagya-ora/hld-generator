"""
Debugger for Document Analyzer Agent.

Usage:
    python debuggers/debug_analyzer.py --file path/to/doc.pdf --product "Product Name" [options]

Examples:
    # Basic analysis
    python debuggers/debug_analyzer.py --file DSR.pdf --product "5G SBA"

    # With additional documents
    python debuggers/debug_analyzer.py --file DSR.pdf --product "Sessions" --additional-docs ref1.pdf ref2.pdf

    # With output save
    python debuggers/debug_analyzer.py --file DSR.pdf --product "Sessions" --output results.json

    # With debug logging
    python debuggers/debug_analyzer.py --file DSR.pdf --product "Sessions" --debug
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

# Ensure imports work for both direct script execution and module execution.
DEBUGGER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DEBUGGER_DIR.parent
PROJECT_PARENT = PROJECT_DIR.parent
for _path in (PROJECT_PARENT, PROJECT_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

# Register hld_generator_v2 as 'hld_generator' so that internal absolute imports
# like `from hld_generator.agents...` resolve correctly regardless of folder name.
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

from debuggers.base import AgentDebugger

# Import Agent
try:
    from hld_generator.agents.document_analyzer.agent import DocumentAnalyzerAgent
except ImportError:
    from agents.document_analyzer.agent import DocumentAnalyzerAgent

class DocumentAnalyzerDebugger(AgentDebugger):
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--file", type=str, required=True, help="Path to primary document file to analyze")
        parser.add_argument("--product", type=str, required=True, help="Product name to focus analysis on")
        parser.add_argument("--dataset", type=str, default="debug_dataset", help="Cognee dataset name")
        parser.add_argument("--document-type", type=str, help="Document type (auto-detected if not specified)")
        parser.add_argument("--additional-docs", nargs="+", help="Additional document files to analyze together")
        parser.add_argument("--product-hint", type=str, help="Optional product hint for extraction")
        parser.add_argument("--show-images", action="store_true", help="Show detailed image inventory in output")

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        # Resolve primary document path
        input_path = str(Path(args.file).expanduser().resolve())

        # Verify file exists
        if not Path(input_path).exists():
            raise FileNotFoundError(f"Document not found: {input_path}")

        logger.info(f"Primary Document: {Path(input_path).name}")

        # Build document paths list if additional docs provided
        document_paths: List[str] = None
        if args.additional_docs:
            document_paths = [input_path]  # Primary doc
            for doc_path in args.additional_docs:
                resolved_path = str(Path(doc_path).expanduser().resolve())
                if not Path(resolved_path).exists():
                    logger.warning(f"Additional document not found (skipping): {doc_path}")
                    continue
                document_paths.append(resolved_path)
                logger.info(f"Additional Document: {Path(resolved_path).name}")

            if len(document_paths) == 1:
                # Only primary doc exists, no additional docs found
                document_paths = None

        # Build extraction metadata
        extraction_metadata = {}
        if args.product_hint:
            extraction_metadata["product_hint"] = args.product_hint

        # Initialize agent
        logger.info("=" * 60)
        logger.info("Initializing Document Analyzer Agent...")
        logger.info("=" * 60)
        agent = DocumentAnalyzerAgent(config={"debug": args.debug})

        # Run analysis
        logger.info("Running Analysis Pipeline...")
        try:
            knowledge_base, image_inventory = await agent.run(
                document_path=input_path,
                dataset_name=args.dataset,
                selected_product_name=args.product,
                document_type=args.document_type,
                document_paths=document_paths,
                product_hint=args.product_hint,
            )
        except Exception as e:
            logger.error(f"Analysis failed: {str(e)}")
            raise

        # Extract metadata
        kb_extraction_metadata = knowledge_base.extraction_metadata or {}
        knowledge_graph_stats = knowledge_base.knowledge_graph_stats or {}
        completeness_score = (
            kb_extraction_metadata.get("completeness_score")
            or knowledge_graph_stats.get("completeness_score")
            or kb_extraction_metadata.get("coverage_score")
            or 0.0
        )

        # Log summary
        logger.info("=" * 60)
        logger.info("Analysis Complete!")
        logger.info("=" * 60)
        logger.info(f"Document Type: {knowledge_base.document_intelligence.document_type}")
        logger.info(f"Primary Products: {', '.join(knowledge_base.document_intelligence.primary_products or ['None'])}")
        logger.info(f"Sites Detected: {len(knowledge_base.sites or [])}")
        logger.info(f"Completeness Score: {completeness_score:.2%}")

        if image_inventory:
            logger.info(f"Images Extracted: {len(image_inventory.get('images', []))}")
            if args.show_images:
                logger.info("Image Details:")
                for img in image_inventory.get('images', [])[:5]:  # Show first 5
                    logger.info(f"  - {img.get('image_id')}: {img.get('classification', 'unknown')}")
                if len(image_inventory.get('images', [])) > 5:
                    logger.info(f"  ... and {len(image_inventory.get('images', [])) - 5} more")

        # Check for errors/warnings from agent
        if hasattr(agent, '_last_state'):
            final_state = agent._last_state
            if final_state.get("errors"):
                logger.warning(f"Completed with {len(final_state['errors'])} errors:")
                for error in final_state["errors"]:
                    logger.warning(f"  - {error}")
            if final_state.get("warnings"):
                logger.info(f"Warnings: {len(final_state['warnings'])}")
                for warning in final_state["warnings"][:3]:  # Show first 3
                    logger.info(f"  - {warning}")

        logger.info("=" * 60)

        # Build result dictionary
        result = {
            "knowledge_base": knowledge_base.model_dump(),
            "completeness_score": completeness_score,
            "extraction_metadata": kb_extraction_metadata,
            "knowledge_graph_stats": knowledge_graph_stats,
        }

        # Conditionally include image inventory (can be large)
        if args.show_images and image_inventory:
            result["image_inventory"] = image_inventory
        elif image_inventory:
            result["image_inventory_summary"] = {
                "total_images": len(image_inventory.get('images', [])),
                "classifications": {}
            }
            for img in image_inventory.get('images', []):
                classification = img.get('classification', 'unknown')
                result["image_inventory_summary"]["classifications"][classification] = \
                    result["image_inventory_summary"]["classifications"].get(classification, 0) + 1

        # Add errors/warnings from final state if available
        if hasattr(agent, '_last_state'):
            final_state = agent._last_state
            result["errors"] = final_state.get("errors", [])
            result["warnings"] = final_state.get("warnings", [])
        else:
            result["errors"] = []
            result["warnings"] = []

        return result

if __name__ == "__main__":
    DocumentAnalyzerDebugger("Document Analyzer Debugger").run()
