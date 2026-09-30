"""
Pydantic models for Retrieval Agent state and outputs.

Defines data structures for:
- RetrievedChunk: Individual content chunk from RAG-Anything
- DiagramReference: Metadata for retrieved diagrams
- TableReference: Metadata for retrieved tables
- SectionRetrievalResult: Aggregated results per section
- RetrievalMetrics: Overall retrieval statistics
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class RetrievedChunk(BaseModel):
    """Single retrieved content chunk from RAG-Anything product documentation"""

    chunk_id: str = Field(..., description="Unique identifier for this chunk")
    content: str = Field(..., description="Retrieved text content")
    source: str = Field(..., description="Source identifier (e.g., 'rag_anything:5G_SBA_Architecture')")
    relevance_score: float = Field(..., description="Relevance score (0.0-1.0)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (filters, query, search_mode, etc.)"
    )
    query_index: int = Field(..., description="Which RAG query retrieved this chunk (0-indexed)")


class DiagramReference(BaseModel):
    """Metadata for a retrieved diagram"""

    image_id: str = Field(..., description="Unique identifier for the diagram")
    caption: str = Field(..., description="Diagram caption/title")
    source: str = Field(..., description="Source document or system")
    relevance_score: float = Field(..., description="Relevance score (0.0-1.0)")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (diagram type, page number, etc.)"
    )


class TableReference(BaseModel):
    """Metadata for a retrieved table"""

    table_id: str = Field(..., description="Unique identifier for the table")
    caption: str = Field(..., description="Table caption/title")
    data: Dict[str, Any] = Field(..., description="Structured table data (headers, rows)")
    source: str = Field(..., description="Source document or system")
    relevance_score: float = Field(..., description="Relevance score (0.0-1.0)")


class SectionRetrievalResult(BaseModel):
    """Aggregated retrieval results for one HLD section"""

    section_id: str = Field(..., description="Section identifier (e.g., 'sec_004')")
    text_chunks: List[RetrievedChunk] = Field(
        default_factory=list,
        description="Retrieved text content chunks"
    )
    diagrams: List[DiagramReference] = Field(
        default_factory=list,
        description="Retrieved diagram references"
    )
    tables: List[TableReference] = Field(
        default_factory=list,
        description="Retrieved table references"
    )
    total_tokens: int = Field(..., description="Estimated total tokens for all chunks")
    retrieval_timestamp: str = Field(..., description="ISO timestamp of retrieval")
    queries_executed: int = Field(..., description="Number of RAG queries executed for this section")


class RetrievalMetrics(BaseModel):
    """Overall retrieval statistics across all sections"""

    total_sections: int = Field(..., description="Number of sections with retrieval")
    total_queries_executed: int = Field(..., description="Total RAG queries executed")
    total_chunks_retrieved: int = Field(..., description="Total content chunks retrieved")
    total_tokens: int = Field(..., description="Total estimated tokens across all sections")
    avg_retrieval_time_per_query: float = Field(..., description="Average query execution time (seconds)")
    timestamp: str = Field(..., description="ISO timestamp when metrics were computed")
