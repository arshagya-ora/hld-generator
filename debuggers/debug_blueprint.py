"""
Debugger for Blueprint Agent.
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

from debuggers.base import AgentDebugger, load_json_input

# Import Agent
try:
    from hld_generator.agents.blueprint.agent import BlueprintAgent
except ImportError:
    from agents.blueprint.agent import BlueprintAgent

class BlueprintDebugger(AgentDebugger):
    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--kb", type=str, required=True, help="Path to Knowledge Base JSON file")
        parser.add_argument("--images", type=str, help="Path to Image Inventory JSON file")
        parser.add_argument("--dataset", type=str, default="debug_dataset", help="Cognee dataset name")

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        logger.info(f"Loading Knowledge Base from: {args.kb}")
        raw = load_json_input(args.kb)

        # Auto-unwrap if the file is the full Document Analyzer output
        # (which contains 'knowledge_base' and optionally 'image_inventory' at top level)
        if "knowledge_base" in raw:
            logger.info("Detected Document Analyzer output format — unwrapping 'knowledge_base'")
            embedded_images = raw.get("image_inventory", {})
            kb_data = raw["knowledge_base"]
        else:
            kb_data = raw
            embedded_images = {}

        img_data = {}
        if args.images:
            img_path = Path(args.images)
            if not img_path.is_file():
                logger.warning(f"--images path is not a file, skipping: {args.images}")
            else:
                logger.info(f"Loading Image Inventory from: {args.images}")
                img_data = load_json_input(args.images)
        elif embedded_images:
            logger.info("Using image_inventory embedded in the Knowledge Base file")
            img_data = embedded_images
            
        # Initialize Agent
        agent = BlueprintAgent(config={"debug": args.debug})

        logger.info("Running Blueprint Agent Pipeline...")
        bp = await agent.run(
            knowledge_base=kb_data,
            image_inventory=img_data,
            cognee_dataset_name=args.dataset,
        )
        logger.info(f"Blueprint Generated: {bp.get('blueprint_id')}")
        logger.info(f"Sections: {len(bp.get('sections', []))}")
            
        return {
            "blueprint_output": bp,
            "clarifications": bp.get("clarifications", []),
            "errors": []
        }

if __name__ == "__main__":
    BlueprintDebugger("Blueprint Agent Debugger").run()
