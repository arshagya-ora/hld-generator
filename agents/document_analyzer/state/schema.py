"""
Internal state schema for Document Analyzer Agent.

This state is used within the agent's internal LangGraph and is separate
from the shared HLDGeneratorState used for cross-agent communication.
"""

from typing import TypedDict, List, Dict, Any, Optional


class AnalyzerState(TypedDict, total=False):
    """
    Internal state for the Document Analyzer Agent's pipeline.

    This state flows through the agent's nodes: parse -> extract_images -> semantic_extract -> merge_and_validate
    """

    # ===== Input =====
    document_path: str  # Path to primary document file
    document_paths: Optional[List[str]]  # Paths to ALL documents (multi-doc support)
    document_type: Optional[str]  # DOCX, PDF, or auto-detected
    dataset_name: str  # Dataset identifier (no longer used by Cognee)
    selected_product_name: str  # Product to focus analysis on

    # ===== Processing State =====
    parsed_content: Optional[str]  # Extracted text from Docling
    parsed_tables: Optional[List[Dict[str, Any]]]  # Rich table objects with section context
    image_dir: Optional[str]  # Persistent directory where parsed images were saved

    # ===== Semantic Chunking =====
    semantic_chunks: Optional[List[Any]]  # Chunks with metadata (from SemanticChunker)
    chunk_extractions: Optional[List[Dict[str, Any]]]  # Per-chunk KB results from LLM

    # ===== Image Analysis =====
    extracted_images: List[Any]  # Images extracted from document
    image_inventory: Optional[Dict[str, Any]]  # Structured image inventory
    converter_result: Optional[Any]  # Raw Docling converter result for image extraction

    # ===== Final Output =====
    knowledge_base: Optional[Dict[str, Any]]  # Final DocumentKnowledgeBase as dict
    completeness_score: float  # 0.0-1.0 score
    missing_items: List[str]  # Identified gaps in extraction

    # ===== Metadata & Control =====
    current_phase: str  # parse|extract_images|semantic_extract|merge_and_validate
    extraction_metadata: Dict[str, Any]  # Stats, timing, chunk counts
    errors: List[str]  # Error messages
    warnings: List[str]  # Non-fatal warnings
