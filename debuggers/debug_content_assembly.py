"""
Combined Content Generation + Assembly Debugger.

Runs both agents in sequence:
  Content Generation Agent → Assembly Agent

The output of Content Generation is piped directly into Assembly
in-memory — no intermediate file needed.
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
_hld_init = PROJECT_DIR / "__init__.py"
if _hld_init.exists() and "hld_generator" not in sys.modules:
    _spec = _ilu.spec_from_file_location(
        "hld_generator", str(_hld_init),
        submodule_search_locations=[str(PROJECT_DIR)]
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules["hld_generator"] = _mod
    _spec.loader.exec_module(_mod)

from debuggers.base import AgentDebugger, load_json_input

from hld_generator.agents.content_generation.agent import ContentGenerationAgent
from hld_generator.agents.content_generation.state.schema import ContentGenerationState
from hld_generator.agents.assembly.agent import AssemblyAgent
from hld_generator.agents.assembly.state.schema import AssemblyState


_DIVIDER = "=" * 56


class _LLMWrapper:
    """
    Bridges OCILLMAdapter to the chat(system_prompt, user_prompt) -> str
    interface expected by all ContentGeneration and Assembly strategies.

    Strategies call:
        await self.llm_client.chat(system_prompt="...", user_prompt="...")
    OCILLMAdapter provides:
        await adapter.create_chat_completion(messages=[...]) -> str
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


class ContentAssemblyDebugger(AgentDebugger):

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            "--blueprint", type=str, required=True,
            help="Path to Blueprint Output JSON file"
        )
        parser.add_argument(
            "--rag", type=str,
            help="Path to Retrieval Agent output JSON (rag_results)"
        )
        parser.add_argument(
            "--images", type=str,
            help="Path to Image Library JSON file"
        )
        parser.add_argument(
            "--context", type=str,
            help="Path to Project Context (DocumentKnowledgeBase) JSON file"
        )
        parser.add_argument(
            "--parsed", type=str,
            help="Path to parsed document plain-text file (.txt) for LLM grounding"
        )
        parser.add_argument(
            "--dataset", type=str, default="debug_dataset",
            help="Cognee dataset name (default: debug_dataset)"
        )
        parser.add_argument(
            "--output-dir", type=str, default="./outputs/assembly",
            help="Directory for assembled documents (default: ./outputs/assembly)"
        )

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:

        # ── Load inputs ───────────────────────────────────────────────────
        logger.info(f"Loading Blueprint from: {args.blueprint}")
        bp_data = load_json_input(args.blueprint)
        # Unwrap if this is a full pipeline output JSON (blueprint nested under "blueprint_output")
        if "blueprint_output" in bp_data and "sections" not in bp_data:
            bp_data = bp_data["blueprint_output"]
            logger.info("Unwrapped blueprint from 'blueprint_output' key")

        rag_data = {}
        if args.rag:
            logger.info(f"Loading RAG results from: {args.rag}")
            rag_data = load_json_input(args.rag)

        img_data = {}
        if args.images:
            img_path = Path(args.images)
            if img_path.is_dir():
                logger.warning(
                    f"--images path is a directory, not a JSON file — skipping image library. "
                    f"Pass a JSON file exported from the Image Generation Agent."
                )
            else:
                logger.info(f"Loading Image Library from: {args.images}")
                img_data = load_json_input(args.images)

        ctx_data = {}
        if args.context:
            logger.info(f"Loading Project Context from: {args.context}")
            ctx_data = load_json_input(args.context)

        parsed_content = ""
        if args.parsed:
            logger.info(f"Loading parsed document text from: {args.parsed}")
            try:
                parsed_content = Path(args.parsed).read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read parsed content file: {e}")

        # ── Initialize OCI (Cognee adapter + LLM wrapper) ────────────────
        from hld_generator.backend.services.oci_client import initialize_oci_services
        from hld_generator.external.oci_adapters import OCILLMAdapter
        initialize_oci_services()
        # Wrap OCILLMAdapter in _LLMWrapper so strategies can call:
        #   await llm_client.chat(system_prompt=..., user_prompt=...)
        llm_client = _LLMWrapper(OCILLMAdapter())

        # ─────────────────────────────────────────────────────────────────
        # Phase 1: Content Generation
        # ─────────────────────────────────────────────────────────────────
        logger.info(_DIVIDER)
        logger.info("Phase 1: Content Generation Agent")
        logger.info(_DIVIDER)

        content_agent = ContentGenerationAgent(
            llm_client=llm_client,
            config={"debug": args.debug},
        )

        content_state: ContentGenerationState = {
            "blueprint": bp_data,
            "rag_results": rag_data,
            "final_image_library": img_data,
            "project_context": ctx_data,
            "parsed_content": parsed_content,
            "cognee_dataset_name": args.dataset,
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
        content_warnings = content_result.get("warnings", [])

        logger.info(f"Content Generation complete — {len(generated_sections)} section(s) generated")
        for sec_id, sec in generated_sections.items():
            logger.info(
                f"  [{sec.get('section_number', '?')}] {sec.get('title', sec_id)}"
                f"  ({sec.get('word_count', 0)} words, strategy={sec.get('generation_metadata', {}).get('strategy_used', '?')})"
            )
        if content_errors:
            logger.warning(f"Content Generation errors: {content_errors}")

        if not generated_sections:
            logger.error("No sections generated — aborting Assembly.")
            return {
                "generated_sections": {},
                "assembled_document": None,
                "exported_files": {},
                "errors": content_errors + ["No sections generated; Assembly skipped"],
                "warnings": content_warnings,
            }

        # ─────────────────────────────────────────────────────────────────
        # Phase 2: Assembly
        # ─────────────────────────────────────────────────────────────────
        logger.info(_DIVIDER)
        logger.info("Phase 2: Assembly Agent")
        logger.info(_DIVIDER)

        assembly_agent = AssemblyAgent(
            llm_client=llm_client,
            output_dir=args.output_dir,
            output_formats=["markdown", "docx"],
        )

        assembly_state: AssemblyState = {
            "blueprint": bp_data,
            "generated_sections": generated_sections,
            "final_image_library": img_data,
            "project_context": ctx_data,
            "llm_client": llm_client,
            "output_dir": args.output_dir,
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
        assembly_warnings = assembly_result.get("warnings", [])

        logger.info(f"Assembly complete — files created: {exported_files}")
        if assembly_errors:
            logger.warning(f"Assembly errors: {assembly_errors}")

        return {
            "generated_sections": generated_sections,
            "assembled_document": assembly_result.get("assembled_document"),
            "exported_files": exported_files,
            "errors": content_errors + assembly_errors,
            "warnings": content_warnings + assembly_warnings,
        }


if __name__ == "__main__":
    ContentAssemblyDebugger("Content Generation + Assembly Debugger").run()
