"""
LangGraph node functions for the Blueprint Agent pipeline.

Each node function reads from and writes to the BlueprintState TypedDict.
The nodes wrap the phase classes, adapting them to the LangGraph node interface.

NEW ARCHITECTURE (3 phases):
  Phase 1 (identify_product + global planning) →
  Phase 2 (section-by-section planning with integrated asset assignment) →
  Phase 3 (build_execution_plan)

OLD ARCHITECTURE (deprecated):
  Phase 1 (identify_product) → Phase 2 (plan_sections) →
  Phase 3 (assign_assets)   → Phase 4 (build_execution_plan)
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from hld_generator.agents.blueprint.state.models import BlueprintState
from hld_generator.agents.blueprint.tools.product_profile_loader import ProductProfileLoader
from hld_generator.agents.blueprint.phases.document_type import DocumentTypePhase
from hld_generator.agents.blueprint.phases.section_by_section_planning import SectionBySectionPlanningPhase
from hld_generator.agents.blueprint.phases.execution_plan import ExecutionPlanPhase
from hld_generator.shared.llm_wrapper import OCILLMWrapper

logger = logging.getLogger(__name__)


class BlueprintNodes:
    """
    Container for all LangGraph node functions.

    Holds shared dependencies (ProductProfileLoader, LLM wrapper) and exposes
    async node functions compatible with LangGraph's StateGraph.
    """

    def __init__(
        self,
        profile_dir: Optional[Path] = None,
        llm_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize shared dependencies.

        Args:
            profile_dir: Path to the local product profile directory
            llm_config: Optional OCI GenAI config overrides
        """
        self.profile_loader = ProductProfileLoader(profile_dir=profile_dir)
        self.llm = OCILLMWrapper(**(llm_config or {}))

    # ------------------------------------------------------------------
    # Node 1: identify_product
    # ------------------------------------------------------------------

    async def identify_product(self, state: BlueprintState) -> Dict[str, Any]:
        """
        Phase 1: Identify product, extract template variables, and build global planning context.

        Reads:  knowledge_base, image_inventory
        Writes: identified_product, product_profile, template_variables, document_type,
                global_planning_context
        """
        logger.info("Node: identify_product")

        try:
            phase = DocumentTypePhase(profile_loader=self.profile_loader, llm=self.llm)

            result = await phase.execute(
                knowledge_base=state.get("knowledge_base", {}),
                image_inventory=state.get("image_inventory"),
                user_prompt=state.get("user_prompt", ""),
                structured_intent=state.get("structured_intent"),
                product_id=state.get("product_id"),  # CRITICAL: Pass product_id from job
            )

            return {
                "identified_product": result["identified_product"],
                "product_profile": result["product_profile"],
                "template_variables": result["template_variables"],
                "document_type": result["document_type"],
                "global_planning_context": result["global_planning_context"],
                "current_phase": "planning",
            }

        except Exception as e:
            logger.error(f"Phase 1 failed: {e}")
            return {
                "errors": state.get("errors", []) + [f"Phase 1 (identify_product): {str(e)}"],
                "current_phase": "error",
            }

    # ------------------------------------------------------------------
    # Node 2: plan_sections (NEW: section-by-section with integrated assets)
    # ------------------------------------------------------------------

    async def plan_sections(self, state: BlueprintState) -> Dict[str, Any]:
        """
        Phase 2: Section-by-Section Planning with Integrated Asset Assignment.

        NEW: Each section is planned in ONE comprehensive LLM call that includes
        asset assignment based on FULL Document Analyzer output.

        Reads:  knowledge_base, product_profile, template_variables,
                global_planning_context, image_inventory
        Writes: planned_sections (WITH assets already assigned)
        """
        logger.info("Node: plan_sections (section-by-section with integrated asset assignment)")

        try:
            phase = SectionBySectionPlanningPhase(llm=self.llm)

            result = await phase.execute(
                knowledge_base=state.get("knowledge_base", {}),
                product_profile=state.get("product_profile", {}),
                template_variables=state.get("template_variables", {}),
                global_planning_context=state.get("global_planning_context", {}),
                image_inventory=state.get("image_inventory"),
                structured_intent=state.get("structured_intent"),
            )

            return {
                "planned_sections": result["planned_sections"],
                "current_phase": "building",  # Skip old "assigning" phase, go directly to building
            }

        except Exception as e:
            logger.error(f"Phase 2 failed: {e}")
            return {
                "errors": state.get("errors", []) + [f"Phase 2 (plan_sections): {str(e)}"],
                "current_phase": "error",
            }

    # ------------------------------------------------------------------
    # Node 3: build_execution_plan (OLD: Node 4)
    # ------------------------------------------------------------------

    async def build_execution_plan(self, state: BlueprintState) -> Dict[str, Any]:
        """
        Phase 3 (NEW): Assemble BlueprintOutput from planned sections.

        NEW: Assets are already in planned_sections from Phase 2, so no merging needed.
        Just build generation batches and assemble final output.

        Reads:  planned_sections (with assets), knowledge_base, image_inventory,
                identified_product, document_type, template_variables
        Writes: blueprint_output, generation_batches
        """
        logger.info("Node: build_execution_plan")

        try:
            phase = ExecutionPlanPhase()

            result = await phase.execute(
                planned_sections=state.get("planned_sections", []),
                image_assignments=[],  # Empty - assets already in sections
                table_assignments=[],  # Empty - assets already in sections
                knowledge_base=state.get("knowledge_base", {}),
                product_profile=state.get("product_profile", {}),  # Section ordering comes from the profile
                image_inventory=state.get("image_inventory"),
                clarifications=state.get("clarifications", []),
                can_proceed=state.get("can_proceed", True),
                data_assessment_summary=state.get("data_assessment", {}),
                identified_product=state.get("identified_product", ""),
                document_type=state.get("document_type", "HLD"),
                template_variables=state.get("template_variables", {}),
            )

            blueprint = result["blueprint_output"]

            return {
                "blueprint_output": blueprint,
                "generation_batches": blueprint.get("generation_batches", []),
                "current_phase": "complete",
            }

        except Exception as e:
            logger.error(f"Phase 3 failed: {e}")
            return {
                "errors": state.get("errors", []) + [f"Phase 3 (build_execution_plan): {str(e)}"],
                "current_phase": "error",
            }
