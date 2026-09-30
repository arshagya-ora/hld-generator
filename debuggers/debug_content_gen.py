"""
Debugger for Content Generation Agent.
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

from debuggers.base import AgentDebugger, load_json_input

# Import Agent
from hld_generator.agents.content_generation.agent import ContentGenerationAgent
from hld_generator.agents.content_generation.state.schema import ContentGenerationState

class ContentGenerationDebugger(AgentDebugger):
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--blueprint", type=str, required=True, help="Path to Blueprint Output JSON file")
        parser.add_argument("--rag", type=str, help="Path to RAG Results JSON file")
        parser.add_argument("--images", type=str, help="Path to Image Library JSON file")
        parser.add_argument("--context", type=str, help="Path to Project Context (KB) JSON file")
        parser.add_argument("--dataset", type=str, default="debug_dataset", help="Cognee dataset name")

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        logger.info(f"Loading Blueprint from: {args.blueprint}")
        bp_data = load_json_input(args.blueprint)
        
        rag_data = {}
        if args.rag:
            rag_data = load_json_input(args.rag)
            
        img_data = {}
        if args.images:
            img_data = load_json_input(args.images)
            
        ctx_data = {}
        if args.context:
            ctx_data = load_json_input(args.context)
            
        # Initialize Agent
        from hld_generator.backend.services.oci_client import (
            initialize_oci_services,
            get_oci_client,
        )

        initialize_oci_services()
        llm_client = get_oci_client()

        agent = ContentGenerationAgent(llm_client=llm_client, config={"debug": args.debug})
        
        # Prepare State
        initial_state: ContentGenerationState = {
            "blueprint": bp_data,
            "rag_results": rag_data,
            "final_image_library": img_data,
            "project_context": ctx_data,
            "cognee_dataset_name": args.dataset,
            
            "generation_queue": [],
            "current_section_index": 0,
            "current_section_id": None,
            "current_strategy": None,
            "generated_sections": {},
            "generation_complete": False,
            "errors": [],
            "warnings": []
        }
        
        logger.info("Running Content Generation Agent Pipeline...")
        # Since this can take a long time, we might want to allow filtering which sections to run
        # but for now, run all as per blueprint
        final_state = await agent.ainvoke(initial_state)
        
        sections = final_state.get("generated_sections", {})
        logger.info(f"Content Generation Complete. Sections generated: {len(sections)}")
        
        return {
            "generated_sections": sections,
            "errors": final_state.get("errors")
        }

if __name__ == "__main__":
    ContentGenerationDebugger("Content Generation Agent Debugger").run()
