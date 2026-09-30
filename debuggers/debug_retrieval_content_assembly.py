"""
Debugger for Retrieval + Content Generation + Assembly (Chained).

Runs three agents sequentially:
1. Retrieval Agent - executes RAG queries from blueprint
2. Content Generation Agent - generates section content using RAG results
3. Assembly Agent - compiles into final document

This mimics stages 3-5 of the full pipeline.
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

# Import Agents
from hld_generator.agents.retrieval.agent import RetrievalAgent
from hld_generator.agents.retrieval.state.schema import RetrievalState
from hld_generator.agents.content_generation.agent import ContentGenerationAgent
from hld_generator.agents.content_generation.state.schema import ContentGenerationState
from hld_generator.agents.assembly.agent import AssemblyAgent
from hld_generator.agents.assembly.state.schema import AssemblyState


_DIVIDER = "=" * 60


class _LLMWrapper:
    """
    Bridges OCILLMAdapter to the chat(system_prompt, user_prompt) -> str
    interface expected by all ContentGeneration and Assembly strategies.
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


class RetrievalContentAssemblyDebugger(AgentDebugger):
    """Combined debugger for Retrieval → Content Generation → Assembly pipeline."""

    def add_arguments(self, parser: argparse.ArgumentParser):
        # Inputs
        parser.add_argument(
            "--blueprint",
            type=str,
            required=True,
            help="Path to Blueprint Output JSON file (required)"
        )
        parser.add_argument(
            "--kb",
            type=str,
            help="Path to Document Knowledge Base JSON (optional, for context)"
        )
        parser.add_argument(
            "--images",
            type=str,
            help="Path to Image Library JSON file (optional)"
        )
        parser.add_argument(
            "--parsed",
            type=str,
            help="Path to parsed document plain-text file for LLM grounding (optional)"
        )

        # Configuration
        parser.add_argument(
            "--dataset",
            type=str,
            default="debug_dataset",
            help="Cognee dataset name (default: debug_dataset)"
        )
        parser.add_argument(
            "--rag-dir",
            type=str,
            default=os.getenv("RAG_WORKING_DIR", "./rag_storage"),
            help="Base RAG storage directory (default: ./rag_storage or $RAG_WORKING_DIR)"
        )
        parser.add_argument(
            "--product-id",
            type=str,
            default="",
            help="Override product ID (e.g. DSR). Auto-extracted from blueprint if omitted."
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="./outputs/assembly",
            help="Directory for assembled documents (default: ./outputs/assembly)"
        )

        # Optional stage controls
        parser.add_argument(
            "--save-retrieval-output",
            type=str,
            help="Optional: Save Retrieval Agent output to separate JSON file"
        )
        parser.add_argument(
            "--save-content-output",
            type=str,
            help="Optional: Save Content Generation output to separate JSON file"
        )

    async def execute(self, args: argparse.Namespace, logger: logging.Logger) -> Dict[str, Any]:
        """
        Execute all three agents in sequence.

        Returns:
            Combined output with retrieval, content, and assembly results
        """
        # ============================================================
        # Load Common Inputs
        # ============================================================
        logger.info("Loading inputs...")

        bp_data = load_json_input(args.blueprint)
        # Unwrap if nested under blueprint_output key
        if "blueprint_output" in bp_data and "sections" not in bp_data:
            bp_data = bp_data["blueprint_output"]
            logger.info("Unwrapped blueprint from 'blueprint_output' key")

        kb_data = {}
        if args.kb:
            kb_data = load_json_input(args.kb)
            # Unwrap if nested under knowledge_base key
            if "knowledge_base" in kb_data and "products" not in kb_data:
                kb_data = kb_data["knowledge_base"]
                logger.info("Unwrapped KB from 'knowledge_base' key")

        img_data = {}
        if args.images:
            img_path = Path(args.images)
            if img_path.is_dir():
                logger.warning("--images path is a directory, skipping")
            else:
                img_data = load_json_input(args.images)

        parsed_content = ""
        if args.parsed:
            try:
                parsed_content = Path(args.parsed).read_text(encoding="utf-8")
                logger.info(f"Loaded {len(parsed_content):,} chars of parsed content")
            except Exception as e:
                logger.warning(f"Could not read parsed content: {e}")

        # Extract product ID
        product_id = bp_data.get("product", args.product_id)
        logger.info(f"Product ID: {product_id or 'Not specified'}")
        logger.info("")

        # ============================================================
        # Initialize OCI Services
        # ============================================================
        from hld_generator.backend.services.oci_client import (
            initialize_oci_services,
            get_oci_client,
            get_cognee_wrapper,
        )
        from hld_generator.shared.multi_product_rag_wrapper import MultiProductRAGWrapper
        from hld_generator.external.oci_adapters import OCILLMAdapter

        initialize_oci_services()
        oci_client = get_oci_client()
        cognee_wrapper = get_cognee_wrapper()

        rag_wrapper = MultiProductRAGWrapper(
            oci_client=oci_client,
            base_working_dir=args.rag_dir,
        )

        llm_client = _LLMWrapper(OCILLMAdapter())

        # ============================================================
        # STAGE 1: Retrieval Agent
        # ============================================================
        logger.info(_DIVIDER)
        logger.info("STAGE 1: Retrieval Agent")
        logger.info(_DIVIDER)
        logger.info(f"Blueprint Sections: {len(bp_data.get('sections', []))}")
        logger.info(f"RAG Directory: {args.rag_dir}")
        logger.info("")

        retrieval_agent = RetrievalAgent(
            rag_anything_client=rag_wrapper,
            cognee_wrapper=cognee_wrapper,
        )

        retrieval_state: RetrievalState = {
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

        logger.info("Running Retrieval Agent pipeline...")
        retrieval_result = await retrieval_agent.ainvoke(retrieval_state)

        rag_results = retrieval_result.get("rag_results", {})
        retrieval_metrics = retrieval_result.get("retrieval_metrics")
        retrieval_errors = retrieval_result.get("errors", [])

        logger.info(f"Retrieval Complete")
        logger.info(f"   Sections Processed: {len(rag_results)}")
        if retrieval_metrics:
            logger.info(f"   Total Queries: {retrieval_metrics.get('total_queries', 0)}")
            logger.info(f"   Total Chunks: {retrieval_metrics.get('total_chunks_retrieved', 0)}")
        if retrieval_errors:
            logger.warning(f"   Errors: {retrieval_errors}")
        logger.info("")

        # Save retrieval output if requested
        retrieval_output = {
            "rag_results": rag_results,
            "retrieval_metrics": retrieval_metrics,
            "errors": retrieval_errors
        }

        if args.save_retrieval_output:
            import json
            save_path = Path(args.save_retrieval_output).resolve()

            # Handle directory paths - append default filename
            if save_path.is_dir():
                save_path = save_path / "retrieval_output.json"
            elif not save_path.suffix:
                # No extension - treat as directory
                save_path.mkdir(parents=True, exist_ok=True)
                save_path = save_path / "retrieval_output.json"

            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(retrieval_output, f, indent=2, default=str)
            logger.info(f"Retrieval output saved to: {save_path}")
            logger.info("")

        # ============================================================
        # STAGE 2: Content Generation Agent
        # ============================================================
        logger.info(_DIVIDER)
        logger.info("STAGE 2: Content Generation Agent")
        logger.info(_DIVIDER)

        content_agent = ContentGenerationAgent(
            llm_client=llm_client,
            config={"debug": args.debug},
        )

        content_state: ContentGenerationState = {
            "blueprint": bp_data,
            "rag_results": rag_results,
            "final_image_library": img_data,
            "project_context": kb_data,
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

        logger.info("Running Content Generation pipeline...")
        content_result = await content_agent.ainvoke(content_state)

        generated_sections = content_result.get("generated_sections", {})
        content_errors = content_result.get("errors", [])
        content_warnings = content_result.get("warnings", [])

        logger.info(f"Content Generation Complete")
        logger.info(f"   Sections Generated: {len(generated_sections)}")
        for sec_id, sec in list(generated_sections.items())[:5]:
            logger.info(
                f"   [{sec.get('section_number', '?')}] {sec.get('title', sec_id)[:50]} "
                f"({sec.get('word_count', 0)} words)"
            )
        if len(generated_sections) > 5:
            logger.info(f"   ... and {len(generated_sections) - 5} more sections")
        if content_errors:
            logger.warning(f"   Errors: {content_errors}")
        logger.info("")

        # Save content output if requested
        content_output = {
            "generated_sections": generated_sections,
            "errors": content_errors,
            "warnings": content_warnings
        }

        if args.save_content_output:
            import json
            save_path = Path(args.save_content_output).resolve()

            # Handle directory paths - append default filename
            if save_path.is_dir():
                save_path = save_path / "content_output.json"
            elif not save_path.suffix:
                # No extension - treat as directory
                save_path.mkdir(parents=True, exist_ok=True)
                save_path = save_path / "content_output.json"

            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(content_output, f, indent=2, default=str)
            logger.info(f"Content output saved to: {save_path}")
            logger.info("")

        if not generated_sections:
            logger.error("No sections generated — aborting Assembly")
            return {
                "stage_1_retrieval": retrieval_output,
                "stage_2_content": content_output,
                "stage_3_assembly": {
                    "errors": ["No sections generated; Assembly skipped"]
                },
                "pipeline_summary": {
                    "retrieval_sections": len(rag_results),
                    "generated_sections": 0,
                    "assembly_status": "skipped",
                    "errors": content_errors + ["No sections generated"]
                }
            }

        # ============================================================
        # STAGE 3: Assembly Agent
        # ============================================================
        logger.info(_DIVIDER)
        logger.info("STAGE 3: Assembly Agent")
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
            "project_context": kb_data,
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

        logger.info("Running Assembly pipeline...")
        assembly_result = await assembly_agent.ainvoke(assembly_state)

        exported_files = assembly_result.get("exported_files", {})
        assembly_errors = assembly_result.get("errors", [])
        assembly_warnings = assembly_result.get("warnings", [])
        quality_checks = assembly_result.get("quality_checks", [])

        logger.info(f"Assembly Complete")
        if exported_files:
            logger.info(f"   Exported Files:")
            for fmt, path in exported_files.items():
                logger.info(f"     {fmt.upper()}: {path}")
        else:
            logger.warning("   No files exported")

        if quality_checks:
            passed = [c for c in quality_checks if c.get("passed")]
            failed = [c for c in quality_checks if not c.get("passed")]
            logger.info(f"   Quality Checks: {len(passed)} passed, {len(failed)} failed")

        if assembly_errors:
            logger.warning(f"   Errors: {assembly_errors}")
        logger.info("")

        # ============================================================
        # Final Summary
        # ============================================================
        logger.info(_DIVIDER)
        logger.info("PIPELINE COMPLETE")
        logger.info(_DIVIDER)

        all_errors = retrieval_errors + content_errors + assembly_errors
        all_warnings = content_warnings + assembly_warnings

        if all_errors:
            logger.warning(f"Total Errors: {len(all_errors)}")
        if all_warnings:
            logger.info(f"Total Warnings: {len(all_warnings)}")

        logger.info(f"Final Document: {exported_files.get('markdown', 'Not generated')}")

        # Return combined output
        return {
            "stage_1_retrieval": retrieval_output,
            "stage_2_content": content_output,
            "stage_3_assembly": {
                "exported_files": exported_files,
                "quality_checks": quality_checks,
                "errors": assembly_errors,
                "warnings": assembly_warnings
            },
            "pipeline_summary": {
                "blueprint_id": bp_data.get("blueprint_id"),
                "product": product_id,
                "retrieval_sections": len(rag_results),
                "retrieval_total_queries": retrieval_metrics.get("total_queries", 0) if retrieval_metrics else 0,
                "retrieval_total_chunks": retrieval_metrics.get("total_chunks_retrieved", 0) if retrieval_metrics else 0,
                "generated_sections": len(generated_sections),
                "exported_files": list(exported_files.keys()),
                "total_errors": len(all_errors),
                "total_warnings": len(all_warnings),
                "assembly_status": "completed" if exported_files else "failed"
            }
        }


if __name__ == "__main__":
    RetrievalContentAssemblyDebugger(
        "Retrieval + Content Generation + Assembly Debugger (Chained Pipeline)"
    ).run()
