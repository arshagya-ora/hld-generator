"""
Phase 3: Data Assessment

Evaluates data completeness for each planned section by checking the
DocumentKnowledgeBase and ImageInventory against what each section requires.
Identifies critical gaps and generates clarification questions.

Uses direct LLM calls for intelligent gap analysis.
"""

import json
import logging
from typing import Dict, Any, List, Optional

from hld_generator.agents.blueprint.state.models import Clarification
from hld_generator.shared.llm_wrapper import OCILLMWrapper
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)

# Thresholds for data completeness scoring
COMPLETENESS_THRESHOLD = 0.9   # Sections scoring >= this are considered "fully complete"
FALLBACK_COMPLETENESS = 0.8    # Default completeness when LLM assessment fails


DATA_ASSESSMENT_SYSTEM_PROMPT = """You are a Data Assessment Agent for telecom HLD document generation.

Your task: Given planned sections and the available project data, assess data completeness for each section and identify critical gaps.

## Your Responsibilities:
1. For each section, evaluate whether the DocumentKnowledgeBase has enough data to generate it.
2. Score data_completeness from 0.0 (no data) to 1.0 (fully complete).
3. List specific missing_data items for each section.
4. List assumptions that would need to be made if data is missing.
5. Identify critical gaps that require user clarification before generation can proceed.

## Rules for Clarifications:
- "critical" priority: Data MUST be obtained (e.g., missing IP addresses for network config, missing hardware specs for BOQ)
- "high" priority: Strongly recommended but generation can proceed with assumptions
- "medium" priority: Would improve quality but can use defaults
- "low" priority: Nice to have
- NEVER mark something as critical if a reasonable assumption can be made
- IP addresses, hardware specs, and peer configurations are ALWAYS critical if missing (never hallucinate these)

## Output Format:
Return a JSON object:
{
  "section_assessments": [
    {
      "section_id": "sec_xxx",
      "data_completeness": 0.0-1.0,
      "missing_data": ["item1", "item2"],
      "assumptions": ["assumption1"],
      "assessment_notes": "explanation"
    }
  ],
  "clarifications": [
    {
      "priority": "critical|high|medium|low",
      "question": "What is X?",
      "context": "Needed for section Y because Z",
      "impact_if_skipped": "Will use placeholder / default / omit section",
      "can_skip": true/false,
      "suggested_format": "e.g. IP address in CIDR notation"
    }
  ],
  "overall_completeness": 0.0-1.0,
  "can_proceed": true/false
}

Return ONLY the JSON, no additional text."""


class DataAssessmentPhase:
    """
    Phase 3: Data completeness assessment.

    Checks each planned section against available data and identifies
    gaps that need user clarification.
    """

    def __init__(self, llm: OCILLMWrapper):
        self.llm = llm

    async def execute(
        self,
        planned_sections: List[Dict[str, Any]],
        knowledge_base: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]] = None,
        product_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute Phase 3: Data Assessment.

        Args:
            planned_sections: Section plans from Phase 2
            knowledge_base: DocumentKnowledgeBase as dict
            image_inventory: ImageInventory as dict (optional)
            product_profile: Loaded ProductProfile as dict (for no-hallucination rules)

        Returns:
            Dict with:
              - section_assessments: per-section data completeness updates
              - clarifications: List[dict] (Clarification dicts)
              - can_proceed: bool
              - data_assessment_summary: dict
        """
        logger.info("Phase 3: Data Assessment")

        # Build assessment prompt
        user_prompt = self._build_assessment_prompt(
            planned_sections=planned_sections,
            knowledge_base=knowledge_base,
            image_inventory=image_inventory,
            product_profile=product_profile,
        )

        # Call LLM for assessment
        assessment = await self._call_llm_for_assessment(user_prompt)

        # Process results
        section_assessments = assessment.get("section_assessments", [])
        clarifications = assessment.get("clarifications", [])
        overall_completeness = assessment.get("overall_completeness", 1.0)
        can_proceed = assessment.get("can_proceed", True)

        # Validate clarifications via Pydantic
        validated_clarifications = []
        for c in clarifications:
            try:
                clarification = Clarification(**c)
                validated_clarifications.append(clarification.model_dump())
            except Exception as e:
                logger.warning(f"  Clarification validation failed: {e}")
                validated_clarifications.append(c)

        # Update sections with assessment data
        updated_sections = self._merge_assessments(planned_sections, section_assessments)

        # Build summary
        summary = {
            "overall_completeness": overall_completeness,
            "total_sections": len(planned_sections),
            "sections_fully_complete": sum(
                1 for a in section_assessments
                if a.get("data_completeness", 1.0) >= COMPLETENESS_THRESHOLD
            ),
            "sections_with_gaps": sum(
                1 for a in section_assessments
                if a.get("data_completeness", 1.0) < COMPLETENESS_THRESHOLD
            ),
            "critical_clarifications": sum(
                1 for c in validated_clarifications if c.get("priority") == "critical"
            ),
            "total_clarifications": len(validated_clarifications),
        }

        logger.info(
            f"  Overall completeness: {overall_completeness:.0%}, "
            f"can_proceed: {can_proceed}, "
            f"clarifications: {len(validated_clarifications)}"
        )

        return {
            "planned_sections": updated_sections,
            "clarifications": validated_clarifications,
            "can_proceed": can_proceed,
            "data_assessment_summary": summary,
        }

    def _build_assessment_prompt(
        self,
        planned_sections: List[Dict[str, Any]],
        knowledge_base: Dict[str, Any],
        image_inventory: Optional[Dict[str, Any]] = None,
        product_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the prompt for data assessment LLM call."""

        # Compact section summary (don't send full RAG queries etc.)
        section_summary = []
        for s in planned_sections:
            section_summary.append({
                "section_id": s.get("section_id"),
                "title": s.get("title"),
                "generation_strategy": s.get("generation_strategy"),
                "rag_ratio": s.get("rag_ratio", 0),
                "tables": [t.get("table_id") for t in s.get("tables", [])],
                "diagrams": [d.get("figure_reference") for d in s.get("diagrams", [])],
            })

        # Available data keys summary
        available_data = {
            "document_intelligence": list(knowledge_base.get("document_intelligence", {}).keys()),
            "project_overview_populated": bool(knowledge_base.get("project_overview")),
            "products_count": len(knowledge_base.get("products", {})),
            "product_names": list(knowledge_base.get("products", {}).keys()),
            "sites_count": len(knowledge_base.get("sites", [])),
            "has_capacity_data": knowledge_base.get("capacity_and_sizing") is not None,
            "has_network_data": bool(knowledge_base.get("network_and_integration", {})),
            "has_infrastructure_data": bool(knowledge_base.get("infrastructure", {})),
            "diagrams_count": len(knowledge_base.get("diagrams", [])),
            "tables_count": len(knowledge_base.get("tables", [])),
            "special_notes_count": len(knowledge_base.get("special_notes", [])),
        }

        # Image inventory summary
        image_count = 0
        image_types = []
        if image_inventory:
            images = image_inventory.get("images", [])
            image_count = len(images)
            for img in images:
                vision = img.get("vision_analysis")
                if vision:
                    # Handle both dict and Pydantic model instances
                    if isinstance(vision, dict):
                        image_types.append(vision.get("type", "unknown"))
                    elif hasattr(vision, 'type'):  # VisionAnalysis model instance
                        image_types.append(vision.type if vision.type else "unknown")
                    else:
                        image_types.append("unknown")

        # No-hallucination rules from profile
        no_hallucinate_rules = []
        if product_profile:
            rules = product_profile.get("section_rules", {})
            critical_rules = rules.get("critical_rules", rules.get("validation_rules", {}))
            if isinstance(critical_rules, dict):
                no_hallucinate_rules = critical_rules.get("never_hallucinate", [])
            elif isinstance(critical_rules, list):
                no_hallucinate_rules = critical_rules

        prompt = f"""## Planned Sections:
{json.dumps(section_summary, indent=2)}

## Available Data Summary:
{json.dumps(available_data, indent=2)}

## Raw Project Data:
{json.dumps(knowledge_base, indent=2, default=str)}

## Available Images: {image_count} images
Image types: {image_types}

## NEVER HALLUCINATE (critical extraction-only data):
{json.dumps(no_hallucinate_rules, indent=2)}

Assess data completeness for each section and identify gaps requiring clarification."""

        return prompt

    async def _call_llm_for_assessment(
        self, user_prompt: str
    ) -> Dict[str, Any]:
        """Call OCI GenAI for data assessment."""
        logger.info("  Calling OCI GenAI for data assessment...")

        try:
            result = await self.llm.chat_json(
                system_prompt=DATA_ASSESSMENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=4096,
                temperature=0.2,
            )

            if isinstance(result, dict):
                return result

        except Exception as e:
            logger.error(f"  Data assessment LLM call failed: {e}")

        # Fallback: optimistic assessment (assume all data is available)
        logger.warning("  Using fallback optimistic assessment")
        return {
            "section_assessments": [],
            "clarifications": [],
            "overall_completeness": FALLBACK_COMPLETENESS,
            "can_proceed": True,
        }

    def _merge_assessments(
        self,
        planned_sections: List[Dict[str, Any]],
        assessments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge LLM assessments back into section plans."""
        # Build lookup by section_id
        assessment_map = {
            a["section_id"]: a for a in assessments if "section_id" in a
        }

        updated = []
        for section in planned_sections:
            sid = section.get("section_id", "")
            if sid in assessment_map:
                a = assessment_map[sid]
                section["data_completeness"] = a.get("data_completeness", section.get("data_completeness", 1.0))
                section["missing_data"] = a.get("missing_data", section.get("missing_data", []))
                section["assumptions"] = a.get("assumptions", section.get("assumptions", []))
            updated.append(section)

        return updated
