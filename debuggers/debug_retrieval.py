"""
Debugger for Retrieval Agent.
"""

import argparse
import logging
import os
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

from debuggers.base import AgentDebugger, load_json_input

# Import Agent
from hld_generator.agents.retrieval.agent import RetrievalAgent
from hld_generator.agents.retrieval.state.schema import RetrievalState

class RetrievalDebugger(AgentDebugger):
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--blueprint", type=str, required=True, help="Path to Blueprint Output JSON file")
        parser.add_argument("--kb", type=str, help="Path to Document Knowledge Base JSON file")
        parser.add_argument("--dataset", type=str, default="debug_dataset", help="Cognee dataset name")
        parser.add_argument("--rag-dir", type=str,
                            default=os.getenv("RAG_WORKING_DIR", "./rag_storage"),
                            help="Base RAG storage directory. Auto-detected from $RAG_WORKING_DIR "
                                 "(same env var used by the ingestion CLI). "
                                 "Must match the path used during ingestion.")
        parser.add_argument("--product-id", type=str, default="",
                            help="Override product ID (e.g. DSR). Auto-extracted from blueprint if omitted.")

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        logger.info(f"Loading Blueprint from: {args.blueprint}")
        bp_data = load_json_input(args.blueprint)
        # Unwrap outer key if the file is a full debugger output (e.g. {"blueprint_output": {...}})
        if "blueprint_output" in bp_data:
            bp_data = bp_data["blueprint_output"]
        
        kb_data = {}
        if args.kb:
            kb_data = load_json_input(args.kb)
            
        # Initialize services and agent dependencies
        from hld_generator.backend.services.oci_client import (
            initialize_oci_services,
            get_oci_client,
            get_cognee_wrapper,
        )
        # Use MultiProductRAGWrapper — matches the storage layout used by the ingestion CLI:
        #   rag_storage/{product_id}/product_docs/   (e.g. rag_storage/DSR/product_docs/)
        # The flat RAGAnythingWrapper(working_dir="./rag_storage") would query the root
        # which has no documents, causing "No LightRAG instance available" errors.
        from hld_generator.shared.multi_product_rag_wrapper import MultiProductRAGWrapper

        initialize_oci_services()
        oci_client = get_oci_client()
        cognee_wrapper = get_cognee_wrapper()

        rag_wrapper = MultiProductRAGWrapper(
            oci_client=oci_client,
            base_working_dir=args.rag_dir,
        )

        agent = RetrievalAgent(
            rag_anything_client=rag_wrapper,
            cognee_wrapper=cognee_wrapper,
        )

        # Extract product_id from blueprint (e.g. "DSR" from {"product": "DSR", ...})
        # This drives execute_queries_node to route to rag_storage/DSR/product_docs/.
        product_id = bp_data.get("product", args.product_id)
        if product_id:
            logger.info(f"Product ID from blueprint: '{product_id}'")
        else:
            logger.warning(
                "No product ID found in blueprint or --product-id flag. "
                "Retrieval will fall back to unscoped aquery() — likely returning no results."
            )

        # Prepare State
        initial_state: RetrievalState = {
            "blueprint": bp_data,
            "product_id": product_id,
            "cognee_dataset_name": args.dataset,
            "document_knowledge_base": kb_data,
            "current_section_id": None,
            "query_execution_log": [],
            "rag_results": {},
            "retrieval_metrics": None,
            "retrieval_complete": False,
            "errors": []
        }
        
        logger.info("Running Retrieval Agent Pipeline...")
        # Note: Cognee might need actual DB connection here
        final_state = await agent.ainvoke(initial_state)
        
        results = final_state.get("rag_results", {})
        logger.info(f"Retrieval Complete. Sections processed: {len(results)}")
        
        return {
            "rag_results": results,
            "retrieval_metrics": final_state.get("retrieval_metrics"),
            "errors": final_state.get("errors")
        }

if __name__ == "__main__":
    RetrievalDebugger("Retrieval Agent Debugger").run()
