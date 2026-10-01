"""
Retrieval Agent for ArchDraft.

Executes RAG queries specified by Blueprint Agent to gather product documentation
from RAG-Anything and store results for Content Generation Agent.
"""

from hld_generator.agents.retrieval.agent import RetrievalAgent

__all__ = ["RetrievalAgent"]
