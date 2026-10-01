"""
Phase 4: Execution Plan Assembly

Takes the planned sections (Phase 2) and asset assignments (Phase 3), merges them,
then organises everything into generation batches respecting dependency ordering.
Produces the final BlueprintOutput.

This phase is deterministic — no LLM calls. Pure merging and graph-based
dependency resolution.
"""

import logging
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional

from hld_generator.agents.blueprint.state.models import (
    BlueprintOutput,
    GenerationBatch,
)
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class ExecutionPlanPhase:
    """
    Phase 4: Assemble the final execution plan.

    Merges asset assignments into SectionPlans, builds generation batches
    respecting section dependencies, and compiles everything into BlueprintOutput.
    """

    async def execute(
        self,
        planned_sections: List[Dict[str, Any]],
        image_assignments: List[Dict[str, Any]],
        table_assignments: List[Dict[str, Any]],
        knowledge_base: Dict[str, Any],
        product_profile: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]],
        clarifications: List[Dict[str, Any]],
        can_proceed: bool,
        data_assessment_summary: Dict[str, Any],
        identified_product: str,
        document_type: str,
        template_variables: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Execute Phase 4: Execution Plan Assembly.

        Args:
            planned_sections:       SectionPlan dicts from Phase 2
            image_assignments:      [{image_id, section_id, figure_title, assign_reason, confidence}]
            table_assignments:      [{table_id, section_id, use_as, assign_reason, confidence}]
            knowledge_base:         Full DocumentKnowledgeBase dict (contains tables[] with markdown)
            product_profile:             Product profile dict (contains sections[] array defining document order)
            image_inventory:        ImageInventory dict (contains images[] with storage_path)
            clarifications:         Clarification questions (carried from missing_data_critical)
            can_proceed:            Whether generation can proceed
            data_assessment_summary: Summary stats from sections
            identified_product:     Product from Phase 1
            document_type:          "HLD" etc.
            template_variables:     Global variables from Phase 1

        Returns:
            Dict with `blueprint_output` (BlueprintOutput as dict).
        """
        logger.info("Phase 3: Execution Plan Assembly (NEW: Assets already in sections)")

        # NEW: Build section_id → profile array index mapping to preserve profile-defined document order
        # CRITICAL: Use product_profile (not document knowledge_base) — product_profile has sections[] array
        profile_sections = product_profile.get("sections", [])
        profile_section_order = {
            sec.get("section_id"): idx
            for idx, sec in enumerate(profile_sections)
        }

        logger.info(f"  Product profile has {len(profile_sections)} sections in order")

        # Re-sort sections by profile array order (preserves profile-defined order: Executive Summary → 1-10 → Appendices)
        # (Phase 2 returns sections in dependency graph order, but we need profile order for output)
        sections = sorted(
            planned_sections,
            key=lambda s: profile_section_order.get(s.get("section_id"), 999)
        )
        logger.info(f"  Assembling blueprint for {len(sections)} sections (sorted by product profile order)")

        # FIX (BUG 5): Renumber sections sequentially after conditional exclusions
        # When conditional sections 7 and 9 are excluded, remaining sections should be 1-8, not 1,2,3,4,5,6,8,10
        self._renumber_sections_sequentially(sections)
        logger.info(f"  Renumbered sections sequentially to fix gaps from excluded conditional sections")

        # Step 1: Build generation batches (topological sort on dependencies)
        batches = self._build_generation_batches(sections)
        logger.info(f"  Built {len(batches)} generation batches")

        # Step 2: Use only user-provided clarifications (NOT auto-derived from missing_data)
        # Missing data → placeholder content (handled by content generation agent)
        # Do NOT generate clarification questions for missing_data_critical fields
        all_clarifications = clarifications  # Use clarifications passed from Phase 1/2 only
        logger.info(f"  Clarifications: {len(all_clarifications)} (user-provided only, not auto-derived)")

        # Step 3: Calculate summary stats
        total_tokens = sum(s.get("estimated_tokens", 0) for s in sections)
        total_rag_queries = sum(len(s.get("rag_queries", [])) for s in sections)
        total_images_assigned = sum(len(s.get("matched_images", [])) for s in sections)
        total_tables_assigned = sum(len(s.get("matched_tables", [])) for s in sections)

        if not data_assessment_summary:
            data_assessment_summary = {}
        data_assessment_summary.update({
            "total_images_assigned": total_images_assigned,
            "total_tables_assigned": total_tables_assigned,
        })

        # Step 4: Generate blueprint ID
        customer = template_variables.get("customer_name", "unknown").lower()
        customer_slug = customer.replace(" ", "_")[:20]
        date_str = datetime.utcnow().strftime("%Y%m%d")
        blueprint_id = f"bp_{customer_slug}_{identified_product.lower()}_{date_str}"

        # Step 5: Assemble BlueprintOutput
        try:
            blueprint = BlueprintOutput(
                blueprint_id=blueprint_id,
                product=identified_product,
                document_type=document_type,
                customer_name=template_variables.get("customer_name", "[Customer]"),
                project_name=template_variables.get("project_name", "[Project]"),
                sections=sections,
                generation_batches=batches,
                clarifications=all_clarifications,
                can_proceed=can_proceed,
                template_variables=template_variables,
                data_assessment_summary=data_assessment_summary,
                total_estimated_tokens=total_tokens,
                total_rag_queries=total_rag_queries,
            )
            blueprint_dict = blueprint.model_dump()
        except Exception as e:
            logger.warning(f"  Pydantic validation failed, using raw dict: {e}")
            blueprint_dict = {
                "blueprint_id": blueprint_id,
                "created_at": datetime.utcnow().isoformat(),
                "product": identified_product,
                "document_type": document_type,
                "customer_name": template_variables.get("customer_name", "[Customer]"),
                "project_name": template_variables.get("project_name", "[Project]"),
                "sections": sections,
                "generation_batches": [
                    b.model_dump() if hasattr(b, "model_dump") else b for b in batches
                ],
                "clarifications": all_clarifications,
                "can_proceed": can_proceed,
                "template_variables": template_variables,
                "data_assessment_summary": data_assessment_summary,
                "total_estimated_tokens": total_tokens,
                "total_rag_queries": total_rag_queries,
            }

        logger.info(
            f"  Blueprint assembled: {blueprint_id} | "
            f"{len(sections)} sections | {len(batches)} batches | "
            f"~{total_tokens:,} tokens | {total_rag_queries} RAG queries | "
            f"{total_images_assigned} images assigned | {total_tables_assigned} tables assigned | "
            f"can_proceed={can_proceed}"
        )

        return {"blueprint_output": blueprint_dict}

    # ------------------------------------------------------------------
    # Clarification derivation
    # ------------------------------------------------------------------

    def _derive_clarifications(
        self, sections: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Auto-generate clarification questions from missing_data_critical fields
        across all sections. Deduplicates by question text.
        """
        seen: set = set()
        clarifications = []

        for sec in sections:
            title = sec.get("title", "")
            for item in sec.get("missing_data_critical", []):
                if item in seen:
                    continue
                seen.add(item)
                clarifications.append({
                    "priority": "critical",
                    "question": item,
                    "context": f"Required for section: {title} ({sec.get('section_id', '')})",
                    "impact_if_skipped": "This section may be generated with placeholder content.",
                    "can_skip": True,
                    "suggested_format": "",
                })

        return clarifications

    def _renumber_sections_sequentially(self, sections: List[Dict[str, Any]]) -> None:
        """
        Renumber section_number fields sequentially (1, 2, 3...) to fix gaps
        left by excluded conditional sections.

        Modifies sections in-place.

        Example:
            Before: section_numbers = [1, 2, 3, 4, 5, 6, 8, 10] (7 and 9 excluded)
            After:  section_numbers = [1, 2, 3, 4, 5, 6, 7, 8]
        """
        counter = 1
        for section in sections:
            # Only renumber top-level sections (those with section_number like "1", "2", not "1.1")
            section_num = section.get("section_number", "")
            if section_num and "." not in str(section_num):
                section["section_number"] = str(counter)
                counter += 1
            # Subsections keep their hierarchical numbering (e.g., "3.1", "3.2.1")

    # ------------------------------------------------------------------
    # Generation batch builder (Kahn's topological sort)
    # ------------------------------------------------------------------

    def _build_generation_batches(
        self, sections: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Build generation batches using topological sort on section dependencies.

        Sections with no dependencies → batch 1.
        Sections depending on batch N sections → batch N+1.
        Sections within the same batch can run in parallel.
        """
        section_ids = {s.get("section_id", f"sec_{i}") for i, s in enumerate(sections)}
        deps_graph: Dict[str, List[str]] = {}
        in_degree: Dict[str, int] = {}

        for i, section in enumerate(sections):
            sid = section.get("section_id", f"sec_{i}")
            deps = section.get("dependencies", [])
            valid_deps = [d for d in deps if d in section_ids and d != sid]
            deps_graph[sid] = valid_deps
            in_degree[sid] = len(valid_deps)

        # Kahn's algorithm — group by level
        levels: List[List[str]] = []
        queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
        remaining = set(in_degree.keys())

        while queue:
            current_level = list(queue)
            levels.append(current_level)
            queue.clear()

            for sid in current_level:
                remaining.discard(sid)
                for other_sid, deps in deps_graph.items():
                    if sid in deps:
                        in_degree[other_sid] -= 1
                        if in_degree[other_sid] == 0 and other_sid in remaining:
                            queue.append(other_sid)

        if remaining:
            logger.warning(f"  Circular dependencies detected: {remaining}")
            levels.append(list(remaining))

        # Assign generate_order to sections and build batch dicts
        batches = []
        section_to_order: Dict[str, int] = {}

        for batch_num, section_ids_in_batch in enumerate(levels, start=1):
            depends_on = batch_num - 1 if batch_num > 1 else None
            for sid in section_ids_in_batch:
                section_to_order[sid] = batch_num

            try:
                batch = GenerationBatch(
                    batch_number=batch_num,
                    section_ids=section_ids_in_batch,
                    depends_on_batch=depends_on,
                    can_parallel=len(section_ids_in_batch) > 1,
                )
                batches.append(batch.model_dump())
            except Exception:
                batches.append({
                    "batch_number": batch_num,
                    "section_ids": section_ids_in_batch,
                    "depends_on_batch": depends_on,
                    "can_parallel": len(section_ids_in_batch) > 1,
                })

        # Back-fill generate_order into merged sections
        for section in sections:
            sid = section.get("section_id", "")
            if sid in section_to_order:
                section["generate_order"] = section_to_order[sid]

        return batches
