"""
Retrieval Agent - Executes RAG queries to gather product documentation.

Main responsibilities:
1. Read RAG query specifications from Blueprint output
2. Execute queries against RAG-Anything (product documentation store)
3. Rank and filter results based on relevance
4. Deduplicate content across queries
5. Store retrieved content keyed by section ID
"""

from typing import Dict, Any, Callable, Optional
import logging

from hld_generator.agents.retrieval.state.schema import RetrievalState
from hld_generator.agents.retrieval.graph.builder import build_retrieval_graph
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class RetrievalAgent:
    """
    Agent responsible for executing RAG queries specified in Blueprint.

    Architecture:
    - RAG-Anything: Query product documentation (primary source)

    Pipeline (LangGraph):
    1. Initialize - Validate inputs, prepare state
    2. Execute Queries - Query RAG-Anything, get LLM-synthesized answers, store them
    3. Finalize - Compute metrics
    """

    def __init__(
        self,
        rag_anything_client,  # RAGAnything instance (required)
    ):
        """
        Initialize Retrieval Agent.

        Args:
            rag_anything_client: RAGAnything instance for product documentation queries
        """
        self.rag_anything_client = rag_anything_client

        # Build LangGraph pipeline
        self.graph = build_retrieval_graph(
            rag_anything_client=rag_anything_client,
        )

        logger.info("Retrieval Agent initialized successfully")

    async def ainvoke(self, state: RetrievalState) -> RetrievalState:
        """
        Main async invocation for retrieval pipeline.

        Args:
            state: RetrievalState with blueprint and document_knowledge_base

        Returns:
            Updated RetrievalState with rag_results, retrieval_metrics, retrieval_complete
        """
        logger.info("Retrieval Agent starting...")
        result = await self.graph.ainvoke(state)
        logger.info("Retrieval Agent complete")
        return result

