"""
Debugger for Assembly Agent.
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
try:
    from hld_generator.agents.assembly.agent import AssemblyAgent
    from hld_generator.agents.assembly.state.schema import AssemblyState
except ImportError:
    # Assuming Assembly Agent exists or will exist soon
    try:
        from hld_generator.agents.assembly.agent import AssemblyAgent
        from hld_generator.agents.assembly.state.schema import AssemblyState
    except ImportError:
         print("Assembly Agent not yet implemented. Creating MOCK debugger.")
         AssemblyAgent = None
         AssemblyState = None

class AssemblyDebugger(AgentDebugger):
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--blueprint", type=str, required=True, help="Path to Blueprint Output JSON file")
        parser.add_argument("--sections", type=str, required=True, help="Path to Generated Sections JSON file")
        parser.add_argument("--images", type=str, help="Path to Image Library JSON file")
        parser.add_argument("--context", type=str, help="Path to Project Context (KB) JSON file")
        parser.add_argument("--output-dir", type=str, default="./output", help="Directory to save assembled docs")

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        if not AssemblyAgent:
            logger.error("Assembly Agent not installed/implemented.")
            return {"error": "Assembly Agent missing"}

        logger.info(f"Loading Blueprint from: {args.blueprint}")
        bp_data = load_json_input(args.blueprint)
        
        logger.info(f"Loading Sections from: {args.sections}")
        sec_data = load_json_input(args.sections)
            
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

        agent = AssemblyAgent(
            llm_client=llm_client,
            output_dir=args.output_dir,
            output_formats=["docx", "pdf", "html"],
        )
        
        # Prepare State
        initial_state: AssemblyState = {
            "blueprint": bp_data,
            "generated_sections": sec_data,
            "final_image_library": img_data,
            "project_context": ctx_data,
            "llm_client": llm_client,
            "output_dir": args.output_dir,
            "output_formats": ["docx", "pdf", "html"],
            
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
            "warnings": []
        }
        
        logger.info("Running Assembly Agent Pipeline...")
        final_state = await agent.ainvoke(initial_state)
        
        files = final_state.get("exported_files", {})
        logger.info(f"Assembly Complete. Files created: {files}")
        
        return {
            "assembled_document": final_state.get("assembled_document"),
            "exported_files": files,
            "errors": final_state.get("errors")
        }

if __name__ == "__main__":
    AssemblyDebugger("Assembly Agent Debugger").run()
