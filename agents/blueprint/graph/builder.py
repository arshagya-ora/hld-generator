"""
LangGraph pipeline builder for the Blueprint Agent.

NEW ARCHITECTURE (3 phases):
  Phase 1: identify_product + build global planning context
  Phase 2: section-by-section planning with integrated asset assignment
  Phase 3: build_execution_plan

OLD ARCHITECTURE (deprecated):
  identify_product → plan_sections → assign_assets → build_execution_plan

Includes error-checking conditional edges: if a phase sets current_phase
to "error", downstream phases are skipped and the pipeline goes directly
to build_execution_plan to produce an error-state output.
"""

import logging
from typing import Dict, Any, Optional

from langgraph.graph import StateGraph, END

from hld_generator.agents.blueprint.state.models import BlueprintState
from hld_generator.agents.blueprint.graph.nodes import BlueprintNodes

logger = logging.getLogger(__name__)


def _route_after_identify(state: BlueprintState) -> str:
    """Skip to execution plan assembly if Phase 1 failed."""
    if state.get("current_phase") == "error":
        logger.warning("Phase 1 failed — skipping to build_execution_plan")
        return "build_execution_plan"
    return "plan_sections"


def build_blueprint_graph(
    profile_dir=None,
    llm_config: Optional[Dict[str, Any]] = None,
) -> StateGraph:
    """
    Build the Blueprint Agent's LangGraph pipeline.

    NEW ARCHITECTURE (3 phases):
      Phase 1: identify_product + build global planning context
      Phase 2: section-by-section planning with integrated asset assignment
      Phase 3: build_execution_plan

    Args:
        profile_dir: Optional local product profile directory
        llm_config: Optional dict with OCI GenAI config overrides
                    (compartment_id, model_id, endpoint, etc.)

    Returns:
        Compiled StateGraph
    """
    # Create nodes with shared dependencies
    nodes = BlueprintNodes(profile_dir=profile_dir, llm_config=llm_config)

    # Define the graph
    graph = StateGraph(BlueprintState)

    # Add nodes (3 phases only)
    graph.add_node("identify_product", nodes.identify_product)
    graph.add_node("plan_sections", nodes.plan_sections)
    graph.add_node("build_execution_plan", nodes.build_execution_plan)

    # Set entry point
    graph.set_entry_point("identify_product")

    # Conditional edge: skip plan_sections on Phase 1 error
    graph.add_conditional_edges(
        "identify_product",
        _route_after_identify,
        {"plan_sections": "plan_sections", "build_execution_plan": "build_execution_plan"},
    )
    # plan_sections always flows to build_execution_plan (assign_assets removed)
    graph.add_edge("plan_sections", "build_execution_plan")
    graph.add_edge("build_execution_plan", END)

    logger.info(
        "Blueprint graph built (NEW 3-phase architecture): "
        "identify_product → plan_sections → build_execution_plan"
    )

    return graph.compile()
