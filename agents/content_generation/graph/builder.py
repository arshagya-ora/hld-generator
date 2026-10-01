"""
LangGraph builder for Content Generation Agent.
"""

from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, END

from hld_generator.agents.content_generation.state.schema import ContentGenerationState
from hld_generator.agents.content_generation.graph.nodes import ContentGenerationNodes


def build_content_generation_graph(
    llm_client,
    config: Optional[Dict[str, Any]] = None,
) -> StateGraph:
    """
    Build the Content Generation Agent LangGraph.
    """
    nodes = ContentGenerationNodes(llm_client, config or {})
    
    workflow = StateGraph(ContentGenerationState)
    
    # Add nodes
    # NEW: Simplified batch-parallel architecture (no loop)
    workflow.add_node("initialize", nodes.initialize_node)
    workflow.add_node("generate_all_batches", nodes.generate_all_batches_node)
    workflow.add_node("finalize", nodes.finalize_node)

    # Define edges - Simple sequential flow
    workflow.set_entry_point("initialize")
    workflow.add_edge("initialize", "generate_all_batches")
    workflow.add_edge("generate_all_batches", "finalize")
    workflow.add_edge("finalize", END)
    
    return workflow.compile()
