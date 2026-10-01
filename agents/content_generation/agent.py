"""
Content Generation Agent - Main implementation.

Orchestrates the generation of HLD sections using LangGraph pipeline.
"""

import logging
from typing import Dict, Any, Optional, Callable

from hld_generator.agents.content_generation.graph.builder import build_content_generation_graph
from hld_generator.agents.content_generation.state.schema import ContentGenerationState
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class ContentGenerationAgent:
    """
    Content Generation Agent for HLD generation.

    Main responsibilities:
    1. Read Blueprint plan
    2. Read Retrieval results (rag_results)
    3. Read Image Library
    4. Generate content for each section using appropriate strategy
    """

    def __init__(
        self,
        llm_client,  # OCI GenAI client
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the Content Generation Agent.

        Args:
            llm_client: OCI GenAI client for text generation
            config: Configuration dictionary
        """
        self.llm_client = llm_client
        self.config = config or {}

        # Build LangGraph pipeline
        self.graph = build_content_generation_graph(
            llm_client=llm_client,
            config=self.config,
        )

        logger.info("ContentGenerationAgent initialized")

    async def ainvoke(self, state: ContentGenerationState) -> ContentGenerationState:
        """
        Run the content generation pipeline (standalone).
        """
        logger.info("Content Generation Agent starting...")
        result = await self.graph.ainvoke(state)
        logger.info("Content Generation Agent complete")
        return result

