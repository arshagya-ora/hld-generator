"""
Blueprint Agent — Main implementation.

Orchestrates the 4-phase LangGraph pipeline that transforms
DocumentKnowledgeBase + ImageInventory into a complete generation plan
(BlueprintOutput).

Phases:
  1. identify_product  → Match document to product profile
  2. plan_sections     → LLM-driven section planning
  3. assess_data       → Data completeness + gap detection
  4. build_execution_plan → Dependency resolution + batch assembly

Usage:
    agent = BlueprintAgent()
    blueprint = await agent.run(knowledge_base_dict, image_inventory_dict, dataset_name)

Orchestrator integration:
    blueprint = await agent.run(knowledge_base, image_inventory, dataset_name)
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from hld_generator.agents.blueprint.graph.builder import build_blueprint_graph
from hld_generator.agents.blueprint.state.models import BlueprintState
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class BlueprintAgent:
    """
    Blueprint Agent for HLD generation planning.

    Takes the Document Analyzer's output (DocumentKnowledgeBase + ImageInventory)
    and produces a complete, dependency-ordered generation plan.

    Uses:
      - Local product profile JSON files (loaded dynamically)
      - Direct OCI GenAI LLM calls for reasoning (not Cognee)
      - LangGraph for pipeline orchestration
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        profile_dir: Optional[Path] = None,
    ):
        """
        Initialize the Blueprint Agent.

        Args:
            config: Optional configuration dict with LLM settings:
                - compartment_id, model_id, endpoint (OCI GenAI)
            profile_dir: Optional path to the product profile directory.
                     Defaults to PRODUCT_PROFILE_DIR or product_profiles/.
        """
        self.config = config or {}
        self.profile_dir = profile_dir

        # LLM configuration (passed through to OCILLMWrapper)
        self.llm_config = {}
        for key in ("compartment_id", "model_id", "endpoint", "config_profile", "config_file"):
            if key in self.config:
                self.llm_config[key] = self.config[key]

        # Build the LangGraph pipeline
        self.graph = build_blueprint_graph(
            profile_dir=self.profile_dir,
            llm_config=self.llm_config if self.llm_config else None,
        )

        logger.info("BlueprintAgent initialized")

    async def run(
        self,
        knowledge_base: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]] = None,
        structured_intent: Optional[Dict[str, Any]] = None,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the Blueprint Agent pipeline (standalone execution).

        Args:
            knowledge_base: DocumentKnowledgeBase as dict (from Document Analyzer)
            image_inventory: ImageInventory as dict (optional)
            structured_intent: StructuredIntent dict from Intent Interpreter (optional)
            product_id: Product ID from job (e.g., "Sessions", "DSR", "5G_SBA")
                       If provided, Blueprint uses this instead of auto-detecting from keywords.
                       CRITICAL for product ID consistency across all agents.

        Returns:
            BlueprintOutput as dict

        Raises:
            Exception: If pipeline fails critically
        """
        logger.info("Blueprint Agent starting...")
        if product_id:
            logger.info(f"  Using provided product_id: {product_id}")

        # Build initial state
        initial_state: BlueprintState = {
            "knowledge_base": knowledge_base,
            "image_inventory": image_inventory,
            "structured_intent": structured_intent,
            "product_id": product_id,  # CRITICAL: Pass product_id from job
            "current_phase": "identifying",
            "errors": [],
            "template_variables": {},
            "document_type": "HLD",
            "clarifications": [],
            "can_proceed": True,
        }

        # Run the LangGraph pipeline
        final_state = await self.graph.ainvoke(initial_state)

        # Check for errors
        errors = final_state.get("errors", [])
        if errors:
            logger.warning(f"Blueprint Agent completed with errors: {errors}")

        blueprint = final_state.get("blueprint_output")
        if not blueprint or not isinstance(blueprint, dict):
            raise RuntimeError(
                f"Blueprint Agent produced no output. Errors: {errors}"
            )

        # Validate required fields exist
        required_keys = {"sections", "blueprint_id", "product"}
        missing = required_keys - set(blueprint.keys())
        if missing:
            raise RuntimeError(
                f"Blueprint output missing required fields: {missing}. Errors: {errors}"
            )
        if not blueprint.get("sections"):
            raise RuntimeError(
                f"Blueprint output has no sections. Errors: {errors}"
            )

        logger.info(
            f"Blueprint Agent complete: "
            f"{len(blueprint.get('sections', []))} sections, "
            f"{len(blueprint.get('generation_batches', []))} batches, "
            f"can_proceed={blueprint.get('can_proceed', True)}"
        )

        return blueprint

