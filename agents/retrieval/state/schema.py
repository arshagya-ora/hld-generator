"""
State schema for Retrieval Agent (TypedDict for LangGraph compatibility).

Defines the internal state structure used during retrieval pipeline execution.
"""

from typing import TypedDict, Optional, Dict, List, Any


class RetrievalState(TypedDict, total=False):
    """
    State for Retrieval Agent internal processing.

    This state is passed through the LangGraph pipeline nodes and accumulates
    retrieval results, metrics, and error information.
    """

    # ============================
    # Inputs (from master state)
    # ============================
    blueprint: Optional[Dict[str, Any]]  # BlueprintOutput as dict
    """Blueprint containing section plans and RAG queries"""

    product_id: Optional[str]
    """Canonical product ID for RAG-Anything dataset selection (e.g. "5G_SBA", "DSR").
    Set from HLDGeneratorState.selected_product_id by the Retrieval Agent node."""

    document_knowledge_base: Optional[Dict[str, Any]]
    """DocumentKnowledgeBase from Document Analyzer (project context)"""

    # ============================
    # Processing State
    # ============================
    current_section_id: Optional[str]
    """Currently processing section ID (used during query execution)"""

    query_execution_log: List[Dict[str, Any]]
    """Log of query executions (for debugging/audit trail)"""

    # ============================
    # Outputs
    # ============================
    rag_results: Dict[str, Dict[str, Any]]
    """
    Retrieved content keyed by section_id.
    Each value is a SectionRetrievalResult dict.
    Example: {"sec_004": SectionRetrievalResult.dict(), ...}
    """

    retrieval_metrics: Optional[Dict[str, Any]]
    """Overall retrieval statistics (RetrievalMetrics as dict)"""

    retrieval_complete: bool
    """Flag indicating successful completion of retrieval"""

    # ============================
    # Error Handling
    # ============================
    errors: List[str]
    """List of error messages encountered during retrieval"""
