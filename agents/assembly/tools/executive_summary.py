"""
Executive Summary generator using LLM.

Synthesizes entire document into a concise executive summary.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ExecutiveSummaryGenerator:
    """Generates executive summary using LLM."""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def generate_executive_summary(
        self,
        sections: List[Dict[str, Any]],
        blueprint: Dict[str, Any],
        project_context: Dict[str, Any],
    ) -> str:
        """
        Generate executive summary from all sections.

        Args:
            sections: List of GeneratedSection dicts
            blueprint: Blueprint output with project metadata
            project_context: Document knowledge base

        Returns:
            Markdown-formatted executive summary
        """
        logger.info("Generating executive summary using LLM...")

        # Extract key information from sections
        section_summaries = self._extract_section_summaries(sections)

        # Extract project highlights
        project_highlights = self._extract_project_highlights(blueprint, project_context)

        # Build prompt for LLM
        prompt = self._build_executive_summary_prompt(
            section_summaries,
            project_highlights,
        )

        # Call LLM using wrapper's chat() interface
        try:
            system_prompt = "You are an expert technical writer creating executive summaries for telecom HLD documents."

            executive_summary = await self.llm_client.chat(
                system_prompt=system_prompt,
                user_prompt=prompt,
            )

            logger.info("Executive summary generated successfully")
            return executive_summary

        except Exception as e:
            logger.error(f"Failed to generate executive summary: {e}")
            # Return fallback summary
            return self._generate_fallback_summary(project_highlights)

    def _extract_section_summaries(
        self,
        sections: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        """
        Extract key points from each section.

        Args:
            sections: List of GeneratedSection dicts

        Returns:
            List of section summaries
        """
        summaries = []

        for section in sections:
            title = section.get("title", "")
            content = section.get("markdown_content", "")

            # Extract first paragraph or first 200 chars as summary
            paragraphs = content.split("\n\n")
            summary = paragraphs[1] if len(paragraphs) > 1 else content[:200]

            summaries.append({
                "section": title,
                "summary": summary,
            })

        return summaries

    def _extract_project_highlights(
        self,
        blueprint: Dict[str, Any],
        project_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract key project information.

        Args:
            blueprint: Blueprint output
            project_context: Document knowledge base

        Returns:
            Dictionary of project highlights
        """
        return {
            "customer": blueprint.get("customer_name", "Unknown Customer"),
            "product": blueprint.get("product", "Unknown Product"),
            "project": blueprint.get("project_name", "Unknown Project"),
            "document_type": blueprint.get("document_type", "HLD"),
            "capacity": project_context.get("capacity", {}),
            "deployment": project_context.get("deployment_type", ""),
            "sites": project_context.get("sites", []),
        }

    def _build_executive_summary_prompt(
        self,
        section_summaries: List[Dict[str, str]],
        project_highlights: Dict[str, Any],
    ) -> str:
        """
        Build prompt for LLM to generate executive summary.

        Args:
            section_summaries: List of section summaries
            project_highlights: Key project information

        Returns:
            Prompt string
        """
        prompt = f"""Generate an Executive Summary for this {project_highlights['document_type']} document.

Project: {project_highlights['customer']} - {project_highlights['product']}
Document Type: {project_highlights['document_type']}

Section Summaries:
"""

        for summary in section_summaries:
            prompt += f"\n{summary['section']}:\n{summary['summary']}\n"

        prompt += f"""

Key Project Information:
- Customer: {project_highlights['customer']}
- Product: {project_highlights['product']}
- Deployment: {project_highlights['deployment']}
- Sites: {len(project_highlights.get('sites', []))} sites

Instructions:
1. Write a 2-3 page executive summary
2. Target audience: C-level executives, project managers
3. Structure:
   - Project Overview (1 paragraph)
   - Solution Overview (2 paragraphs)
   - Key Architecture Highlights (3-4 bullet points)
   - Deployment Approach (1 paragraph)
   - Benefits and Value (3-4 bullet points)
4. Use non-technical language, focus on business value
5. Professional, confident tone

Output: Executive Summary in markdown format.
"""

        return prompt

    def _generate_placeholder_executive_summary(
        self,
        project_highlights: Dict[str, Any],
    ) -> str:
        """
        Generate placeholder executive summary (mock implementation).

        Args:
            project_highlights: Key project information

        Returns:
            Markdown-formatted executive summary
        """
        return f"""# 1. Executive Summary

## Project Overview

This {project_highlights['document_type']} document outlines the proposed deployment of {project_highlights['product']} for {project_highlights['customer']}. Confirm the project scope and requirements against the approved input documents.

## Solution Overview

The proposed architecture, deployment sites, integrations, and operational requirements should be described using the approved design inputs.

## Key Architecture Highlights

- **Availability:** Confirm the redundancy and failover design.
- **Capacity:** Confirm sizing assumptions and growth targets.
- **Security:** Confirm applicable controls and requirements.
- **Performance:** Confirm service targets and measured limits.
- **Operations:** Confirm monitoring and maintenance responsibilities.

## Deployment Approach

Describe the deployment phases and acceptance criteria from the project plan.

## Benefits and Value

List only benefits supported by the approved design and project evidence.
"""

    def _generate_fallback_summary(
        self,
        project_highlights: Dict[str, Any],
    ) -> str:
        """
        Generate fallback summary if LLM fails.

        Args:
            project_highlights: Key project information

        Returns:
            Basic executive summary
        """
        return f"""# 1. Executive Summary

This document describes the deployment of {project_highlights['product']} for {project_highlights['customer']}.

Review the approved project inputs before treating this draft as a complete design.
"""
