"""
Global Planning Module

Builds the global planning context for section-by-section blueprint generation.
This includes:
- Section dependency graph (which sections depend on others)
- Conditional section hints (defers to Phase 2 LLM for evaluation)
- Global planning instructions from profile

IMPORTANT: NO hardcoded product-specific logic, NO regex pattern matching.
All conditional section evaluation is handled by Phase 2 LLM with full context.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict, deque

from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


def build_section_dependency_graph(profile_sections: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Extract section dependencies from profile sections.

    Builds a dependency graph where each section_id maps to a list of section_ids it depends on.

    Args:
        profile_sections: List of section dicts from product profile

    Returns:
        Dict mapping section_id to list of dependency section_ids
        Example: {
            "sec_solution_overview": [],
            "sec_capacity_sizing": ["sec_solution_overview"],
            "sec_ipfe_architecture": ["sec_deployment_architecture"],
        }
    """
    dependency_graph = {}

    for section in profile_sections:
        section_id = section.get("section_id", "")
        if not section_id:
            continue

        # Get explicit dependencies from generation config
        generation_config = section.get("generation", {})
        explicit_deps = generation_config.get("dependencies", [])

        # Also check if section title contains component name that requires architecture section
        # Example: "IPFE Features" depends on "IPFE Architecture"
        title = section.get("title", "").lower()
        implicit_deps = []

        # Component architecture dependencies
        # If this is a feature/detail section, it depends on the component architecture
        if "feature" in title or "routing" in title or "congestion" in title:
            # Look for component architecture sections
            for other_section in profile_sections:
                other_title = other_section.get("title", "").lower()
                other_id = other_section.get("section_id", "")

                # Check if component name appears in both titles
                # and the other section is an architecture section
                if "architecture" in other_title or "overview" in other_title:
                    # Extract potential component names (IPFE, DA-MP, NOAM, etc.)
                    # Simple heuristic: look for uppercase acronyms in current section title
                    for word in section.get("title", "").split():
                        if word.isupper() and len(word) >= 3:
                            if word.lower() in other_title:
                                implicit_deps.append(other_id)
                                break

        # Combine explicit and implicit dependencies
        all_deps = list(set(explicit_deps + implicit_deps))
        dependency_graph[section_id] = all_deps

    logger.info(f"Built dependency graph with {len(dependency_graph)} sections")
    return dependency_graph


def evaluate_global_conditionals(
    product_profile: Dict[str, Any],
    template_variables: Dict[str, str],
    knowledge_base: Dict[str, Any]
) -> Dict[str, Optional[bool]]:
    """
    Pre-evaluate simple conditional patterns to speed up section LLM calls.

    Analyzes profile conditional logic and template variables to provide hints about
    whether conditional sections should be included.

    Args:
        product_profile: Product profile dict (from ProductProfile.to_dict())
        template_variables: Extracted template variables (customer_name, nf_list, etc.)
        knowledge_base: DocumentKnowledgeBase dict

    Returns:
        Dict mapping section_id to inclusion hint:
        - True: strong hint to include
        - False: strong hint to exclude
        - None: let LLM decide (ambiguous or complex condition)

    Example:
        {
            "sec_executive_summary": False,  # VIL customer → exclude
            "sec_ipfe_architecture": True,   # IPFE in nf_list → include
            "sec_dsr_features": None,         # Complex condition, let LLM decide
        }
    """
    evaluations = {}

    customer_name = template_variables.get("customer_name", "").lower()
    nf_list_str = template_variables.get("nf_list", "").lower()
    nf_list = [nf.strip() for nf in nf_list_str.split(",")]

    # Get sections from profile
    sections = product_profile.get("sections", [])

    for section in sections:
        section_id = section.get("section_id", "")
        if not section_id:
            continue

        conditional = section.get("conditional", False)

        if not conditional:
            # Mandatory section - always include
            evaluations[section_id] = True
            continue

        # Conditional section - ALWAYS let Phase 2 LLM decide
        # NO regex matching, NO pattern matching, NO hardcoded logic
        #
        # The Phase 2 section-by-section LLM will evaluate condition_logic in full context:
        # - customer_name, nf_list, deployment_model from template_variables
        # - document_intelligence from document analyzer
        # - product_profile sections and metadata
        #
        # This ensures product-agnostic, context-aware conditional evaluation
        # without hardcoded product-specific patterns.
        evaluations[section_id] = None

    logger.info(f"Pre-evaluated {sum(1 for v in evaluations.values() if v is not None)}/{len(evaluations)} conditional sections")
    return evaluations


def build_global_context(product_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract global planning context from product profile.

    Args:
        product_profile: Product profile dict (from ProductProfile.to_dict())

    Returns:
        Dict with global planning instructions, section ordering rules, NF patterns, etc.
    """
    global_config = product_profile.get("global", {})

    return {
        "planning_instructions": global_config.get("planning_instructions", {}),
        "section_ordering_rules": global_config.get("section_ordering_rules", {}),
        "nf_architecture_pattern": global_config.get("nf_architecture_pattern", {}),
        "product_specific_sections": global_config.get("product_specific_sections", {}),
        "validation_rules": global_config.get("validation_rules", {}),
    }


def topological_sort_with_levels(
    dependency_graph: Dict[str, List[str]]
) -> List[List[str]]:
    """
    Perform topological sort on dependency graph and group sections into levels.

    Sections at the same level have no dependencies on each other and can be
    processed in parallel.

    Args:
        dependency_graph: Dict mapping section_id to list of dependency section_ids

    Returns:
        List of levels, where each level is a list of section_ids that can be
        processed in parallel.

        Example:
        [
            ["sec_introduction", "sec_references"],  # Level 0 (no deps)
            ["sec_solution_overview"],                # Level 1 (depends on level 0)
            ["sec_capacity_sizing", "sec_deployment"], # Level 2 (depends on level 1)
        ]

    Raises:
        ValueError: If circular dependency detected
    """
    # Build in-degree map (how many dependencies each section has)
    in_degree = defaultdict(int)
    adjacency_list = defaultdict(list)

    # Get all section IDs
    all_sections = set(dependency_graph.keys())
    for section_id, deps in dependency_graph.items():
        for dep in deps:
            adjacency_list[dep].append(section_id)
            in_degree[section_id] += 1
            all_sections.add(dep)

    # Initialize all sections with 0 in-degree
    for section_id in all_sections:
        if section_id not in in_degree:
            in_degree[section_id] = 0

    # Level-by-level processing
    levels = []
    queue = deque([sec for sec in all_sections if in_degree[sec] == 0])
    processed_count = 0

    while queue:
        # All sections in current queue form one level (can be processed in parallel)
        current_level = list(queue)
        levels.append(current_level)
        queue.clear()

        # Process current level
        for section_id in current_level:
            processed_count += 1
            # Reduce in-degree of all sections that depend on this one
            for dependent in adjacency_list[section_id]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    # Check for circular dependencies
    if processed_count != len(all_sections):
        remaining = [sec for sec in all_sections if in_degree[sec] > 0]
        raise ValueError(
            f"Circular dependency detected in section dependency graph. "
            f"Remaining sections: {remaining}"
        )

    logger.info(f"Topological sort: {len(levels)} levels, {len(all_sections)} sections total")
    for i, level in enumerate(levels):
        logger.info(f"  Level {i}: {len(level)} sections - {level}")

    return levels
