"""
Pydantic models for the Blueprint Agent output.

These models define the structured generation plan produced by the
Blueprint Agent. They are consumed by downstream agents (Retrieval,
Content Generation, Assembly) to execute the plan.
"""

from pydantic import BaseModel, Field, model_validator, field_validator
from typing import List, Dict, Any, Optional, Literal, Union
from datetime import datetime


# ─────────────────────────────────────────────
# Sub-models: RAG, Diagrams, Tables
# ─────────────────────────────────────────────

class RAGQueryPlan(BaseModel):
    """A planned RAG retrieval query for a section."""

    query: str = Field(..., description="Natural language query for Cognee/RAG")
    target_content: str = Field("", description="What we expect to retrieve")
    top_k: int = Field(5, description="Number of results to retrieve")
    filters: Dict[str, str] = Field(
        default_factory=dict,
        description="Filters: product, nf_type, section_category, etc."
    )


class DiagramAssignment(BaseModel):
    """Maps a diagram to a section, with sourcing strategy."""

    image_id: Optional[str] = Field(
        None,
        description="Image ID from ImageInventory (if reusing an extracted image)"
    )
    figure_reference: str = Field(
        ...,
        description="Figure reference in the document, e.g. 'Figure 4-1'"
    )
    title: str = Field(..., description="Diagram title / caption")
    sourcing_strategy: Literal["reuse", "regenerate", "generate_new"] = Field(
        "generate_new",
        description="How to source this diagram"
    )
    description: str = Field(
        "",
        description="What this diagram should show"
    )
    diagram_type: str = Field(
        "architecture_diagram",
        description="Type: network_topology, component_diagram, deployment_diagram, "
        "flow_chart, architecture_diagram, sequence_diagram, rack_layout, other"
    )


class TableAssignment(BaseModel):
    """Maps a table to a section, with data sourcing plan."""

    table_id: str = Field(..., description="Unique table identifier, e.g. 'HARDWARE_SPECS'")
    placeholder_tag: str = Field(
        ...,
        description="Tag for insertion: '[INSERT_TABLE: HARDWARE_SPECS]'"
    )
    title: str = Field(..., description="Table title / caption")
    data_source: Literal[
        "document_analyzer", "rag", "manual", "template"
    ] = Field("template", description="Where data comes from")
    columns: List[str] = Field(
        default_factory=list,
        description="Expected column headers"
    )
    extraction_notes: str = Field(
        "",
        description="Instructions for extracting/populating table data"
    )

    @field_validator("data_source", mode="before")
    @classmethod
    def normalize_data_source(cls, value):
        """
        Normalize legacy/custom profile data source labels to the strict enum.
        """
        if value is None:
            return "template"

        raw = str(value).strip().lower()
        if raw in {"document_analyzer", "rag", "manual", "template"}:
            return raw

        if (
            raw.startswith("rag")
            or "retrieval" in raw
            or "knowledge" in raw
        ):
            return "rag"

        if (
            "document" in raw
            or "metadata" in raw
            or "ciq" in raw
            or raw.startswith("extraction")
        ):
            return "document_analyzer"

        if (
            "manual" in raw
            or "user_input" in raw
            or "customer_input" in raw
            or "input" in raw
        ):
            return "manual"

        if (
            "template" in raw
            or "static" in raw
            or "logic" in raw
            or "calculation" in raw
        ):
            return "template"

        return "template"


# ─────────────────────────────────────────────
# Section-level plan
# ─────────────────────────────────────────────

class SubsectionPlan(BaseModel):
    """Plan for a subsection within a section."""

    subsection_number: str = Field(..., description="e.g. '3.2.1'")
    title: str = Field(..., description="Subsection title")
    generation_notes: str = Field("", description="Special instructions for this subsection")


class MatchedImage(BaseModel):
    """An image pre-assigned to this section by the asset assignment phase."""

    image_id: str = Field(..., description="Image ID from ImageInventory")
    storage_path: str = Field("", description="Filesystem path to the image file")
    figure_title: str = Field("", description="Caption / title for this figure")
    assign_reason: str = Field("", description="Why this image was matched to this section")
    confidence: Literal["high", "medium", "low"] = Field("medium", description="Match confidence")
    vision_type: str = Field("", description="Image type: network_topology, sequence_diagram, etc.")


class MatchedTable(BaseModel):
    """A document-extracted table pre-assigned to this section."""

    extracted_table_id: str = Field(..., description="Table ID from document_analyzer (e.g. 'Table_5')")
    use_as: str = Field("", description="Semantic role in this section (e.g. 'VM_SIZING_274KMPS')")
    markdown: str = Field("", description="Actual extracted markdown table content")
    description: str = Field("", description="What this table contains")
    assign_reason: str = Field("", description="Why this table was matched to this section")
    confidence: Literal["high", "medium", "low"] = Field("medium")


class SectionPlan(BaseModel):
    """
    Complete generation plan for a single HLD section.

    Self-contained render specification — every field is a typed value,
    string, or list of strings. Downstream agents process this without
    any further LLM interpretation.
    """

    # ── Identity ──
    section_id: str = Field(..., description="Unique ID, e.g. 'sec_capacity_sizing'")
    section_number: str = Field(..., description="Section number, e.g. '3' or '5.3'")
    title: str = Field(..., description="Section title")

    # ── Dynamic inclusion decision (set by Phase 2 LLM) ──
    include: bool = Field(True, description="Whether to include this section in the HLD")
    include_reason: str = Field(
        "", description="Why included or excluded — especially important for dynamically added sections"
    )

    # ── Structure ──
    subsections: List[SubsectionPlan] = Field(default_factory=list)
    dependencies: List[str] = Field(
        default_factory=list,
        description="section_ids that must be generated before this one"
    )

    # ── Generation config ──
    generation_strategy: Literal[
        "template", "rag_heavy", "hybrid", "generated", "reuse"
    ] = Field("hybrid", description="How this section is generated")
    template_ratio: int = Field(0, ge=0, le=100)
    rag_ratio: int = Field(0, ge=0, le=100)
    estimated_tokens: int = Field(1000, ge=0)

    @field_validator("generation_strategy", mode="before")
    @classmethod
    def normalize_generation_strategy(cls, value):
        """
        Normalize LLM-generated strategy labels to strict enum values.
        LLMs sometimes return descriptive variants like 'document_analyzer_heavy' or 'template_based'.
        """
        if value is None:
            return "hybrid"

        raw = str(value).strip().lower()

        # Direct matches
        if raw in {"template", "rag_heavy", "hybrid", "generated", "reuse"}:
            return raw

        # Normalize template variants
        if "template" in raw:
            return "template"

        # Normalize document_analyzer_heavy → rag_heavy (relies on extracted data)
        if "document_analyzer" in raw or "analyzer" in raw:
            return "rag_heavy"

        # Normalize RAG variants
        if "rag" in raw or "retrieval" in raw:
            return "rag_heavy"

        # Normalize generated variants
        if "generated" in raw or "llm" in raw:
            return "generated"

        # Normalize reuse variants
        if "reuse" in raw or "copy" in raw:
            return "reuse"

        # Default fallback
        return "hybrid"

    # ── What to write: explicit instructions (set by Phase 2 LLM) ──
    generation_steps: List[str] = Field(
        default_factory=list,
        description="Ordered, specific, actionable write instructions referencing actual project data"
    )
    content_facts: List[str] = Field(
        default_factory=list,
        description="Exact strings from project data to inject verbatim into the section"
    )
    quality_checks: List[str] = Field(
        default_factory=list,
        description="Acceptance criteria the generated content must satisfy before it is accepted"
    )
    hallucination_guards: List[str] = Field(
        default_factory=list,
        description="Fields that must NEVER be hallucinated — mark as TBD if unknown"
    )
    section_project_facts: List[str] = Field(
        default_factory=list,
        description="Key project-specific facts relevant to this section from special_notes"
    )
    requirements_to_address: List[str] = Field(
        default_factory=list,
        description="Flattened list of write requirements injected into content generation prompts. "
                    "Populated from generation_steps by _validate_and_enrich() if not set by LLM."
    )

    # ── Style anchor (from profile) ──
    exemplar_snippet: Optional[str] = Field(
        None,
        description="Short real-HLD excerpt for voice and depth reference"
    )
    content_patterns: Dict[str, Any] = Field(
        default_factory=dict,
        description="profile-defined content templates (reference lists, glossary entries, etc.)"
    )

    # ── Pre-matched assets (set by Phase 3 LLM) ──
    matched_images: List[MatchedImage] = Field(
        default_factory=list,
        description="Images assigned to this section with storage paths ready for embedding"
    )
    matched_tables: List[MatchedTable] = Field(
        default_factory=list,
        description="Extracted tables assigned to this section with real markdown content"
    )

    # ── RAG queries ──
    rag_queries: List[RAGQueryPlan] = Field(default_factory=list)

    # ── Data status ──
    data_completeness: float = Field(1.0, ge=0.0, le=1.0)
    missing_data_critical: List[str] = Field(default_factory=list)
    missing_data_important: List[str] = Field(default_factory=list)
    missing_data_optional: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    # ── Execution control ──
    generate_order: int = Field(0)
    ready_to_generate: bool = Field(True)

    # ── Legacy fields kept for backward compat ──
    data_sources: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    generation_notes: Optional[str] = Field(None)
    conditional: bool = Field(False)
    condition_met: Optional[Union[str, bool]] = Field(None)
    batch_strategy: Optional[Dict[str, Any]] = Field(None)
    reusable_content: Optional[Dict[str, List[str]]] = Field(None)
    diagrams: List[DiagramAssignment] = Field(default_factory=list)
    tables: List[TableAssignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ratios(self):
        """Ensure template_ratio + rag_ratio does not exceed 100%."""
        if self.template_ratio + self.rag_ratio > 100:
            self.rag_ratio = 100 - self.template_ratio
        return self


# ─────────────────────────────────────────────
# Generation batching
# ─────────────────────────────────────────────

class GenerationBatch(BaseModel):
    """
    A batch of sections that can be generated together.

    Respects dependency ordering — a batch only runs after
    all batches it depends on are complete.
    """

    batch_number: int = Field(..., description="Execution order (1 = first)")
    section_ids: List[str] = Field(
        ...,
        description="Sections in this batch"
    )
    depends_on_batch: Optional[int] = Field(
        None,
        description="Batch number that must complete first"
    )
    can_parallel: bool = Field(
        True,
        description="Whether sections in this batch can run in parallel"
    )


# ─────────────────────────────────────────────
# Quality Targets
# ─────────────────────────────────────────────

class QualityTargets(BaseModel):
    """Quality scoring and validation requirements for the generated document."""

    min_quality_score: float = Field(
        0.85, ge=0.0, le=1.0,
        description="Minimum acceptable quality score (0.0-1.0)"
    )
    validation_required: bool = Field(
        True,
        description="Whether validation agent must review before finalization"
    )
    human_review_sections: List[str] = Field(
        default_factory=list,
        description="Section IDs requiring human review (high complexity/risk sections)"
    )


# ─────────────────────────────────────────────
# Clarifications
# ─────────────────────────────────────────────

class Clarification(BaseModel):
    """A question for the user when critical data is missing."""

    priority: Literal["critical", "high", "medium", "low"] = Field(
        ..., description="How important this is"
    )
    question: str = Field(..., description="Question to ask the user")
    context: str = Field(
        "",
        description="Why this is needed (which section, what impact)"
    )
    impact_if_skipped: str = Field(
        "",
        description="What happens if user doesn't answer"
    )
    can_skip: bool = Field(
        True,
        description="Whether generation can proceed without this"
    )
    suggested_format: str = Field(
        "",
        description="Hint for the user on how to provide the answer"
    )


# ─────────────────────────────────────────────
# Top-level output
# ─────────────────────────────────────────────

class BlueprintOutput(BaseModel):
    """
    Primary output of the Blueprint Agent.

    This is the complete generation plan — it tells all downstream agents
    exactly what to generate, how to generate it, and in what order.
    Written to state['hld_structure'] as a dict.
    """

    # Metadata
    blueprint_id: str = Field(
        ...,
        description="Unique blueprint ID, e.g. 'bp_vodafone_dsr_hld_20260211'"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp of creation"
    )
    product: str = Field(
        ...,
        description="Identified product, e.g. '5G_SBA' or 'DSR'"
    )
    document_type: str = Field(
        "HLD",
        description="Document type (always 'HLD' for v1)"
    )
    customer_name: str = Field(..., description="Customer / client name")
    project_name: str = Field(..., description="Project name / identifier")

    # The plan
    sections: List[SectionPlan] = Field(
        ...,
        description="Ordered list of all sections to generate"
    )
    generation_batches: List[GenerationBatch] = Field(
        default_factory=list,
        description="Execution batches respecting dependencies"
    )

    # Data health
    clarifications: List[Clarification] = Field(
        default_factory=list,
        description="Questions for user (if critical data is missing)"
    )
    can_proceed: bool = Field(
        True,
        description="Whether generation can proceed without user input"
    )

    # Global context for all sections
    template_variables: Dict[str, str] = Field(
        default_factory=dict,
        description="Global template variables: customer_name, nf_list, site_names, etc."
    )

    # Summary
    data_assessment_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Overall data completeness stats and gap summary"
    )
    total_estimated_tokens: int = Field(
        0,
        description="Sum of all section token estimates"
    )
    total_rag_queries: int = Field(
        0,
        description="Total planned RAG queries across all sections"
    )

    # Quality targets
    quality_targets: QualityTargets = Field(
        default_factory=QualityTargets,
        description="Quality scoring and validation requirements"
    )


# ─────────────────────────────────────────────
# Internal Blueprint Agent state (LangGraph)
# ─────────────────────────────────────────────

from typing import TypedDict


class GlobalPlanningContext(TypedDict, total=False):
    """
    Global planning context built in Phase 1.

    Contains dependency graph, conditional hints, and planning instructions
    for section-by-section planning in Phase 2.
    """
    planning_instructions: Dict[str, Any]
    section_ordering_rules: Dict[str, Any]
    nf_architecture_pattern: Dict[str, Any]
    product_specific_sections: Dict[str, Any]
    validation_rules: Dict[str, Any]
    dependency_graph: Dict[str, List[str]]  # section_id -> list of dependency section_ids
    conditional_hints: Dict[str, Optional[bool]]  # section_id -> include hint (True/False/None)


class BlueprintState(TypedDict, total=False):
    """
    Internal state for the Blueprint Agent's LangGraph pipeline.

    NEW ARCHITECTURE (3 phases):
      Phase 1: identify_product + build global planning context
      Phase 2: section-by-section planning with integrated asset assignment
      Phase 3: build_execution_plan

    OLD ARCHITECTURE (deprecated):
      identify_product → plan_sections → assign_assets → build_execution_plan
    """

    # Inputs (set at start)
    knowledge_base: Dict[str, Any]             # DocumentKnowledgeBase as dict
    image_inventory: Optional[Dict[str, Any]]  # ImageInventory as dict
    structured_intent: Optional[Dict[str, Any]]  # StructuredIntent from Intent Interpreter
    product_id: Optional[str]                  # CRITICAL: Product ID from job (e.g., "Sessions", "DSR")
                                               # When provided, Phase 1 uses this instead of auto-detecting
                                               # Ensures product ID consistency across all agents

    # Phase 1 outputs
    identified_product: Optional[str]          # e.g. "5G_SBA", "DSR"
    product_profile: Optional[Dict[str, Any]]       # Loaded product planning JSON
    template_variables: Dict[str, str]         # Global variables
    document_type: str                         # "HLD" for now
    global_planning_context: GlobalPlanningContext  # NEW: dependency graph, conditional hints

    # Phase 2 outputs (section-by-section planning with assets)
    planned_sections: Optional[List[Dict[str, Any]]]  # SectionPlan dicts WITH assets assigned

    # Phase 3 outputs (execution plan)
    generation_batches: Optional[List[Dict[str, Any]]]
    blueprint_output: Optional[Dict[str, Any]]  # Final BlueprintOutput as dict

    # Carry-through from earlier phases
    data_assessment: Optional[Dict[str, Any]]
    clarifications: List[Dict[str, Any]]
    can_proceed: bool

    # Control
    current_phase: str                         # identifying | planning | building | complete | error
    errors: List[str]
