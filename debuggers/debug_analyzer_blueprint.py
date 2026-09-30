"""
Debugger for Document Analyzer + Blueprint Agent (Chained).

Runs both agents sequentially:
1. Document Analyzer extracts knowledge from the document
2. Blueprint Agent creates generation plan from the extracted knowledge

This mimics the first two stages of the full pipeline.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Any

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

# Import Agents
try:
    from hld_generator.agents.document_analyzer.agent import DocumentAnalyzerAgent
    from hld_generator.agents.blueprint.agent import BlueprintAgent
except ImportError:
    from agents.document_analyzer.agent import DocumentAnalyzerAgent
    from agents.blueprint.agent import BlueprintAgent


class AnalyzerBlueprintDebugger(AgentDebugger):
    """Combined debugger for Document Analyzer → Blueprint Agent pipeline."""

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to document file to analyze (.docx / .pdf)"
        )
        parser.add_argument(
            "--product",
            type=str,
            required=True,
            help="Product name to focus analysis on (e.g., 'DSR', '5G_SBA')"
        )
        parser.add_argument(
            "--dataset",
            type=str,
            default="debug_dataset",
            help="Cognee dataset name"
        )
        parser.add_argument(
            "--save-analyzer-output",
            type=str,
            help="Optional: Save Document Analyzer output to separate JSON file"
        )

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        """
        Execute both agents in sequence.

        Returns:
            Combined output with both analyzer and blueprint results
        """
        input_path = str(Path(args.file).expanduser().resolve())

        # ============================================================
        # STAGE 1: Document Analyzer
        # ============================================================
        logger.info("=" * 60)
        logger.info("STAGE 1: Document Analyzer")
        logger.info("=" * 60)
        logger.info(f"Input Document: {input_path}")
        logger.info(f"Target Product: {args.product}")
        logger.info(f"Dataset: {args.dataset}")
        logger.info("")

        analyzer_agent = DocumentAnalyzerAgent(config={"debug": args.debug})

        logger.info("Running Document Analyzer pipeline...")
        knowledge_base, image_inventory = await analyzer_agent.run(
            document_path=input_path,
            dataset_name=args.dataset,
            selected_product_name=args.product,
        )

        extraction_metadata = knowledge_base.extraction_metadata or {}
        knowledge_graph_stats = knowledge_base.knowledge_graph_stats or {}
        completeness_score = (
            extraction_metadata.get("completeness_score")
            or knowledge_graph_stats.get("completeness_score")
            or extraction_metadata.get("coverage_score")
            or 0.0
        )

        logger.info(f"Document Analysis Complete")
        logger.info(f"   Completeness Score: {completeness_score}")
        logger.info(f"   Products Detected: {len(knowledge_base.products)}")
        logger.info(f"   Sites Detected: {len(knowledge_base.sites or [])}")
        logger.info(f"   Tables Extracted: {len(knowledge_base.tables or [])}")
        logger.info(f"   Images Extracted: {image_inventory.get('total_images_extracted', 0) if image_inventory else 0}")
        logger.info("")

        # Prepare analyzer output
        analyzer_output = {
            "knowledge_base": knowledge_base.model_dump(),
            "image_inventory": image_inventory,
            "completeness_score": completeness_score,
            "extraction_metadata": extraction_metadata,
            "knowledge_graph_stats": knowledge_graph_stats,
            "errors": []
        }

        # Optionally save analyzer output to separate file
        if args.save_analyzer_output:
            import json
            save_path = Path(args.save_analyzer_output).resolve()

            # Handle directory paths - append default filename
            if save_path.is_dir():
                save_path = save_path / "analyzer_output.json"
            elif not save_path.suffix:
                # No extension - treat as directory
                save_path.mkdir(parents=True, exist_ok=True)
                save_path = save_path / "analyzer_output.json"

            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(analyzer_output, f, indent=2, default=str)
            logger.info(f"Analyzer output saved to: {save_path}")
            logger.info("")

        # ============================================================
        # STAGE 2: Blueprint Agent
        # ============================================================
        logger.info("=" * 60)
        logger.info("STAGE 2: Blueprint Agent")
        logger.info("=" * 60)
        logger.info("Inputs:")
        logger.info(f"  - Knowledge Base: {len(knowledge_base.model_dump())} keys")
        logger.info(f"  - Image Inventory: {len(image_inventory) if image_inventory else 0} keys")
        logger.info("")

        blueprint_agent = BlueprintAgent(config={"debug": args.debug})

        logger.info("Running Blueprint Agent pipeline...")
        blueprint_output = await blueprint_agent.run(
            knowledge_base=knowledge_base.model_dump(),
            image_inventory=image_inventory,
            cognee_dataset_name=args.dataset,
        )

        logger.info(f"Blueprint Generation Complete")
        logger.info(f"   Blueprint ID: {blueprint_output.get('blueprint_id')}")
        logger.info(f"   Product: {blueprint_output.get('product')}")
        logger.info(f"   Document Type: {blueprint_output.get('document_type')}")
        logger.info(f"   Total Sections: {len(blueprint_output.get('sections', []))}")

        # Count sections by include status
        sections = blueprint_output.get('sections', [])
        included_sections = [s for s in sections if s.get('include', True)]
        excluded_sections = [s for s in sections if not s.get('include', True)]

        logger.info(f"   Included Sections: {len(included_sections)}")
        logger.info(f"   Excluded Sections: {len(excluded_sections)}")

        # Count total RAG queries
        total_rag_queries = sum(len(s.get('rag_queries', [])) for s in sections)
        logger.info(f"   Total RAG Queries: {total_rag_queries}")

        # Count matched images and tables
        total_matched_images = sum(len(s.get('matched_images', [])) for s in sections)
        total_matched_tables = sum(len(s.get('matched_tables', [])) for s in sections)
        logger.info(f"   Matched Images: {total_matched_images}")
        logger.info(f"   Matched Tables: {total_matched_tables}")

        # Check for clarifications
        clarifications = blueprint_output.get('clarifications', [])
        can_proceed = blueprint_output.get('can_proceed', True)
        if clarifications:
            logger.warning(f"   Clarifications Needed: {len(clarifications)}")
            logger.warning(f"   Can Proceed: {can_proceed}")

        # Generation batches
        generation_batches = blueprint_output.get('generation_batches', [])
        if generation_batches:
            logger.info(f"   Generation Batches: {len(generation_batches)}")
            for batch in generation_batches:
                batch_num = batch.get('batch_number', '?')
                batch_sections = batch.get('sections', [])
                logger.info(f"      Batch {batch_num}: {len(batch_sections)} sections")

        logger.info("")
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 60)

        # Return combined output
        return {
            "stage_1_analyzer": analyzer_output,
            "stage_2_blueprint": {
                "blueprint_output": blueprint_output,
                "clarifications": clarifications,
                "errors": []
            },
            "pipeline_summary": {
                "document_path": input_path,
                "product": args.product,
                "dataset": args.dataset,
                "analyzer_completeness_score": completeness_score,
                "blueprint_id": blueprint_output.get('blueprint_id'),
                "total_sections": len(sections),
                "included_sections": len(included_sections),
                "excluded_sections": len(excluded_sections),
                "total_rag_queries": total_rag_queries,
                "matched_images": total_matched_images,
                "matched_tables": total_matched_tables,
                "clarifications_needed": len(clarifications),
                "can_proceed_to_generation": can_proceed
            }
        }


if __name__ == "__main__":
    AnalyzerBlueprintDebugger(
        "Document Analyzer + Blueprint Agent Debugger (Chained Pipeline)"
    ).run()
