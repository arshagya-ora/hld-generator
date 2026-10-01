"""
Base abstract class for all generation strategies.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from hld_generator.agents.content_generation.state.models import GeneratedSection


class BaseGenerationStrategy(ABC):
    """
    Abstract base class for content generation strategies.
    
    Subclasses must implement the generate() method to produce
    a GeneratedSection from the provided inputs.
    """
    
    def __init__(self, llm_client, config: Optional[Dict[str, Any]] = None):
        self.llm_client = llm_client
        self.config = config or {}

    @abstractmethod
    async def generate(
        self,
        section_plan: Dict[str, Any],
        rag_content: Dict[str, Any],
        image_library: Dict[str, Any],
        project_context: Dict[str, Any],
        template_variables: Dict[str, str],
        parsed_content: str = "",
    ) -> GeneratedSection:
        """
        Generate content for a single section.

        Args:
            section_plan: The plan for this specific section (from Blueprint)
            rag_content: Retrieved content relevant to this section
            image_library: Images available for insertion
            project_context: Global project metadata
            template_variables: Key-value pairs for template substitution
            parsed_content: Full raw parsed document text for grounding (first 12K chars used)

        Returns:
            GeneratedSection object with content and metadata
        """
        pass
