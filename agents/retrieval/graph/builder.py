"""
LangGraph builder for Retrieval Agent pipeline.

Constructs a 3-node sequential pipeline:
1. Initialize - Validate inputs and prepare state
2. Execute Queries - Query RAG-Anything, get LLM-synthesized answers, store them
3. Finalize - Compute metrics

RAG-Anything handles ranking/deduplication internally. The retrieval agent just
calls the library and stores the clean plain-text answers.
"""

from langgraph.graph import StateGraph, END

from hld_generator.agents.retrieval.state.schema import RetrievalState
from hld_generator.agents.retrieval.graph.nodes import (
    initialize_node,
    execute_queries_node,
    finalize_node,
)


def build_retrieval_graph(
    rag_anything_client,  # RAGAnything instance (required)
) -> StateGraph:
    """
    Build LangGraph for retrieval pipeline.

    Simple 3-node pipeline that delegates all complexity to RAG-Anything:
    1. Initialize - validate inputs
    2. Execute Queries - call RAG-Anything library, store clean answers
    3. Finalize - compute metrics

    Args:
        rag_anything_client: RAGAnything instance for querying indexed datasets

    Returns:
        Compiled StateGraph ready for execution
    """

    graph = StateGraph(RetrievalState)

    # ============================
    # Define Nodes
    # ============================

    graph.add_node("initialize", initialize_node)

    async def execute_queries_with_client(state: RetrievalState) -> RetrievalState:
        return await execute_queries_node(state, rag_anything_client)

    graph.add_node("execute_queries", execute_queries_with_client)
    graph.add_node("finalize", finalize_node)

    # ============================
    # Define Edges (Sequential Pipeline)
    # ============================

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "execute_queries")
    graph.add_edge("execute_queries", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
