"""
State schema for Assembly Agent (TypedDict for LangGraph compatibility).

Defines the internal state structure used during document assembly pipeline execution.
"""

from typing import TypedDict, Optional, Dict, List, Any


class AssemblyState(TypedDict, total=False):
    """
    State for Assembly Agent internal processing.

    This state is passed through the LangGraph pipeline nodes.
    It accumulates assembled content and tracks progress.
    """

    # ============================
    # Inputs (from master state)
    # ============================
    blueprint: Optional[Dict[str, Any]]
    """BlueprintOutput as dict (contains section metadata, template variables)"""

    generated_sections: Dict[str, Dict[str, Any]]
    """Generated sections from Content Generation Agent (section_id → GeneratedSection dict)"""

    final_image_library: Optional[Dict[str, Any]]
    """Generated images from Image Generation Agent"""

    project_context: Optional[Dict[str, Any]]
    """DocumentKnowledgeBase from Document Analyzer (project metadata)"""

    llm_client: Optional[Any]
    """LLM client for executive summary generation"""

    output_dir: str
    """Output directory for assembled documents"""

    output_formats: List[str]
    """Desired output formats: ['docx', 'pdf', 'html']"""

    # ============================
    # Processing State
    # ============================
    assembly_start_time: Optional[float]
    """Unix timestamp when assembly started (for timing metrics)"""

    compiled_content: Optional[str]
    """Compiled markdown content (all sections merged)"""

    figure_references: List[Dict[str, Any]]
    """List of all figures with assigned numbers (FigureReference dicts)"""

    table_references: List[Dict[str, Any]]
    """List of all tables with assigned numbers (TableReference dicts)"""

    section_references: List[Dict[str, Any]]
    """List of all sections with numbers (SectionReference dicts)"""

    toc_content: Optional[str]
    """Generated table of contents markdown"""

    list_of_figures: Optional[str]
    """Generated list of figures markdown"""

    list_of_tables: Optional[str]
    """Generated list of tables markdown"""

    executive_summary: Optional[str]
    """LLM-generated executive summary markdown"""

    appendices_content: Optional[str]
    """Generated appendices markdown"""

    # ============================
    # Export State
    # ============================
    exported_files: Dict[str, str]
    """Paths to exported files keyed by format (docx, pdf, html)"""

    # ============================
    # Quality Checks
    # ============================
    quality_checks: List[Dict[str, Any]]
    """Results of quality validation checks (QualityCheckResult dicts)"""

    # ============================
    # Outputs
    # ============================
    assembled_document: Optional[Dict[str, Any]]
    """Final AssembledDocument dict with all metadata"""

    assembly_complete: bool
    """Flag indicating successful completion"""

    # ============================
    # Error Handling & Logs
    # ============================
    errors: List[str]
    """List of error messages encountered"""

    warnings: List[str]
    """List of warning messages"""
