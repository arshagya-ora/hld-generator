"""
Pydantic models for Content Generation Agent outputs.

These models structure the final generated content for each section.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class GenerationMetadata(BaseModel):
    """Metadata about how a section was generated."""

    strategy_used: str = Field(..., description="Strategy: template, rag, hybrid, generated")
    retrieved_chunks_used: int = Field(0, description="Count of RAG chunks used in prompt")
    project_data_fields_used: List[str] = Field(default_factory=list, description="Project context fields used")
    tokens_used: int = Field(0, description="Total tokens consumed")
    generation_time_seconds: float = Field(0.0, description="Time taken to generate")
    quality_self_assessment: float = Field(0.0, description="Self-assessed quality score (0-1)")
    model_name: str = Field("", description="LLM model used")
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class GeneratedSection(BaseModel):
    """
    A single generated HLD section.

    Contains the markdown content and structured metadata.
    """

    section_id: str = Field(..., description="Unique ID from Blueprint")
    section_number: str = Field(..., description="Section number, e.g. '5.1'")
    title: str = Field(..., description="Section title")
    
    markdown_content: str = Field(..., description="The actual generated content in Markdown")
    
    word_count: int = Field(0, description="Word count of markdown content")
    subsections_generated: int = Field(0, description="Number of subsections")
    
    images_inserted: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of images referenced in the text"
    )
    
    tables_inserted: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of tables referenced in the text"
    )
    
    requirements_addressed: List[str] = Field(
        default_factory=list,
        description="List of requirements explicitly covered"
    )
    
    cross_references: List[str] = Field(
        default_factory=list,
        description="List of cross-references to other sections"
    )
    
    generation_metadata: GenerationMetadata = Field(
        ...,
        description="Technical metadata about generation"
    )
