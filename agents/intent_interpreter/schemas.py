"""
Structured Intent Schemas.

Defines the output schema for the Intent Interpreter - the structured
instructions that drive the entire pipeline.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class ComponentScopeMode(str, Enum):
    """How to interpret the component list."""
    EXCLUSIVE = "EXCLUSIVE"    # Only include listed components
    INCLUSIVE = "INCLUSIVE"     # Include all, exclude listed
    EMPHASIS = "EMPHASIS"      # Include all, emphasise listed


class ComponentScope(BaseModel):
    """Which components to include/exclude in the HLD."""
    mode: ComponentScopeMode = Field(
        default=ComponentScopeMode.INCLUSIVE,
        description="How to interpret the include/exclude lists"
    )
    include: List[str] = Field(
        default_factory=list,
        description="Components to include (EXCLUSIVE mode) or emphasise (EMPHASIS mode)"
    )
    exclude: List[str] = Field(
        default_factory=list,
        description="Components to explicitly exclude"
    )
    preserve_structural: bool = Field(
        default=True,
        description="Keep mandatory sections (intro, deployment, appendices) regardless of component scope"
    )


class StyleDirective(BaseModel):
    """Style override for a specific section."""
    detail_level: Optional[str] = Field(
        default=None,
        description="high-level | detailed | comprehensive"
    )
    max_subsections: Optional[int] = Field(
        default=None,
        description="Maximum number of subsections to generate"
    )
    estimated_tokens: Optional[int] = Field(
        default=None,
        description="Approximate token budget for this section"
    )
    custom_instructions: Optional[str] = Field(
        default=None,
        description="Free-form style instructions for this section"
    )


class DataSourceMapping(BaseModel):
    """Maps a data type to a specific source document."""
    source: str = Field(
        ...,
        description="Filename or pattern to match"
    )
    sheet: Optional[str] = Field(
        default=None,
        description="Specific sheet/table within the source"
    )
    priority: str = Field(
        default="MEDIUM",
        description="HIGH | MEDIUM | LOW"
    )


class CustomSection(BaseModel):
    """A section not in the profile that the user wants to add."""
    section_id: str = Field(
        ...,
        description="Unique identifier for the section"
    )
    title: str = Field(
        ...,
        description="Section title"
    )
    insert_after: Optional[str] = Field(
        default=None,
        description="Section ID to insert after"
    )
    generation_strategy: str = Field(
        default="hybrid",
        description="template | rag | hybrid | generated"
    )


class GlobalConstraints(BaseModel):
    """Global constraints on the HLD generation."""
    max_total_tokens: Optional[int] = Field(
        default=None,
        description="Maximum total token budget for the entire HLD"
    )
    preferred_diagram_style: Optional[str] = Field(
        default=None,
        description="architecture_focused | detailed | minimal"
    )


class StructuredIntent(BaseModel):
    """
    The complete structured intent output from the Intent Interpreter.

    This is THE primary driver for the entire pipeline. Every downstream
    agent consumes this to make decisions.
    """
    intent_type: str = Field(
        default="FULL_GENERATION",
        description="FULL_GENERATION | SELECTIVE_GENERATION | UPDATE | REGENERATE"
    )

    component_scope: ComponentScope = Field(
        default_factory=ComponentScope,
        description="Which components to include/exclude"
    )

    style_directives: Dict[str, StyleDirective] = Field(
        default_factory=dict,
        description="Per-section style overrides keyed by section_id"
    )

    data_source_mappings: Dict[str, DataSourceMapping] = Field(
        default_factory=dict,
        description="Maps data types to specific source documents"
    )

    custom_sections: List[CustomSection] = Field(
        default_factory=list,
        description="Sections to add that are not in the profile"
    )

    global_constraints: GlobalConstraints = Field(
        default_factory=GlobalConstraints,
        description="Global constraints on generation"
    )

    template_variable_overrides: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Override global template variables extracted from user_prompt. "
            "Supported keys: customer_name, project_name, site_names, deployment_model, "
            "product_version, platform_version, etc. "
            "Example: {'customer_name': 'Saudi Telecom Company', 'project_name': 'Sessions Upgrade 2026'}"
        )
    )

    raw_user_prompt: str = Field(
        default="",
        description="Original user prompt for reference"
    )
