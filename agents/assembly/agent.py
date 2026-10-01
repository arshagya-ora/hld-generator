"""
Assembly Agent - Main implementation.

Transforms validated individual sections into a complete, professionally
formatted HLD/SAED document ready for delivery.
"""

import logging
from typing import Dict, Any, Optional, Callable

from hld_generator.agents.assembly.graph.builder import build_assembly_graph
from hld_generator.agents.assembly.state.schema import AssemblyState
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


class AssemblyAgent:
    """
    Assembly Agent for HLD generation.

    Main responsibilities:
    1. Compile all generated sections
    2. Auto-number figures, tables, sections
    3. Generate TOC, List of Figures, List of Tables
    4. Generate Executive Summary (LLM)
    5. Generate Appendices
    6. Run quality checks
    7. Export to DOCX/PDF/HTML
    8. Package final document
    """

    def __init__(
        self,
        llm_client,  # OCI GenAI client for executive summary
        output_dir: str = "./outputs",
        output_formats: Optional[list] = None,
    ):
        """
        Initialize the Assembly Agent.

        Args:
            llm_client: OCI GenAI client for executive summary generation
            output_dir: Output directory for assembled documents
            output_formats: List of desired output formats (default: ["markdown", "docx"])
        """
        self.llm_client = llm_client
        self.output_dir = output_dir
        self.output_formats = output_formats or ["markdown", "docx"]

        # Build LangGraph pipeline
        self.graph = build_assembly_graph(llm_client=llm_client)

        logger.info("AssemblyAgent initialized")

    async def ainvoke(self, state: AssemblyState) -> AssemblyState:
        """
        Run the assembly pipeline (standalone).
        """
        logger.info("Assembly Agent starting...")
        result = await self.graph.ainvoke(state)
        logger.info("Assembly Agent complete")
        return result

