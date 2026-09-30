"""
LangGraph nodes for Content Generation Agent.
"""

import logging
import asyncio
from typing import Dict, Any, List
from itertools import groupby

from langgraph.graph import END

from hld_generator.agents.content_generation.state.schema import ContentGenerationState
from hld_generator.agents.content_generation.strategies import HybridStrategy

logger = logging.getLogger(__name__)

# Maximum concurrent LLM calls (same as Blueprint Phase 2)
MAX_PARALLEL_SECTIONS = 5


class ContentGenerationNodes:
    """
    Nodes for the Content Generation LangGraph pipeline.
    """

    def __init__(self, llm_client, config: Dict[str, Any]):
        self.llm_client = llm_client
        self.config = config

        # Single unified strategy for all sections — Hybrid provides the most
        # complete prompt (profile content_patterns, RAG, project facts, hallucination
        # guards, quality checks, exemplar snippets, figure/table injection).
        self.strategy = HybridStrategy(llm_client, config)

    async def initialize_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Initialize generation process.
        - Validates inputs
        - Builds generation queue
        """
        logger.info("Initializing Content Generation...")
        
        blueprint = state.get("blueprint", {})
        sections = blueprint.get("sections", [])
        
        if not sections:
            return {
                "errors": ["No sections found in Blueprint"],
                "generation_complete": False
            }

        # Sections the Assembly Agent handles independently — never generate content for these
        ASSEMBLY_OWNED_SECTIONS = {"sec_executive_summary"}

        # Filter out excluded sections (include=False) and assembly-owned sections
        included_sections = [
            s for s in sections
            if s.get("include", True) and s.get("section_id") not in ASSEMBLY_OWNED_SECTIONS
        ]
        excluded_count = len(sections) - len(included_sections)
        if excluded_count:
            logger.info(f"Skipping {excluded_count} sections (include=False or assembly-owned)")

        # Sort sections by generate_order if available, otherwise by section index
        sorted_sections = sorted(included_sections, key=lambda s: s.get("generate_order", 0))
        
        return {
            "generation_queue": sorted_sections,
            "current_section_index": 0,
            "generated_sections": {},
            "errors": [],
            "warnings": []
        }

    async def generate_all_batches_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Generate all sections in parallel batches based on generate_order (dependency levels).

        This replaces the old sequential loop with batch-parallel processing:
        - Groups sections by generate_order (dependency levels)
        - Processes each level sequentially (respects dependencies)
        - Within each level, generates all sections in parallel using asyncio.gather()
        - Uses semaphore to limit concurrent LLM calls (max 5)

        Pattern reused from Blueprint Phase 2 section batching.
        """
        queue = state.get("generation_queue", [])

        if not queue:
            logger.warning("No sections in generation queue")
            return {
                "generated_sections": {},
                "generation_complete": True
            }

        logger.info(f"Starting parallel batch generation for {len(queue)} sections")

        # Group sections by generate_order (dependency levels)
        sorted_sections = sorted(queue, key=lambda s: s.get("generate_order", 0))
        levels = [list(group) for _, group in groupby(sorted_sections, key=lambda s: s.get("generate_order", 0))]

        logger.info(f"  {len(queue)} sections organized into {len(levels)} dependency levels")

        # Semaphore to limit concurrent LLM calls (avoid OCI rate limits)
        semaphore = asyncio.Semaphore(MAX_PARALLEL_SECTIONS)

        # Accumulated results
        all_generated_sections = {}
        all_errors = []

        # Process level by level (sequential to respect dependencies)
        for level_idx, level_sections in enumerate(levels):
            level_order = level_sections[0].get("generate_order", 0)
            logger.info(f"  Level {level_idx} (generate_order={level_order}): Generating {len(level_sections)} sections in parallel")

            # Create async tasks for all sections in this level
            async def generate_with_semaphore(section_plan):
                async with semaphore:
                    section_id = section_plan.get("section_id")
                    try:
                        logger.info(f"    Starting generation for section: {section_id}")

                        # Extract data needed for generation
                        all_rag_results = state.get("rag_results", {})
                        rag_content = all_rag_results.get(section_id, {})

                        # Warn if section has RAG queries but no retrieval results
                        if not rag_content and section_plan.get("rag_queries"):
                            logger.warning(
                                f"Section '{section_id}' has {len(section_plan['rag_queries'])} RAG queries "
                                f"but no retrieval results found. Possible section_id mismatch or retrieval failure."
                            )

                        project_context = state.get("project_context", {})
                        template_vars = state.get("blueprint", {}).get("template_variables", {})
                        parsed_content = state.get("parsed_content", "")
                        image_lib = state.get("final_image_library", {})

                        # Generate content using strategy
                        generated_section = await self.strategy.generate(
                            section_plan=section_plan,
                            rag_content=rag_content,
                            image_library=image_lib,
                            project_context=project_context,
                            template_variables=template_vars,
                            parsed_content=parsed_content,
                        )

                        logger.info(f"    Completed generation for section: {section_id}")
                        return (section_id, generated_section.dict(), None)

                    except Exception as e:
                        logger.error(f"    Generation failed for section {section_id}: {e}")
                        return (section_id, None, str(e))

            # Execute all sections in this level in parallel
            tasks = [generate_with_semaphore(section) for section in level_sections]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                # Handle exceptions from gather
                if isinstance(result, Exception):
                    logger.error(f"    Unexpected exception in batch: {result}")
                    all_errors.append(f"Batch exception: {str(result)}")
                    continue

                section_id, generated_dict, error = result

                if error:
                    all_errors.append(f"Failed section {section_id}: {error}")
                elif generated_dict:
                    all_generated_sections[section_id] = generated_dict

            logger.info(f"  Level {level_idx} complete: {len([r for r in results if not isinstance(r, Exception) and r[2] is None])} succeeded, {len([r for r in results if isinstance(r, Exception) or (not isinstance(r, Exception) and r[2] is not None)])} failed")

        logger.info(f"Parallel batch generation complete: {len(all_generated_sections)}/{len(queue)} sections generated")

        return {
            "generated_sections": all_generated_sections,
            "errors": state.get("errors", []) + all_errors,
            "generation_complete": True
        }

    async def check_queue_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        DEPRECATED: Replaced by generate_all_batches_node.
        Kept for backward compatibility but no longer used in new graph.
        """
        queue = state.get("generation_queue", [])
        idx = state.get("current_section_index", 0)

        if idx < len(queue):
            current_section = queue[idx]
            return {
                "current_section_id": current_section.get("section_id"),
                # "generation_complete": False # Don't set this yet
            }
        else:
            return {"generation_complete": True}

    async def select_strategy_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        All sections now use the unified Hybrid strategy.
        This node is kept for graph compatibility.
        """
        return {"current_strategy": "hybrid"}

    async def generate_content_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Execute the Hybrid generation strategy for the current section.
        """
        idx = state.get("current_section_index", 0)
        section_plan = state["generation_queue"][idx]
        section_id = section_plan.get("section_id")

        strategy = self.strategy

        # Extract RAG content for this section specifically
        all_rag_results = state.get("rag_results", {})
        rag_content = all_rag_results.get(section_id, {})

        # Warn if section has RAG queries but no retrieval results (silent mismatch)
        if not rag_content and section_plan.get("rag_queries"):
            logger.warning(
                f"Section '{section_id}' has {len(section_plan['rag_queries'])} RAG queries "
                f"but no retrieval results found. Possible section_id mismatch or retrieval failure."
            )

        # Project context
        project_context = state.get("project_context", {})
        template_vars = state.get("blueprint", {}).get("template_variables", {})

        # Parsed document for grounding
        parsed_content = state.get("parsed_content", "")

        # Images
        image_lib = state.get("final_image_library", {})

        try:
            generated_section = await strategy.generate(
                section_plan=section_plan,
                rag_content=rag_content,
                image_library=image_lib,
                project_context=project_context,
                template_variables=template_vars,
                parsed_content=parsed_content,
            )
            
            # Store result
            current_generated = state.get("generated_sections", {})
            current_generated[section_id] = generated_section.dict()
            
            return {
                "generated_sections": current_generated
            }
            
        except Exception as e:
            logger.error(f"Generation failed for section {section_id}: {e}")
            return {
                "errors": state.get("errors", []) + [f"Failed section {section_id}: {str(e)}"]
            }

    async def post_process_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Post-processing: Image insertion, formatting, etc.
        For now, this is a placeholder or minimal implementation.
        """
        # TODO: Implement image insertion logic here or in strategy
        # Currently Strategies are doing basic generation. 
        # Future: Parse markdown, insert image links, fix headers.
        
        return {} # No state change needed yet

    async def advance_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Move to next section.
        """
        return {
            "current_section_index": state.get("current_section_index", 0) + 1
        }

    async def finalize_node(self, state: ContentGenerationState) -> Dict[str, Any]:
        """
        Final cleanup and metrics.
        """
        logger.info("Content Generation Complete.")
        return {
            "generation_complete": True
        }
