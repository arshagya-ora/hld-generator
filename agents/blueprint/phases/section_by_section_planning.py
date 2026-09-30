"""
Phase 2: Section-by-Section Planning with Integrated Asset Assignment

NEW ARCHITECTURE: One comprehensive LLM call per profile section that simultaneously:
- Plans section structure and generation steps based on FULL Document Analyzer output
- Assigns relevant images and tables
- Makes decisions with complete context (profile + Document Analyzer + available assets)

This replaces the old 2-phase approach (section planning + asset assignment) with a
unified, context-rich planning process where the LLM sees everything needed to make
optimal decisions.
"""

import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict

from hld_generator.agents.blueprint.state.models import SectionPlan
from hld_generator.agents.blueprint.phases.global_planning import (
    topological_sort_with_levels,
    build_section_dependency_graph,
)
from hld_generator.agents.blueprint.tools.intent_section_filter import (
    filter_sections_by_intent,
    insert_custom_sections,
    build_intent_context_for_prompt,
)
from hld_generator.shared.llm_wrapper import OCILLMWrapper
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System prompt for section-by-section planning
# ─────────────────────────────────────────────────────────────────────────────

SECTION_BY_SECTION_SYSTEM_PROMPT = """You are a Senior HLD Blueprint Architect for telecom products.

Your task: Plan ONE section of a High-Level Design document completely and assign all relevant assets (images, tables) to it in a single comprehensive decision.

## CRITICAL: Document Analyzer as Primary Decision Driver

The **Document Analyzer output** is the single source of truth for all your decisions. Use it to:
1. Determine if this section is relevant based on ACTUAL project data
2. Extract SPECIFIC facts and data points for generation_steps
3. Decide which images/tables match this section's content
4. Score data completeness based on how much relevant data exists

## Your Responsibilities:

### 1. Section Relevance Decision (Conditional Sections)

**IF profile section has `conditional: true`**:
- Examine the FULL Document Analyzer output carefully
- Determine if section is relevant based on ACTUAL project data:
  - **Component presence**: "sec_ipfe_architecture" → check if IPFE exists in `products.components`
  - **Feature presence**: "sec_congestion_control" → check if congestion control mentioned in `products.features`
  - **Customer-specific patterns**: "sec_executive_summary" → check `document_intelligence.customer_name` against VIL/TCL patterns
- Set `include: true` ONLY if Document Analyzer contains relevant data for this section
- Set `include: false` if Document Analyzer lacks data for this section
- Provide detailed `include_reason` citing specific Document Analyzer fields (e.g., "IPFE component found in products.components[0].name" or "No IPFE component found in Document Analyzer - excluding section")

**IF profile section has `conditional: false` (Mandatory)**:
- Always include mandatory sections regardless of Document Analyzer content
- If Document Analyzer lacks data, set `data_completeness: 0.3-0.5` and list `missing_data_critical`
- Generate template-based generation_steps using profile example_content

### 2. Generation Steps - Extract from Document Analyzer

Every generation_step MUST reference ACTUAL project data from Document Analyzer:

**GOOD Examples** (specific, references actual data):
- "State DA-MP capacity: 25K MPS per instance (from Document Analyzer: products.capacity_and_sizing.da_mp_capacity)"
- "Describe IPFE warm-standby failover using TSA VIP 10.20.30.40 (from Document Analyzer: infrastructure.ipfe_tsa_vip)"
- "List all deployed sites: UPW (Meerut), PJB (Mohali) (from Document Analyzer: sites[].name and sites[].location)"

**BAD Examples** (generic, no Document Analyzer reference):
- "Describe DA-MP capacity" (generic template)
- "Explain IPFE architecture" (no actual data)

**Requirements**:
- Aim for 6-12 steps per section
- Each step must cite specific Document Analyzer paths: `products.components[0].name`, `sites[0].location`, `capacity_and_sizing.vm_count`
- Complex sections (architecture, HA, routing) warrant 10+ steps

### 3. Content Facts - Verbatim Extraction from Document Analyzer

Extract EXACT strings from Document Analyzer that must appear in final content:
- Do NOT paraphrase
- Copy verbatim from `document_intelligence`, `products`, `capacity_and_sizing`, etc.
- Example: If Document Analyzer has `"deployment_model": "Geo-redundant Active/Standby pairs across UPW and PJB sites"`, then content_fact should be exactly: `"Geo-redundant Active/Standby pairs across UPW and PJB sites"`

### 4. Asset Assignment (Images & Tables) - INTEGRATED DECISION

**For IMAGES**:
1. Read `surrounding_text` (figure caption) — strongest signal
2. Read `vision_analysis` (components_shown, purpose, relationships_shown)
3. **Cross-reference with Document Analyzer**: Does the image illustrate concepts present in Document Analyzer for THIS section?
   - Example: Image shows "IPFE failover" + Document Analyzer has IPFE deployment details → assign to IPFE architecture section
   - Example: Image shows "capacity chart" + Document Analyzer has capacity data → assign to capacity sizing section
4. Set `figure_title` from caption or derive from vision analysis
5. Set confidence:
   - "high" if caption explicitly names section topic AND Document Analyzer confirms topic relevance
   - "medium" if visual content strongly implies topic AND Document Analyzer has related data
   - "low" if best guess
6. Write detailed `assign_reason` (3-5 sentences) citing:
   - Specific signals from surrounding_text/vision_analysis
   - Specific Document Analyzer fields that match the image content
   - Why this section is the best fit

**For TABLES**:
1. Read `section_reference` (original document heading) — primary signal
2. Read `description` and `markdown_preview`
3. **Cross-reference with Document Analyzer**: Does the table contain data present in Document Analyzer for THIS section?
   - Example: Table has "VM sizing" + Document Analyzer has VM capacity details → assign to capacity section
4. Set `use_as` to semantic role (SCREAMING_SNAKE_CASE, e.g., "VM_SIZING_MATRIX", "INTERFACE_CAPACITY_TABLE")
5. Write detailed `assign_reason` (2-4 sentences) citing Document Analyzer correlation

**CRITICAL RULES**:
- Do NOT assign assets already used by previous sections (check "Available Images/Tables" list)
- Do NOT hallucinate image_ids or table_ids — use ONLY IDs from the input lists
- Limit: Max 3 images, max 3 tables per section (keep highest-confidence matches)
- **Document Analyzer validation**: Only assign assets that illustrate concepts PRESENT in Document Analyzer

### 5. RAG Queries - Refine from profile Baseline

Start with profile's rag_queries baseline. Enhance with:
- Project-specific terms from Document Analyzer (customer name, component names, version numbers, site names)
- GOOD: "DSR IPFE warm standby TSA ARP failover VIL deployment UPW PJB sites"
- BAD: "IPFE architecture" (too generic)

### 6. Data Completeness - Honest Scoring Based on Document Analyzer

Score based on Document Analyzer content richness for THIS section:
- **1.0** = Document Analyzer has complete data for all subsections of this section
- **0.8** = Good data, minor gaps (can generate quality content with small assumptions)
- **0.5** = Partial data, major gaps requiring significant assumptions
- **0.2** = Minimal data, mostly template-based generation required
- **0.0** = No relevant data in Document Analyzer for this section

Be accurate. Do not inflate scores. If Document Analyzer lacks data for this section, score appropriately.

### 7. Quality Checks - Binary Pass/Fail Criteria

Each check must be testable without human judgement:
- GOOD: "Section must name all 8 DSR components: IPFE, DA-MP, NOAM, SOAM, IDIH, UDR, SLF, SBR"
- GOOD: "VM sizing table must include vCPU, RAM, HDD columns for all 10 VM types"
- BAD: "Content should be clear" (subjective)

### 8. Subsections - Match profile Hierarchy Exactly

Use the subsection structure from profile's hierarchy.subsections field. PRESERVE nested hierarchies (3-4 levels deep) - do NOT flatten.

**Subsection Parsing Algorithm** (recursive):
1. Recursively walk hierarchy.subsections and nested sub_subsections
2. For each entry:
   - If subsection_number is present, use it
   - If missing, extract from title (e.g., "3.2.1 Title" → number="3.2.1", title="Title")
   - If still missing, auto-generate based on parent number
   - Create subsection object with 'subsections' array (empty if no children)
3. Extract generation_notes from:
   - profile subsection's 'notes' field (if present)
   - OR from generation.generation_flow array by matching subsection_number
   - Format: "X.Y Title: Instruction text..." → parse and map to subsection X.Y
4. Recursively process children (sub_subsections) and populate 'subsections' array
5. Return nested structure preserving profile hierarchy

**Subsection Output Schema** (NESTED structure):
Each subsection must have:
- subsection_number: "X.Y" or "X.Y.Z" (string)
- title: "Clean title without number" (string)
- generation_notes: "Specific content instruction for this subsection" (string, can be empty for structural headings)
- subsections: [] (array of nested child subsections, empty if no children)

**CRITICAL**: Preserve the NESTED hierarchy from profile hierarchy.subsections. Do NOT flatten.
If profile has 3-4 levels deep (sub_subsections), output must preserve this nesting.

## Output Format:

Return ONLY a JSON object (no markdown code fences, no prose). Schema:
{
  "section_id": "sec_...",
  "section_number": "X",
  "title": "...",
  "include": true,
  "include_reason": "<mandatory / condition met because [cite Document Analyzer fields] / excluded because [Document Analyzer lacks X]>",
  "subsections": [
    {
      "subsection_number": "X",
      "title": "Clean title",
      "generation_notes": "Specific instruction from profile notes or generation_flow",
      "subsections": []  // No children
    },
    {
      "subsection_number": "Y",
      "title": "Another section",
      "generation_notes": "...",
      "subsections": [  // NESTED children
        {
          "subsection_number": "Y.1",
          "title": "Nested subsection",
          "generation_notes": "...",
          "subsections": [  // Can nest 3-4 levels deep
            {
              "subsection_number": "Y.1.1",
              "title": "Deep nested subsection",
              "generation_notes": "...",
              "subsections": []
            }
          ]
        }
      ]
    }
  ],  // NESTED structure preserving profile hierarchy (NOT flat array)
  "generation_strategy": "template|hybrid|rag_heavy|generated",
  "template_ratio": 0-100,
  "rag_ratio": 0-100,
  "estimated_tokens": 500-4000,
  "dependencies": ["sec_id"],

  "generation_steps": [
    "<specific step referencing actual Document Analyzer data with field paths>",
    "..."
  ],
  "content_facts": [
    "<verbatim string from Document Analyzer>",
    "..."
  ],
  "section_project_facts": ["<relevant special_note from Document Analyzer>", ...],
  "quality_checks": ["<binary criterion>", ...],

  "matched_images": [
    {
      "image_id": "image_X",
      "figure_title": "...",
      "assign_reason": "<detailed 3-5 sentence reasoning citing surrounding_text, vision_analysis, AND Document Analyzer field correlation>",
      "confidence": "high|medium|low",
      "vision_type": "architecture_diagram|chart|..."
    }
  ],
  "matched_tables": [
    {
      "extracted_table_id": "Table_Y",
      "use_as": "SEMANTIC_ROLE_NAME",
      "description": "...",
      "assign_reason": "<detailed 2-4 sentence reasoning citing section_reference AND Document Analyzer field correlation>",
      "confidence": "high|medium|low"
    }
  ],

  "rag_queries": [
    {
      "query": "<specific retrieval query with project terms from Document Analyzer>",
      "target_content": "what we expect to find",
      "top_k": 5
    }
  ],
  "data_completeness": 0.0-1.0,
  "missing_data_critical": ["<specific missing item>", ...],
  "missing_data_important": ["<specific missing item>", ...],
  "missing_data_optional": ["<specific missing item>", ...],
  "assumptions": ["<specific assumption made>", ...]
}

**CRITICAL**: Be thorough, specific, and detailed. Every generation_step must reference actual Document Analyzer data. Every asset assignment must cite Document Analyzer field correlation. Do NOT use generic templates - ground everything in the actual project data from Document Analyzer."""


MAX_PARALLEL_SECTIONS = 5  # Concurrent LLM calls per batch


class SectionBySectionPlanningPhase:
    """
    Phase 2: Section-by-Section Planning with Integrated Asset Assignment.

    For each profile section, makes ONE comprehensive LLM call that:
    - Plans section based on FULL Document Analyzer output
    - Assigns relevant images and tables
    - Makes all decisions with complete context

    Processes sections in dependency-aware parallel batches for speed.
    """

    def __init__(self, llm: OCILLMWrapper):
        self.llm = llm

    async def execute(
        self,
        knowledge_base: Dict[str, Any],
        product_profile: Dict[str, Any],
        template_variables: Dict[str, str],
        global_planning_context: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]] = None,
        structured_intent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute Phase 2: Section-by-Section Planning with Asset Assignment.

        Args:
            knowledge_base: Full DocumentKnowledgeBase dict (Document Analyzer output)
            product_profile: Product profile dict (from ProductProfile.to_dict())
            template_variables: Extracted template variables
            global_planning_context: Global planning context from Phase 1
            image_inventory: ImageInventory dict (optional)
            structured_intent: StructuredIntent dict from Intent Interpreter (optional)

        Returns:
            Dict with:
              - planned_sections: List[dict] of complete SectionPlan dicts with assets assigned
        """
        logger.info("Phase 2: Section-by-Section Planning with Integrated Asset Assignment")

        # Store intent for use in prompts
        self._structured_intent = structured_intent

        profile_sections = product_profile.get("sections", [])

        # ── Intent-based section filtering (deterministic, pre-LLM) ──
        if structured_intent:
            logger.info("  Applying structured intent filters...")
            profile_sections = filter_sections_by_intent(profile_sections, structured_intent)
            profile_sections = insert_custom_sections(profile_sections, structured_intent)
            # Update product_profile with filtered sections for downstream usage
            product_profile = {**product_profile, "sections": profile_sections}

        dependency_graph = global_planning_context.get("dependency_graph", {})

        # Build dependency levels for parallel processing
        levels = topological_sort_with_levels(dependency_graph)

        logger.info(
            f"  {len(profile_sections)} sections organized into {len(levels)} dependency levels"
        )

        # Prepare full Document Analyzer digest once (reused for all sections)
        document_analyzer_digest = self._prepare_document_analyzer_digest(knowledge_base)

        # Track assigned assets across all sections
        assigned_image_ids: Set[str] = set()
        assigned_table_ids: Set[str] = set()

        all_planned_sections: List[Dict[str, Any]] = []

        # DEBUG: Log image inventory status
        if image_inventory:
            total_images = len(image_inventory.get("images", []))
            logger.info(f"  Image inventory loaded: {total_images} total images")
        else:
            logger.info(f"  No image inventory provided")

        # Process level by level (sections within a level processed in parallel)
        for level_idx, level_section_ids in enumerate(levels):
            logger.info(f"  Level {level_idx}: Planning {len(level_section_ids)} sections")

            # Process level in batches of MAX_PARALLEL_SECTIONS
            for batch_start in range(0, len(level_section_ids), MAX_PARALLEL_SECTIONS):
                batch_section_ids = level_section_ids[batch_start : batch_start + MAX_PARALLEL_SECTIONS]

                logger.info(f"    Batch: {batch_section_ids}")

                # Create async tasks for parallel execution
                tasks = []
                for section_id in batch_section_ids:
                    profile_section = self._find_profile_section(section_id, product_profile)
                    if not profile_section:
                        logger.warning(f"      Section {section_id} not found in profile, skipping")
                        continue

                    # Get available assets (exclude already assigned)
                    available_images = self._get_available_images(image_inventory, assigned_image_ids)
                    available_tables = self._get_available_tables(knowledge_base, assigned_table_ids)

                    # DEBUG: Log available assets for this section
                    logger.info(f"    Section {section_id}: {len(available_images)} images available (already assigned: {len(assigned_image_ids)})")

                    # Build prompt for this section
                    prompt = self._build_section_prompt(
                        profile_section=profile_section,
                        global_context=global_planning_context,
                        template_variables=template_variables,
                        document_analyzer_digest=document_analyzer_digest,
                        available_images=available_images,
                        available_tables=available_tables,
                        completed_sections=all_planned_sections,
                        structured_intent=self._structured_intent,
                    )

                    # Create async task
                    tasks.append(
                        self._call_llm_for_section(
                            prompt=prompt,
                            section_id=section_id,
                            profile_section=profile_section
                        )
                    )

                # Execute batch in parallel
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.error(f"      Section planning failed: {result}")
                        continue

                    if result is None:
                        continue

                    # DEBUG: Log LLM response assets
                    section_id_debug = result.get("section_id", "unknown")
                    llm_images = result.get("matched_images", [])
                    llm_tables = result.get("matched_tables", [])
                    logger.info(f"      LLM response for {section_id_debug}: {len(llm_images)} images, {len(llm_tables)} tables")

                    # Validate and enrich section
                    validated_section = self._validate_and_enrich_section(
                        section_plan=result,
                        profile_section=self._find_profile_section(result.get("section_id", ""), product_profile),
                        image_inventory=image_inventory,
                        knowledge_base=knowledge_base,
                        template_variables=template_variables,
                    )

                    # DEBUG: Log validated assets
                    validated_images = validated_section.get("matched_images", [])
                    validated_tables = validated_section.get("matched_tables", [])
                    logger.info(f"      After validation for {section_id_debug}: {len(validated_images)} images, {len(validated_tables)} tables")

                    # Track assigned assets
                    for img in validated_section.get("matched_images", []):
                        assigned_image_ids.add(img["image_id"])
                    for tbl in validated_section.get("matched_tables", []):
                        assigned_table_ids.add(tbl["extracted_table_id"])

                    all_planned_sections.append(validated_section)

        logger.info(
            f"  Completed: {len(all_planned_sections)} sections planned, "
            f"{len(assigned_image_ids)} images assigned, {len(assigned_table_ids)} tables assigned"
        )

        return {"planned_sections": all_planned_sections}

    # ─────────────────────────────────────────────────────────────────────────
    # Document Analyzer Digest Preparation
    # ─────────────────────────────────────────────────────────────────────────

    def _prepare_document_analyzer_digest(
        self,
        knowledge_base: Dict[str, Any]
    ) -> str:
        """
        Format the complete DocumentKnowledgeBase structure for LLM prompt.

        Minimal filtering - preserve all sections of Document Analyzer to allow
        LLM to make informed decisions about section relevance and content facts.

        Args:
            knowledge_base: Full DocumentKnowledgeBase dict

        Returns:
            Formatted string digest (target: 2500-4000 tokens)
        """
        lines = []

        lines.append("## DOCUMENT ANALYZER OUTPUT (Complete Project Data)")
        lines.append("")
        lines.append("Use this as the PRIMARY SOURCE for all decisions:")
        lines.append("")

        # Document Intelligence
        doc_intel = knowledge_base.get("document_intelligence", {})
        if doc_intel:
            lines.append("### document_intelligence:")
            lines.append(f"  customer: {doc_intel.get('customer', 'N/A')}")
            lines.append(f"  project_name: {doc_intel.get('project_name', 'N/A')}")
            lines.append(f"  primary_products: {doc_intel.get('primary_products', [])}")

            project_overview = doc_intel.get("project_overview", "")
            if project_overview:
                lines.append(f"  project_overview: {project_overview[:500]}...")

            special_notes = doc_intel.get("special_notes", [])
            if special_notes:
                lines.append("  special_notes:")
                for note in special_notes[:10]:  # Show up to 10 notes
                    lines.append(f"    - {note[:200]}")

        # Products (components, features, interfaces)
        products = knowledge_base.get("products", {})
        if products:
            lines.append("")
            lines.append("### products:")
            for prod_name, prod_info in list(products.items())[:5]:  # Show up to 5 products
                if isinstance(prod_info, dict):
                    lines.append(f"  {prod_name}:")
                    lines.append(f"    components: {prod_info.get('components', [])}")
                    lines.append(f"    features: {prod_info.get('features', [])[:10]}")  # First 10 features
                    lines.append(f"    interfaces: {prod_info.get('interfaces', [])[:10]}")  # First 10 interfaces

        # Sites
        sites = knowledge_base.get("sites", [])
        if sites:
            lines.append("")
            lines.append("### sites:")
            for site in sites[:10]:  # Show up to 10 sites
                if isinstance(site, dict):
                    lines.append(f"  - name: {site.get('name', 'N/A')}, location: {site.get('location', 'N/A')}")
                    deployed_nfs = site.get("deployed_nfs", [])
                    if deployed_nfs:
                        lines.append(f"    deployed_nfs: {deployed_nfs}")

        # Capacity and Sizing
        capacity = knowledge_base.get("capacity_and_sizing", {})
        if capacity:
            lines.append("")
            lines.append("### capacity_and_sizing:")
            capacity_str = json.dumps(capacity, indent=2, default=str)[:1000]
            lines.append(f"  {capacity_str}...")

        # Network and Integration
        network = knowledge_base.get("network_and_integration", {})
        if network:
            lines.append("")
            lines.append("### network_and_integration:")
            network_str = json.dumps(network, indent=2, default=str)[:1000]
            lines.append(f"  {network_str}...")

        # Infrastructure
        infra = knowledge_base.get("infrastructure", {})
        if infra:
            lines.append("")
            lines.append("### infrastructure:")
            lines.append(f"  deployment_model: {infra.get('deployment_model', 'N/A')}")
            lines.append(f"  platform_version: {infra.get('platform_version', 'N/A')}")

        # Deployment Plan
        deployment_plan = knowledge_base.get("deployment_plan", {})
        if deployment_plan:
            lines.append("")
            lines.append("### deployment_plan:")
            deploy_str = json.dumps(deployment_plan, indent=2, default=str)[:800]
            lines.append(f"  {deploy_str}...")

        # Timeline
        timeline = knowledge_base.get("timeline", {})
        if timeline:
            lines.append("")
            lines.append("### timeline:")
            timeline_str = json.dumps(timeline, indent=2, default=str)[:500]
            lines.append(f"  {timeline_str}...")

        # Security Requirements
        security = knowledge_base.get("security_requirements", {})
        if security:
            lines.append("")
            lines.append("### security_requirements:")
            security_str = json.dumps(security, indent=2, default=str)[:500]
            lines.append(f"  {security_str}...")

        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Section Prompt Building
    # ─────────────────────────────────────────────────────────────────────────

    def _build_section_prompt(
        self,
        profile_section: Dict[str, Any],
        global_context: Dict[str, Any],
        template_variables: Dict[str, str],
        document_analyzer_digest: str,
        available_images: List[Dict[str, Any]],
        available_tables: List[Dict[str, Any]],
        completed_sections: List[Dict[str, Any]],
        structured_intent: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build the user prompt for planning ONE section.

        Args:
            profile_section: profile section definition
            global_context: Global planning context
            template_variables: Template variables
            document_analyzer_digest: Formatted Document Analyzer output
            available_images: List of unassigned images
            available_tables: List of unassigned tables
            completed_sections: List of already planned sections

        Returns:
            User prompt string
        """
        lines = []

        lines.append("# SECTION TO PLAN")
        lines.append("")

        # NEW: Pass complete profile section object as JSON for LLM parsing
        lines.append("## Product Profile Section Definition (COMPLETE)")
        lines.append("")
        lines.append("The following is the COMPLETE profile section object with ALL fields.")
        lines.append("Parse this object to extract subsections, generation instructions, and metadata.")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(profile_section, indent=2))
        lines.append("```")
        lines.append("")
        lines.append("**PARSING INSTRUCTIONS**:")
        lines.append("")
        lines.append("1. **Subsections** (from hierarchy.subsections):")
        lines.append("   - PRESERVE nested structure (do NOT flatten)")
        lines.append("   - Recursively process sub_subsections (3-4 levels deep)")
        lines.append("   - Each subsection must have 'subsections' array (empty if no children)")
        lines.append("   - Auto-generate subsection numbers for entries missing subsection_number")
        lines.append("   - Extract number from title if present (e.g., '3.2.1 Original Deployment' → number='3.2.1', title='Original Deployment')")
        lines.append("   - Preserve 'notes' field as 'generation_notes' for each subsection at any nesting level")
        lines.append("")
        lines.append("2. **Subsection Content Instructions** (from generation.generation_flow):")
        lines.append("   - Parse generation_flow array to extract subsection-specific instructions")
        lines.append("   - Format: 'X.Y Subsection Title: Content instruction text...'")
        lines.append("   - Example: '5.1 Product Overview: High-level DSR platform description...'")
        lines.append("   - Map each flow item to corresponding subsection_number (5.1, 5.2, etc.)")
        lines.append("   - Populate each subsection's generation_notes with the instruction text")
        lines.append("")
        lines.append("3. **Metadata Preservation**:")
        lines.append("   - Use generation.strategy, generation.template_ratio, generation.rag_ratio")
        lines.append("   - Use generation.estimated_tokens")
        lines.append("   - Use generation.dependencies array")
        lines.append("   - Use content patterns and approved input documents for style guidance")
        lines.append("   - Use content_patterns for structural guidance")
        lines.append("")
        lines.append("4. **RAG Queries** (from rag_queries array):")
        lines.append("   - Start with profile's rag_queries baseline")
        lines.append("   - Enhance with project-specific terms from Document Analyzer")
        lines.append("   - Add customer name, component names, version numbers, site names")
        lines.append("   - Example: 'DSR IPFE warm standby TSA ARP failover VIL deployment UPW PJB sites'")
        lines.append("   - Each query should target specific content retrieval for this section")
        lines.append("")
        lines.append("---")
        lines.append("")

        # User Intent Directives (if available)
        intent_context = build_intent_context_for_prompt(structured_intent)
        if intent_context:
            lines.append(intent_context)

        # Section-specific style overrides from intent
        section_id = profile_section.get("section_id", "")
        style_override = profile_section.get("_style_override")
        if style_override:
            lines.append("## STYLE OVERRIDE FOR THIS SECTION (from user intent)")
            lines.append("")
            if style_override.get("detail_level"):
                lines.append(f"Detail level: {style_override['detail_level']}")
            if style_override.get("max_subsections"):
                lines.append(f"Max subsections: {style_override['max_subsections']}")
            if style_override.get("estimated_tokens"):
                lines.append(f"Token budget: {style_override['estimated_tokens']}")
            if style_override.get("custom_instructions"):
                lines.append(f"Custom instructions: {style_override['custom_instructions']}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # Global Context
        lines.append("## Global Context")
        lines.append("")
        lines.append(f"Customer: {template_variables.get('customer_name', 'N/A')}")
        lines.append(f"Project: {template_variables.get('project_name', 'N/A')}")
        lines.append(f"Components (nf_list): {template_variables.get('nf_list', 'N/A')}")
        lines.append(f"Sites: {template_variables.get('site_names', 'N/A')}")
        lines.append(f"Deployment Model: {template_variables.get('deployment_model', 'N/A')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # FULL Document Analyzer Output
        lines.append(document_analyzer_digest)

        # Available Images
        lines.append("## Available Images for Assignment")
        lines.append("")
        if not available_images:
            lines.append("No images available (all assigned to previous sections).")
        else:
            lines.append(f"Total unassigned images: {len(available_images)}")
            lines.append("")
            for img in available_images[:15]:  # Show up to 15 images to conserve tokens
                image_id = img.get("image_id", "?")
                surrounding_text = (img.get("surrounding_text") or "")[:200]
                vision_analysis = img.get("vision_analysis") or {}
                components_shown = vision_analysis.get("components_shown", [])
                purpose = (vision_analysis.get("purpose") or "")[:150]
                vision_type = vision_analysis.get("type") or vision_analysis.get("vision_type", "unknown")

                lines.append(f"[{image_id}]")
                lines.append(f"  surrounding_text: {surrounding_text}")
                lines.append(f"  vision_type: {vision_type}")
                lines.append(f"  components_shown: {components_shown}")
                lines.append(f"  purpose: {purpose}")
                lines.append("")

        lines.append("---")
        lines.append("")

        # Available Tables
        lines.append("## Available Tables for Assignment")
        lines.append("")
        if not available_tables:
            lines.append("No tables available (all assigned to previous sections).")
        else:
            lines.append(f"Total unassigned tables: {len(available_tables)}")
            lines.append("")
            for tbl in available_tables[:15]:  # Show up to 15 tables
                table_id = tbl.get("table_id", "?")
                section_ref = tbl.get("section_reference", "unknown")
                description = (tbl.get("description") or "")[:150]
                markdown = tbl.get("markdown") or ""
                has_content = bool(markdown and markdown.strip())

                if has_content:
                    preview_lines = markdown.splitlines()[:2]
                    preview = " | ".join(preview_lines)[:200]
                else:
                    preview = "(empty table)"

                lines.append(f"[{table_id}]")
                lines.append(f"  section_reference: {section_ref}")
                lines.append(f"  description: {description}")
                lines.append(f"  preview: {preview}")
                lines.append("")

        lines.append("---")
        lines.append("")

        # Dependency Status
        lines.append("## Dependency Status")
        lines.append("")
        section_id = profile_section.get("section_id", "")
        dependencies = profile_section.get("generation", {}).get("dependencies", [])
        if not dependencies:
            lines.append("No dependencies for this section.")
        else:
            completed_ids = {s.get("section_id") for s in completed_sections}
            for dep_id in dependencies:
                if dep_id in completed_ids:
                    lines.append(f"  {dep_id}: Planned (available)")
                else:
                    lines.append(f"  {dep_id}: Not yet planned (use placeholder reference)")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("Plan this section completely. Return ONLY JSON (no markdown fences, no prose).")

        return "\n".join(lines)

    def _format_subsection_hierarchy(
        self,
        subsections: List[Dict[str, Any]],
        lines: List[str],
        indent: int = 0
    ):
        """
        Recursively format subsection hierarchy for prompt display.
        """
        for sub in subsections:
            sub_num = sub.get("subsection_number", "")
            sub_title = sub.get("title", "")
            prefix = "  " * indent + ("↳ " if indent > 0 else "")
            lines.append(f"{prefix}{sub_num} {sub_title}")

            # Recurse for nested subsections
            children = sub.get("sub_subsections", [])
            if children:
                self._format_subsection_hierarchy(children, lines, indent + 1)

    # ─────────────────────────────────────────────────────────────────────────
    # LLM Call for Single Section
    # ─────────────────────────────────────────────────────────────────────────

    async def _call_llm_for_section(
        self,
        prompt: str,
        section_id: str,
        profile_section: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Make LLM call to plan ONE section.

        Args:
            prompt: User prompt for this section
            section_id: Section ID being planned
            profile_section: profile section definition (for fallback)

        Returns:
            Section plan dict or None if failed
        """
        logger.info(f"      LLM call for {section_id}")

        try:
            # Use larger max_tokens for comprehensive planning with full Document Analyzer
            result = await self.llm.chat_json(
                system_prompt=SECTION_BY_SECTION_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=12000,  # Allow space for comprehensive response
                temperature=None,  # Use OCI default
            )

            if isinstance(result, dict):
                logger.info(f"      OK {section_id}: LLM planning successful")
                return result
            else:
                logger.warning(f"      FAIL {section_id}: LLM returned non-dict, using profile fallback")
                return None

        except Exception as e:
            logger.error(f"      FAIL {section_id}: LLM call failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Validation and Enrichment
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_and_enrich_section(
        self,
        section_plan: Dict[str, Any],
        profile_section: Optional[Dict[str, Any]],
        image_inventory: Optional[Dict[str, Any]],
        knowledge_base: Dict[str, Any],
        template_variables: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Validate and enrich section plan with profile defaults and asset enrichment.

        Args:
            section_plan: LLM output section plan
            profile_section: Corresponding profile section (if found)
            image_inventory: ImageInventory for populating storage_path
            knowledge_base: DocumentKnowledgeBase for table markdown
            template_variables: Template variables

        Returns:
            Validated and enriched section plan dict
        """
        # Set defaults for all required fields
        section_plan.setdefault("section_id", "sec_unknown")
        section_plan.setdefault("section_number", "0")
        section_plan.setdefault("title", "Untitled Section")
        section_plan.setdefault("include", True)
        section_plan.setdefault("include_reason", "mandatory")
        section_plan.setdefault("generation_strategy", "hybrid")
        section_plan.setdefault("template_ratio", 50)
        section_plan.setdefault("rag_ratio", 50)
        section_plan.setdefault("estimated_tokens", 1000)
        section_plan.setdefault("dependencies", [])
        section_plan.setdefault("generation_steps", [])
        section_plan.setdefault("content_facts", [])
        section_plan.setdefault("quality_checks", [])
        section_plan.setdefault("section_project_facts", [])
        section_plan.setdefault("rag_queries", [])
        section_plan.setdefault("subsections", [])
        section_plan.setdefault("data_completeness", 1.0)
        section_plan.setdefault("missing_data_critical", [])
        section_plan.setdefault("missing_data_important", [])
        section_plan.setdefault("missing_data_optional", [])
        section_plan.setdefault("assumptions", [])
        section_plan.setdefault("exemplar_snippet", None)
        section_plan.setdefault("content_patterns", {})
        section_plan.setdefault("matched_images", [])
        section_plan.setdefault("matched_tables", [])
        section_plan.setdefault("generate_order", 1)
        section_plan.setdefault("ready_to_generate", True)
        section_plan.setdefault("requirements_to_address", [])

        # Enrich from profile if section_id matches
        if profile_section:
            if not section_plan.get("exemplar_snippet"):
                section_plan["exemplar_snippet"] = profile_section.get("exemplar_snippet")
            if not section_plan.get("content_patterns"):
                section_plan["content_patterns"] = profile_section.get("content_patterns", {})

            # ALWAYS extract profile generation metadata for content generation (even if content_patterns is empty)
            profile_generation = profile_section.get("generation", {})
            if profile_generation:
                # Extract generation_flow and generation_notes to pass to content generation
                section_plan.setdefault("generation_flow", profile_generation.get("generation_flow", []))
                section_plan.setdefault("generation_notes", profile_section.get("generation_notes", ""))

            # Extract subsection-level metadata for special sections (e.g., glossaries, appendices)
            hierarchy = profile_section.get("hierarchy", {})
            for subsection in hierarchy.get("subsections", []):
                subsection_id = subsection.get("subsection_id", "")

                # Extract master glossary for Section 1.4 (Terms and Definitions)
                if subsection_id == "subsec_1.4_terms_and_definitions":
                    glossary_terms = subsection.get("terms_and_definitions_key_terms", [])
                    if glossary_terms:
                        # Add to content_patterns so prompt builder can inject it
                        if "content_patterns" not in section_plan:
                            section_plan["content_patterns"] = {}
                        section_plan["content_patterns"]["master_glossary"] = glossary_terms
                        logger.info(f"  Extracted {len(glossary_terms)} master glossary terms for {section_plan.get('section_id')}")

                # Extract never_hallucinate warnings from any subsection
                never_hallucinate = subsection.get("never_hallucinate", [])
                if never_hallucinate:
                    if "hallucination_guards" not in section_plan:
                        section_plan["hallucination_guards"] = []
                    section_plan["hallucination_guards"].extend(never_hallucinate)

            # Fill quality_checks from profile if LLM left them empty
            if not section_plan["quality_checks"]:
                section_plan["quality_checks"] = (
                    profile_section.get("generation", {}).get("quality_checks", [])
                )

            # Fill rag_queries from profile if LLM left them empty
            if not section_plan.get("rag_queries"):
                section_plan["rag_queries"] = profile_section.get("rag_queries", [])

            # Fill subsections from profile if LLM left them empty (FALLBACK - should rarely trigger)
            if not section_plan.get("subsections"):
                logger.warning(f"  LLM did not populate subsections for {section_plan.get('section_id')}")
                # Leave empty - LLM should have parsed from profile section object
                section_plan["subsections"] = []

            # Fill generation metadata from profile if LLM omitted them
            if not section_plan.get("generation_strategy") or section_plan["generation_strategy"] == "hybrid":
                kb_gen = profile_section.get("generation", {})
                section_plan.setdefault("generation_strategy", kb_gen.get("strategy", "hybrid"))
                section_plan.setdefault("template_ratio", kb_gen.get("template_ratio", 50))
                section_plan.setdefault("rag_ratio", kb_gen.get("rag_ratio", 50))
                section_plan.setdefault("estimated_tokens", kb_gen.get("estimated_tokens", 1000))

            # FIX: Copy conditional flag from profile (Bug 1)
            is_conditional = profile_section.get("conditional", False)
            section_plan["conditional"] = is_conditional

            # Conditional section guard (same as old logic)
            if is_conditional and section_plan.get("include", True):
                include_reason = (section_plan.get("include_reason") or "").strip()
                if not include_reason or include_reason in ("mandatory", "mandatory profile section"):
                    section_plan["include"] = False
                    section_plan["include_reason"] = (
                        "Conditional section excluded — LLM set include=True but provided "
                        "no project-specific justification. Defaulting to exclude (safe)."
                    )
                    section_plan["ready_to_generate"] = False
                    # FIX: Set condition_met = false (Bug 2)
                    section_plan["condition_met"] = False
                    logger.info(
                        f"  Conditional guard: '{section_plan.get('section_id')}' excluded "
                        f"(no LLM justification for inclusion)."
                    )
                else:
                    # FIX: Conditional section included with valid justification
                    section_plan["condition_met"] = True
                    logger.info(
                        f"  Conditional section '{section_plan.get('section_id')}' included: {include_reason}"
                    )
            elif is_conditional and not section_plan.get("include", True):
                # FIX: Conditional section explicitly excluded by LLM
                section_plan["condition_met"] = False
            else:
                # FIX: Mandatory section (non-conditional) - condition_met not applicable
                section_plan["condition_met"] = None

        # FIX Bug 3: Fill dependencies from profile generation config if not set by LLM
        if profile_section and not section_plan.get("dependencies"):
            kb_gen = profile_section.get("generation", {})
            section_plan["dependencies"] = kb_gen.get("dependencies", [])

        # Apply structured intent style overrides (deterministic, post-LLM)
        style_override = (profile_section or {}).get("_style_override")
        if style_override:
            if style_override.get("detail_level"):
                section_plan["detail_level"] = style_override["detail_level"]
            if style_override.get("estimated_tokens"):
                section_plan["estimated_tokens"] = style_override["estimated_tokens"]
            if style_override.get("max_subsections") and section_plan.get("subsections"):
                max_sub = style_override["max_subsections"]
                section_plan["subsections"] = section_plan["subsections"][:max_sub]

        # FIX Bug 10: Zero out estimated_tokens for excluded sections
        if not section_plan.get("include", True):
            section_plan["estimated_tokens"] = 0

        # Auto-populate requirements_to_address from generation_steps if not set
        if not section_plan.get("requirements_to_address") and section_plan.get("generation_steps"):
            section_plan["requirements_to_address"] = section_plan["generation_steps"]

        # Ensure subsections is a list (LLM should have populated with nested structure)
        if not isinstance(section_plan.get("subsections"), list):
            section_plan["subsections"] = []

        # DEBUG: Log images before enrichment
        incoming_images = section_plan.get("matched_images", [])
        logger.debug(f"    Enriching {section_plan.get('section_id', '?')}: {len(incoming_images)} images before enrichment")

        # Enrich matched images with storage_path from ImageInventory
        if image_inventory:
            images_list = image_inventory.get("images", [])
            for matched_img in section_plan.get("matched_images", []):
                image_id = matched_img.get("image_id")
                if image_id:
                    # Find image in inventory and populate storage_path
                    for inv_img in images_list:
                        if inv_img.get("image_id") == image_id:
                            matched_img["storage_path"] = inv_img.get("storage_path", "")
                            if not matched_img.get("vision_type"):
                                vision = inv_img.get("vision_analysis") or {}
                                matched_img["vision_type"] = (
                                    vision.get("type") or vision.get("vision_type", "unknown")
                                )
                            break

        # DEBUG: Log images after enrichment
        enriched_images = section_plan.get("matched_images", [])
        logger.debug(f"    After enrichment: {len(enriched_images)} images with storage_path populated")

        # Enrich matched tables with markdown from DocumentKnowledgeBase
        if knowledge_base:
            tables_list = knowledge_base.get("tables", [])
            for matched_tbl in section_plan.get("matched_tables", []):
                table_id = matched_tbl.get("extracted_table_id")
                if table_id:
                    # Find table in profile and populate markdown
                    for kb_tbl in tables_list:
                        if kb_tbl.get("table_id") == table_id:
                            matched_tbl["markdown"] = kb_tbl.get("markdown", "")
                            if not matched_tbl.get("description"):
                                matched_tbl["description"] = kb_tbl.get("description", "")
                            break

        # Validate through Pydantic
        try:
            plan = SectionPlan(**section_plan)
            return plan.model_dump()
        except Exception as e:
            logger.warning(f"  Section validation failed ({section_plan.get('title', '?')}): {e}")
            return section_plan

    # ─────────────────────────────────────────────────────────────────────────
    # Helper Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _find_profile_section(self, section_id: str, product_profile: Dict) -> Optional[Dict]:
        """Find profile section by section_id."""
        for sec in product_profile.get("sections", []):
            if sec.get("section_id") == section_id:
                return sec
        return None

    def _flatten_subsections(self, subsections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Recursively flatten nested profile hierarchy subsections into a flat list.

        Handles 3-4 level deep hierarchies where nested subsections embed number
        in title string (e.g., "3.2.1 Original Deployment").
        """
        result = []

        def _extract_num_title(entry: Dict) -> tuple:
            """Extract (subsection_number, clean_title) from profile entry."""
            num = entry.get("subsection_number", "")
            title = entry.get("title", "")
            if not num and title:
                # Title may embed number: "3.2.1 Some Title"
                parts = title.split(" ", 1)
                candidate = parts[0].rstrip(".")
                if candidate.replace(".", "").isdigit():
                    num = parts[0]
                    title = parts[1] if len(parts) > 1 else title
            return num, title

        def _walk(entries: List[Dict]) -> None:
            for entry in entries:
                num, title = _extract_num_title(entry)
                result.append({
                    "subsection_number": num,
                    "title": title,
                    "generation_notes": entry.get("notes", entry.get("generation_notes", "")),
                })
                children = entry.get("sub_subsections", [])
                if children:
                    _walk(children)

        _walk(subsections)
        return result

    def _get_available_images(
        self,
        image_inventory: Optional[Dict[str, Any]],
        assigned_image_ids: Set[str]
    ) -> List[Dict[str, Any]]:
        """Get list of images not yet assigned to sections."""
        if not image_inventory:
            return []

        all_images = image_inventory.get("images", [])
        return [
            img for img in all_images
            if img.get("image_id") not in assigned_image_ids
        ]

    def _get_available_tables(
        self,
        knowledge_base: Dict[str, Any],
        assigned_table_ids: Set[str]
    ) -> List[Dict[str, Any]]:
        """Get list of tables not yet assigned to sections."""
        all_tables = knowledge_base.get("tables", [])
        return [
            tbl for tbl in all_tables
            if tbl.get("table_id") not in assigned_table_ids
        ]
