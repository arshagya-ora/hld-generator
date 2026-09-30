"""
State schema for Content Generation Agent (TypedDict for LangGraph compatibility).

Defines the internal state structure used during generation pipeline execution.
"""

from typing import TypedDict, Optional, Dict, List, Any


class ContentGenerationState(TypedDict, total=False):
    """
    State for Content Generation Agent internal processing.

    This state is passed through the LangGraph pipeline nodes.
    It accumulates generated content and tracks progress.
    """

    # ============================
    # Inputs (Ready to use)
    # ============================
    blueprint: Optional[Dict[str, Any]]
    """BlueprintOutput as dict (contains section plans)"""

    rag_results: Optional[Dict[str, Any]]
    """
    Pre-retrieved content from Retrieval Agent.
    Keyed by section_id.
    """

    final_image_library: Optional[Dict[str, Any]]
    """
    Generated images from Image Generation Agent.
    Keyed by image_id or section context.
    """

    project_context: Optional[Dict[str, Any]]
    """DocumentKnowledgeBase from Document Analyzer (project metadata)"""

    parsed_content: str
    """Raw parsed document text for grounding LLM calls (first 12K chars used)"""

    # ============================
    # Processing State
    # ============================
    generation_queue: List[Dict[str, Any]]
    """
    Ordered list of section plans to generate.
    Sorted by dependency and generation order.
    """

    current_section_index: int
    """Index of currently processing section in queue"""

    current_section_id: Optional[str]
    """Currently processing section ID"""

    current_strategy: Optional[str]
    """Strategy selected for current section (template, rag, hybrid, generated)"""

    # ============================
    # Outputs
    # ============================
    generated_sections: Dict[str, Any]
    """
    Generated content keyed by section_id.
    Each value is a GeneratedSection.dict().
    """

    generation_complete: bool
    """Flag indicating successful completion of all sections"""

    # ============================
    # Error Handling & Logs
    # ============================
    errors: List[str]
    """List of error messages encountered"""

    warnings: List[str]
    """List of warning messages"""
