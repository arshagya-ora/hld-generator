"""
Intent-based section filtering for Blueprint Agent.

Deterministic filtering of profile sections based on StructuredIntent:
- Component scope (EXCLUSIVE/INCLUSIVE/EMPHASIS mode)
- Style directives (detail_level, max_subsections, estimated_tokens)
- Custom section insertion
"""

import logging
import copy
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def filter_sections_by_intent(
    profile_sections: List[Dict[str, Any]],
    structured_intent: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Filter and annotate profile sections based on structured intent.

    This is a DETERMINISTIC operation — no LLM calls. It pre-filters
    the profile sections before they reach the LLM planning phase.

    Args:
        profile_sections: Full list of profile section definitions
        structured_intent: StructuredIntent dict from Intent Interpreter

    Returns:
        Filtered and annotated list of profile sections
    """
    if not structured_intent:
        return profile_sections

    component_scope = structured_intent.get("component_scope", {})
    mode = component_scope.get("mode", "INCLUSIVE")
    include_components = [c.lower() for c in component_scope.get("include", [])]
    exclude_components = [c.lower() for c in component_scope.get("exclude", [])]
    preserve_structural = component_scope.get("preserve_structural", True)

    # Only filter if there are actual component constraints
    has_constraints = bool(include_components or exclude_components)
    if not has_constraints:
        # No filtering — annotate with emphasis if EMPHASIS mode
        return _apply_style_directives(profile_sections, structured_intent)

    filtered = []

    for section in profile_sections:
        section = copy.deepcopy(section)
        section_id = section.get("section_id", "")

        # Determine if section is structural (mandatory regardless of component scope)
        is_structural = _is_structural_section(section)

        if preserve_structural and is_structural:
            filtered.append(section)
            continue

        # Get component associations for this section
        section_components = _get_section_components(section)

        if mode == "EXCLUSIVE":
            # Only include sections that match listed components
            if _components_match(section_components, include_components):
                filtered.append(section)
            else:
                logger.info(
                    f"  Intent filter: EXCLUDED {section_id} "
                    f"(components {section_components} not in {include_components})"
                )
        elif mode == "INCLUSIVE":
            # Include all except excluded components
            if not _components_match(section_components, exclude_components):
                filtered.append(section)
            else:
                logger.info(
                    f"  Intent filter: EXCLUDED {section_id} "
                    f"(components {section_components} in exclude list {exclude_components})"
                )
        elif mode == "EMPHASIS":
            # Include all, mark emphasis
            if _components_match(section_components, include_components):
                section["_emphasized"] = True
            filtered.append(section)

    logger.info(
        f"  Intent filter: {len(profile_sections)} → {len(filtered)} sections "
        f"(mode={mode}, include={include_components}, exclude={exclude_components})"
    )

    return _apply_style_directives(filtered, structured_intent)


def insert_custom_sections(
    profile_sections: List[Dict[str, Any]],
    structured_intent: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Insert custom sections from structured intent into the section list.

    Custom sections are defined by the user and don't exist in the profile.
    They get inserted at the position specified by insert_after.

    Args:
        profile_sections: Filtered profile sections
        structured_intent: StructuredIntent dict

    Returns:
        Sections with custom sections inserted
    """
    if not structured_intent:
        return profile_sections

    custom_sections = structured_intent.get("custom_sections", [])
    if not custom_sections:
        return profile_sections

    result = list(profile_sections)

    for custom in custom_sections:
        insert_after = custom.get("insert_after")
        custom_section = {
            "section_id": custom["section_id"],
            "title": custom["title"],
            "conditional": False,
            "category": "custom",
            "generation": {
                "strategy": custom.get("generation_strategy", "hybrid"),
                "template_ratio": 30,
                "rag_ratio": 70,
                "estimated_tokens": 1000,
                "dependencies": [],
            },
            "rag_queries": [],
            "hierarchy": {"subsections": []},
            "_custom": True,
        }

        if insert_after:
            insert_idx = next(
                (i for i, s in enumerate(result) if s.get("section_id") == insert_after),
                len(result) - 1,
            )
            result.insert(insert_idx + 1, custom_section)
        else:
            # Append before appendices
            append_idx = next(
                (i for i, s in enumerate(result) if s.get("section_id", "").startswith("sec_appendix")),
                len(result),
            )
            result.insert(append_idx, custom_section)

        logger.info(
            f"  Intent filter: INSERTED custom section '{custom['title']}' "
            f"(after {insert_after or 'end'})"
        )

    return result


def build_intent_context_for_prompt(structured_intent: Dict[str, Any]) -> str:
    """
    Build a concise intent context string to inject into section planning prompts.

    This gives the LLM awareness of the user's intent without overwhelming the prompt.

    Args:
        structured_intent: StructuredIntent dict

    Returns:
        Formatted string for LLM prompt injection
    """
    if not structured_intent:
        return ""

    lines = []
    lines.append("## User Intent Directives")
    lines.append("")

    intent_type = structured_intent.get("intent_type", "FULL_GENERATION")
    lines.append(f"Intent type: {intent_type}")

    # Component scope summary
    scope = structured_intent.get("component_scope", {})
    mode = scope.get("mode", "INCLUSIVE")
    if mode == "EXCLUSIVE":
        lines.append(f"Component focus: ONLY {scope.get('include', [])}")
    elif scope.get("exclude"):
        lines.append(f"Component scope: Excluding {scope.get('exclude', [])}")

    # Data source mappings
    data_sources = structured_intent.get("data_source_mappings", {})
    if data_sources:
        lines.append("")
        lines.append("Data source preferences:")
        for data_type, mapping in data_sources.items():
            if isinstance(mapping, dict):
                source = mapping.get("source", "")
                lines.append(f"  - {data_type}: use '{source}'")
            else:
                lines.append(f"  - {data_type}: {mapping}")

    # Global constraints
    constraints = structured_intent.get("global_constraints", {})
    if constraints.get("max_total_tokens"):
        lines.append(f"Token budget: {constraints['max_total_tokens']} total")

    # Raw prompt for context
    raw_prompt = structured_intent.get("raw_user_prompt", "")
    if raw_prompt:
        lines.append("")
        lines.append(f"User request: {raw_prompt[:300]}")

    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Internal Helpers
# ─────────────────────────────────────────────────────────────────────────

def _is_structural_section(section: Dict[str, Any]) -> bool:
    """
    Determine if a section is structural (mandatory regardless of component scope).

    Structural sections: introduction, deployment overview, capacity overview,
    appendices, executive summary, etc.
    """
    section_id = section.get("section_id", "").lower()
    category = section.get("category", "").lower()
    title = section.get("title", "").lower()

    # Explicit structural categories
    if category in ("structural", "mandatory"):
        return True

    # Known structural section IDs
    structural_ids = {
        "sec_introduction",
        "sec_executive_summary",
        "sec_document_history",
        "sec_scope",
        "sec_abbreviations",
    }
    if section_id in structural_ids:
        return True

    # Appendices are always structural
    if section_id.startswith("sec_appendix"):
        return True

    # Sections with numbers 1.x are usually structural (intro, scope, etc.)
    section_number = str(section.get("section_number", ""))
    if section_number.startswith("1"):
        return True

    # Title-based detection
    structural_titles = [
        "introduction", "scope", "abbreviation", "acronym",
        "reference", "appendix", "document history", "executive summary",
    ]
    if any(st in title for st in structural_titles):
        return True

    return False


def _get_section_components(section: Dict[str, Any]) -> List[str]:
    """
    Extract component associations from a profile section.

    Components can be specified via:
    - section.component (explicit)
    - section.hierarchy.subsections with component references
    - section.rag_queries mentioning component names
    """
    components = []

    # Direct component field
    component = section.get("component", "")
    if component:
        components.append(component.lower())

    # Check section title for component names
    title = section.get("title", "").lower()

    # Check subsections for component references
    hierarchy = section.get("hierarchy", {})
    for sub in hierarchy.get("subsections", []):
        sub_component = sub.get("component", "")
        if sub_component:
            components.append(sub_component.lower())

    return list(set(components))


def _components_match(
    section_components: List[str],
    target_components: List[str],
) -> bool:
    """
    Check if any section component matches the target list.

    If section has no components, it's treated as generic (matches nothing).
    """
    if not section_components:
        return False

    return any(
        sc in target_components or any(tc in sc or sc in tc for tc in target_components)
        for sc in section_components
    )


def _apply_style_directives(
    sections: List[Dict[str, Any]],
    structured_intent: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Annotate sections with style directive overrides from intent.

    These annotations are consumed by _validate_and_enrich_section() to
    override profile defaults.

    Supports fuzzy keyword matching:
    - "capacity" matches "sec_capacity_sizing" or "Capacity and Sizing"
    - "deployment" matches "sec_deployment_architecture"
    - "network" matches "sec_network_integration"
    """
    style_directives = structured_intent.get("style_directives", {})
    if not style_directives:
        return sections

    for section in sections:
        section_id = section.get("section_id", "")
        section_title = section.get("title", "").lower()

        # Try exact match first (section_id or title)
        directive = None
        if section_id in style_directives:
            directive = style_directives[section_id]
        elif section_title in style_directives:
            directive = style_directives[section_title]
        else:
            # Fuzzy keyword matching
            for key, dir_data in style_directives.items():
                key_lower = key.lower()
                # Match if key is substring of section_id or title, or vice versa
                if (key_lower in section_id.lower() or
                    key_lower in section_title or
                    section_id.lower() in key_lower or
                    any(word in key_lower for word in section_title.split() if len(word) > 4)):
                    directive = dir_data
                    logger.info(
                        f"  Intent filter: Fuzzy matched '{key}' to section '{section_id}' ({section_title})"
                    )
                    break

        if directive and isinstance(directive, dict):
            section["_style_override"] = directive
            logger.info(
                f"  Intent filter: Style override for {section_id}: {directive}"
            )

    return sections
