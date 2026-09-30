"""
Intent Interpreter - The Critical Innovation.

Converts free-form user prompts into structured instructions (StructuredIntent)
that drive the entire HLD generation pipeline. Runs ONCE upfront with a single
LLM call, making all downstream agents efficient.

Without this:
    User prompt → agents try to infer intent repeatedly → inconsistent decisions

With this:
    User prompt → Intent Interpreter (1 LLM call) → StructuredIntent → every agent
    follows the same instructions
"""

import json
import traceback
from typing import Dict, Any, List, Optional

from hld_generator.external.oci_adapters import OCILLMAdapter, OCIConfig
from hld_generator.shared.logging_config import setup_logger
from .schemas import (
    StructuredIntent,
    ComponentScope,
    ComponentScopeMode,
    StyleDirective,
    DataSourceMapping,
    CustomSection,
    GlobalConstraints,
)

logger = setup_logger(__name__)


class IntentInterpreter:
    """
    Converts free-form user prompt to structured instructions.

    LLM calls: 1 (upfront)

    Usage:
        interpreter = IntentInterpreter()
        intent = await interpreter.interpret(
            user_prompt="Include only BSF and SCP...",
            product="5G_SBA",
            available_components=["SCP", "BSF", "SEPP", ...],
            document_filenames=["5G_Architecture.pdf", "Network_Plan.xlsx"]
        )
    """

    def __init__(self, config: Optional[OCIConfig] = None):
        self.llm = OCILLMAdapter(config=config)
        logger.info("Intent Interpreter initialized")

    async def interpret(
        self,
        user_prompt: str,
        product: str,
        available_components: List[str],
        document_filenames: Optional[List[str]] = None,
    ) -> StructuredIntent:
        """
        Parse user intent into structured instructions.

        Args:
            user_prompt: Free-form user instructions
            product: Product identifier (e.g., "5G_SBA", "DSR")
            available_components: Components defined in the product profile
            document_filenames: Names of uploaded documents (for data source mapping)

        Returns:
            StructuredIntent with structured instructions
        """
        if not user_prompt or not user_prompt.strip():
            logger.info("No user prompt provided — returning default intent (full generation)")
            return StructuredIntent(
                intent_type="FULL_GENERATION",
                raw_user_prompt="",
            )

        logger.info(f"Interpreting user intent for product={product}")
        logger.info(f"  User prompt: {user_prompt[:200]}...")
        logger.info(f"  Available components: {available_components}")
        logger.info(f"  Documents: {document_filenames}")

        prompt = self._build_prompt(
            user_prompt, product, available_components, document_filenames
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured instruction generator for an HLD "
                    "(High-Level Design) generation system. You convert free-form "
                    "user requests into precise JSON instructions. Be exact — "
                    "extract only what the user explicitly or implicitly requests. "
                    "Return valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        raw_response = None
        raw_json = None
        parsed = None

        try:
            response = await self.llm.create_chat_completion(
                messages=messages,
                max_tokens=2000,
            )
            raw_response = response

            raw_json = self._extract_json_from_response(response)
            parsed = json.loads(raw_json)

            # Ensure parsed is a dict (LLM might return null or non-dict)
            if not isinstance(parsed, dict):
                raise ValueError(f"LLM returned non-dict response: {type(parsed)}")

            # CRITICAL FIX: Clean null values from parsed JSON before validation
            parsed = self._clean_null_values(parsed)

            logger.debug(f"Parsed intent structure: {json.dumps(parsed, indent=2)[:500]}")

            intent = self._validate_and_enrich(
                parsed, available_components, user_prompt
            )

            logger.info(f"Intent interpreted successfully:")
            logger.info(f"  Type: {intent.intent_type}")
            logger.info(f"  Component scope: {intent.component_scope.mode.value}")
            logger.info(f"  Include: {intent.component_scope.include}")
            logger.info(f"  Style directives: {list(intent.style_directives.keys())}")
            logger.info(f"  Data sources: {list(intent.data_source_mappings.keys())}")
            logger.info(f"  Custom sections: {len(intent.custom_sections)}")

            return intent

        except Exception as e:
            # CRITICAL FIX: Comprehensive error logging for debugging
            logger.error(f"Intent interpretation failed: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")

            # Log raw response (truncated)
            if raw_response:
                logger.error(f"Raw LLM response (first 1000 chars):\n{str(raw_response)[:1000]}")
            else:
                logger.error("Raw LLM response: None (LLM call may have failed)")

            # Log extracted JSON (truncated)
            if raw_json:
                logger.error(f"Extracted JSON (first 1000 chars):\n{raw_json[:1000]}")
            else:
                logger.error("Extracted JSON: None (extraction may have failed)")

            # Log parsed structure if available
            if parsed is not None:
                try:
                    logger.error(f"Parsed structure:\n{json.dumps(parsed, indent=2)[:1000]}")
                except:
                    logger.error(f"Parsed structure (repr): {repr(parsed)[:500]}")
            else:
                logger.error("Parsed structure: None (JSON parsing may have failed)")

            logger.warning("⚠️  USER INSTRUCTIONS WILL BE IGNORED - Falling back to default intent (full generation)")
            logger.warning("⚠️  All components will be included, no custom filtering applied")

            return StructuredIntent(
                intent_type="FULL_GENERATION",
                raw_user_prompt=user_prompt,
            )

    def _build_prompt(
        self,
        user_prompt: str,
        product: str,
        available_components: List[str],
        document_filenames: Optional[List[str]] = None,
    ) -> str:
        """Build the LLM prompt for intent interpretation."""
        docs_section = ""
        if document_filenames:
            docs_list = "\n".join(f"  - {f}" for f in document_filenames)
            docs_section = f"\nUploaded documents:\n{docs_list}\n"

        return f"""Analyse the user's request and convert it to structured JSON instructions.

User's request:
\"{user_prompt}\"

Product: {product}
Available components in this product: {json.dumps(available_components)}
{docs_section}
Extract the following (omit fields that don't apply):

1. **intent_type**: One of:
   - "FULL_GENERATION" — generate complete HLD (default if no specific scope)
   - "SELECTIVE_GENERATION" — user wants specific components only
   - "UPDATE" — modify an existing HLD
   - "REGENERATE" — redo specific sections

2. **component_scope**: How to handle component selection
   - "mode": "EXCLUSIVE" (only listed) | "INCLUSIVE" (all minus excluded) | "EMPHASIS" (all, focus on listed)
   - "include": list of component names from the available list above
   - "exclude": list of component names to skip
   - "preserve_structural": true (keep mandatory sections like intro/deployment) — almost always true

   INTELLIGENT INFERENCE RULES:
   - "Include only X and Y" → EXCLUSIVE mode, include: [X, Y]
   - "Skip Z" or "No Z" or "Omit Z" → INCLUSIVE mode, exclude: [Z]
   - "Focus on X" or "Emphasize X" → EMPHASIS mode, include: [X]

3. **style_directives**: Per-section style overrides (keyed by section topic, not ID)
   For each section the user mentions style preferences:
   - "detail_level": "high-level" | "detailed" | "comprehensive"
   - "max_subsections": integer
   - "estimated_tokens": rough token budget (500=brief, 2000=detailed, 3500=comprehensive)
   - "custom_instructions": any specific instructions

   ADVANCED PATTERN RECOGNITION:
   Section Emphasis (map to style_directives):
   - "Focus on capacity sizing" → capacity_sizing: {{detail_level: "comprehensive", estimated_tokens: 3500}}
   - "Brief deployment overview" → deployment: {{detail_level: "high-level", estimated_tokens: 500}}
   - "Detailed network integration" → network_integration: {{detail_level: "detailed", estimated_tokens: 2500}}
   - "Comprehensive HA analysis" → high_availability: {{detail_level: "comprehensive", estimated_tokens: 3000}}

   Section Removal (map to exclusion):
   - "Skip BoQ section" → Mark BoQ for exclusion
   - "No appendices" → Exclude all appendix sections
   - "Omit licensing details" → Exclude licensing/commercial sections

   Detail Level Inference from Adjectives:
   - "Brief" / "Short" / "Quick" → detail_level: "high-level", ~500 tokens
   - "Detailed" / "Thorough" → detail_level: "detailed", ~2000 tokens
   - "Comprehensive" / "In-depth" / "Extensive" → detail_level: "comprehensive", ~3500 tokens

4. **data_source_mappings**: When user references specific data sources
   Keyed by data type (e.g., "ip_addresses", "capacity_data"):
   - "source": filename from uploaded documents
   - "sheet": specific sheet/table name if mentioned
   - "priority": "HIGH" | "MEDIUM" | "LOW"

   Examples:
   - "Use IP addresses from network_plan.xlsx" → ip_addresses: {{source: "network_plan.xlsx", priority: "HIGH"}}
   - "Capacity data from sizing_sheet.csv" → capacity_data: {{source: "sizing_sheet.csv", priority: "HIGH"}}

5. **custom_sections**: Sections user wants that aren't in the standard profile
   - "section_id": generated ID (e.g., "sec_migration_strategy")
   - "title": section title
   - "insert_after": section topic it should follow (infer logical position)
   - "generation_strategy": "hybrid" (default)

   Examples:
   - "Add section on Microsoft Teams integration" → custom_sections: [{{
       section_id: "sec_microsoft_teams_integration",
       title: "Microsoft Teams Integration",
       insert_after: "deployment" (infer after deployment architecture),
       generation_strategy: "hybrid"
     }}]
   - "Include migration strategy" → custom_sections: [{{
       section_id: "sec_migration_strategy",
       title: "Migration Strategy",
       insert_after: "solution_overview" (logical position),
       generation_strategy: "hybrid"
     }}]

6. **global_constraints**: Overall constraints
   - "max_total_tokens": if user mentions page/size limits (estimate: 500 tokens ≈ 1 page)
   - "preferred_diagram_style": "architecture_focused" | "detailed" | "minimal"

   Examples:
   - "Keep it under 50 pages" → max_total_tokens: 25000
   - "Detailed architecture diagrams" → preferred_diagram_style: "detailed"
   - "Minimal diagrams" → preferred_diagram_style: "minimal"

7. **template_variable_overrides**: Extract if user explicitly provides template variable values
   Examples to recognize:
   - "Customer: Saudi Telecom Company" → {{"customer_name": "Saudi Telecom Company"}}
   - "Customer name: STC" → {{"customer_name": "STC"}}
   - "Project: Sessions Upgrade 2026" → {{"project_name": "Sessions Upgrade 2026"}}
   - "for Vodafone deployment" → {{"customer_name": "Vodafone"}}
   - "Version: Release 24.1" → {{"product_version": "Release 24.1"}}

   Supported keys: customer_name, project_name, site_names, deployment_model, product_version, platform_version

   IMPORTANT:
   - ONLY extract if explicitly stated by user
   - DO NOT invent or expand abbreviations (e.g., "STC" stays "STC", don't expand unless user writes it)
   - Preserve exact capitalization and spacing from user input

CRITICAL REASONING INSTRUCTIONS:
- Make intelligent inferences - don't just extract literal patterns
- If user says "focus on HA", boost token budget for ALL high-availability-related sections
- If user says "skip appendices", exclude all sections with "appendix" in title
- If user mentions a component multiple times, infer EMPHASIS mode
- If user requests custom section, infer logical insertion point based on section topic

Return ONLY valid JSON matching this schema.
IMPORTANT:
- OMIT fields entirely if they don't apply (do NOT use null values)
- Arrays must NOT contain null elements
- Only include fields the user explicitly or implicitly requested

Example of correct response:
{{
  "intent_type": "SELECTIVE_GENERATION",
  "component_scope": {{
    "mode": "EXCLUSIVE",
    "include": ["BSF", "SCP"]
  }}
}}

Example of WRONG response (do not do this):
{{
  "intent_type": "SELECTIVE_GENERATION",
  "component_scope": {{
    "mode": "EXCLUSIVE",
    "include": [null, "BSF", null]
  }},
  "style_directives": null
}}"""

    def _validate_and_enrich(
        self,
        parsed: Dict[str, Any],
        available_components: List[str],
        user_prompt: str,
    ) -> StructuredIntent:
        """
        Validate LLM output and build a typed StructuredIntent.

        Ensures:
        - All included components actually exist in the profile
        - Defaults are filled for missing fields
        - Original user prompt is preserved
        """
        # --- Component scope ---
        scope_raw = parsed.get("component_scope")

        # CRITICAL FIX: Defensive null handling throughout
        if scope_raw and isinstance(scope_raw, dict):
            # Handle both missing keys and null values from LLM
            mode_str = (scope_raw.get("mode") or "INCLUSIVE").upper()
            try:
                mode = ComponentScopeMode(mode_str)
            except ValueError:
                logger.warning(f"Invalid component scope mode '{mode_str}', defaulting to INCLUSIVE")
                mode = ComponentScopeMode.INCLUSIVE

            # Filter to only valid components (case-insensitive match)
            component_map = {c.upper(): c for c in available_components if c}

            # CRITICAL FIX: Explicitly filter None before calling .upper()
            include_raw = scope_raw.get("include") or []
            include = [
                component_map[c.upper()]
                for c in include_raw
                if c is not None and isinstance(c, str) and c.strip() and c.upper() in component_map
            ]

            exclude_raw = scope_raw.get("exclude") or []
            exclude = [
                component_map[c.upper()]
                for c in exclude_raw
                if c is not None and isinstance(c, str) and c.strip() and c.upper() in component_map
            ]

            logger.debug(f"Component filtering: include_raw={include_raw} → include={include}")
            logger.debug(f"Component filtering: exclude_raw={exclude_raw} → exclude={exclude}")

            component_scope = ComponentScope(
                mode=mode,
                include=include,
                exclude=exclude,
                preserve_structural=scope_raw.get("preserve_structural", True),
            )
        else:
            component_scope = ComponentScope()

        # --- Style directives ---
        style_directives = {}
        # CRITICAL FIX: Defensive type checking before .items()
        style_raw = parsed.get("style_directives")
        if style_raw is not None and isinstance(style_raw, dict):
            for key, directive in style_raw.items():
                if directive and isinstance(directive, dict):
                    style_directives[key] = StyleDirective(
                        detail_level=directive.get("detail_level"),
                        max_subsections=directive.get("max_subsections"),
                        estimated_tokens=directive.get("estimated_tokens"),
                        custom_instructions=directive.get("custom_instructions"),
                    )

        # --- Data source mappings ---
        data_source_mappings = {}
        # CRITICAL FIX: Defensive type checking before .items()
        datasources_raw = parsed.get("data_source_mappings")
        if datasources_raw is not None and isinstance(datasources_raw, dict):
            for key, mapping in datasources_raw.items():
                if mapping and isinstance(mapping, dict):
                    source = mapping.get("source", "")
                    if source:
                        data_source_mappings[key] = DataSourceMapping(
                            source=source,
                            sheet=mapping.get("sheet"),
                            priority=mapping.get("priority", "MEDIUM"),
                        )

        # --- Custom sections ---
        custom_sections = []
        # CRITICAL FIX: Defensive array iteration with None filtering
        custom_raw = parsed.get("custom_sections")
        if custom_raw is not None and isinstance(custom_raw, list):
            for sec in custom_raw:
                if sec is not None and isinstance(sec, dict) and sec.get("title"):
                    section_id = sec.get("section_id") or _slugify(sec["title"])
                    custom_sections.append(CustomSection(
                        section_id=section_id,
                        title=sec["title"],
                        insert_after=sec.get("insert_after"),
                        generation_strategy=sec.get("generation_strategy", "hybrid"),
                    ))

        # --- Global constraints ---
        gc_raw = parsed.get("global_constraints")
        if gc_raw is not None and isinstance(gc_raw, dict):
            global_constraints = GlobalConstraints(
                max_total_tokens=gc_raw.get("max_total_tokens"),
                preferred_diagram_style=gc_raw.get("preferred_diagram_style"),
            )
        else:
            global_constraints = GlobalConstraints()

        # --- Template variable overrides ---
        template_variable_overrides = {}
        tv_raw = parsed.get("template_variable_overrides")
        if tv_raw is not None and isinstance(tv_raw, dict):
            # Filter to only valid string values
            for key, value in tv_raw.items():
                if value is not None and isinstance(value, str) and value.strip():
                    template_variable_overrides[key] = value.strip()

            if template_variable_overrides:
                logger.info(f"Template variable overrides extracted: {list(template_variable_overrides.keys())}")

        # --- Intent type ---
        intent_type = parsed.get("intent_type", "FULL_GENERATION")
        if intent_type not in (
            "FULL_GENERATION", "SELECTIVE_GENERATION", "UPDATE", "REGENERATE"
        ):
            intent_type = "FULL_GENERATION"

        # Auto-detect selective if components are specified
        if (
            intent_type == "FULL_GENERATION"
            and component_scope.mode == ComponentScopeMode.EXCLUSIVE
            and component_scope.include
        ):
            intent_type = "SELECTIVE_GENERATION"

        return StructuredIntent(
            intent_type=intent_type,
            component_scope=component_scope,
            style_directives=style_directives,
            data_source_mappings=data_source_mappings,
            custom_sections=custom_sections,
            global_constraints=global_constraints,
            template_variable_overrides=template_variable_overrides,
            raw_user_prompt=user_prompt,
        )

    @staticmethod
    def _clean_null_values(parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean null/None values from parsed JSON that LLM may have included.

        This is a defensive fix for OCI LLM returning JSON with null values
        despite being told to omit fields.

        Handles:
        - null in arrays: [null, "IPFE", null] → ["IPFE"]
        - null as dict values: {"key": null} → {}
        - Recursively cleans nested structures
        """
        if not isinstance(parsed, dict):
            return parsed

        cleaned = {}

        for key, value in parsed.items():
            if value is None:
                # Skip null top-level fields
                continue

            elif isinstance(value, list):
                # Filter null from arrays and recursively clean dict elements
                cleaned_list = []
                for item in value:
                    if item is None:
                        continue  # Skip null array elements
                    elif isinstance(item, dict):
                        cleaned_list.append(IntentInterpreter._clean_null_values(item))
                    else:
                        cleaned_list.append(item)
                if cleaned_list:  # Only include non-empty arrays
                    cleaned[key] = cleaned_list

            elif isinstance(value, dict):
                # Recursively clean nested dicts
                cleaned_dict = IntentInterpreter._clean_null_values(value)
                if cleaned_dict:  # Only include non-empty dicts
                    cleaned[key] = cleaned_dict

            else:
                # Keep primitive values (str, int, bool, etc.)
                cleaned[key] = value

        return cleaned

    @staticmethod
    def _extract_json_from_response(response_text: str) -> str:
        """Strip markdown code fences from LLM response."""
        text = response_text.strip()
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


def _slugify(title: str) -> str:
    """Convert a title to a section_id slug."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return f"sec_{slug}"
