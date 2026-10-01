"""
Hybrid Strategy - Unified content generation strategy for all HLD sections.

Combines product profile guidance, RAG retrieval, project context, and source
document grounding into a single comprehensive prompt. This is the ONLY
strategy used for content generation.
"""

import logging
from typing import Dict, Any, List, Optional

from .base import BaseGenerationStrategy
from hld_generator.agents.content_generation.state.models import GeneratedSection, GenerationMetadata
from hld_generator.agents.content_generation.tools.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

# System prompt shared by all section generations
_SYSTEM_PROMPT = """\
You are an expert technical writer preparing an HLD from supplied project sources and profile guidance.
Write accurate, professional HLD sections in Markdown.

CONTENT HIERARCHY — use these sources in order of priority:
1. KEY PROJECT FACTS and excerpts from the uploaded source documents
2. RETRIEVED REFERENCE CONTENT from the configured indexes
3. PRODUCT PROFILE for section structure and writing guidance

ANTI-HALLUCINATION RULES:
- Use provided MASTER GLOSSARY definitions EXACTLY as given.
- Do NOT invent customer-specific values like: IP addresses, hostnames, site names, VLAN IDs.
- Follow HALLUCINATION GUARDS — use TBD ONLY for customer-specific deployment details.
- Do NOT invent acronym definitions by inferring from context.
- Use product values only when supported by supplied sources. Mark unknown versions,
  capacities, and hardware specifications for review.

ANTI-META-COMMENTARY RULES (CRITICAL — NEVER VIOLATE):
- NEVER write about the document itself, the sources, or the writing process.
- NEVER use phrases like: "no reference material", "based on general knowledge",
  "the Document Analyzer", "the reference materials indicate", "please supply",
  "cannot be confirmed", "as no data is available", "no information was provided",
  "based strictly on", "It appears that".
- Draft each section from available evidence and flag unsupported technical claims for review.
- For project-specific gaps (IPs, hostnames, counts), write the generic product
  description and mark specifics as TBD.
- Start directly with technical content — no preamble, no meta-text."""


class HybridStrategy(BaseGenerationStrategy):
    """
    Unified strategy for all HLD sections. Combines:
    - Product Knowledge (profile content_patterns — primary content source)
    - RAG retrieval (supplements with additional detail)
    - Project Context (customer, sites, deployment model)
    - Source Document (grounding for customer-specific facts)
    """

    def __init__(self, llm_client, config: Optional[Dict[str, Any]] = None):
        super().__init__(llm_client, config)
        self.prompt_builder = PromptBuilder()

    async def generate(
        self,
        section_plan: Dict[str, Any],
        rag_content: Dict[str, Any],
        image_library: Dict[str, Any],
        project_context: Dict[str, Any],
        template_variables: Dict[str, str],
        parsed_content: str = "",
    ) -> GeneratedSection:
        """
        Generate content for a single HLD section.
        """
        section_id = section_plan.get("section_id")
        title = section_plan.get("title", "Untitled")

        logger.info(f"Generating section '{title}' ({section_id})")

        # 1. Prepare RAG chunks (plain-text answers from Retrieval Agent)
        rag_chunks: List[str] = []
        if rag_content:
            product_answer = rag_content.get("rag_questions_answer_from_blueprint", "")
            if product_answer:
                rag_chunks = [product_answer]

        # 2. Prepare images from blueprint section plan (matched_images)
        section_images = []
        matched_images = section_plan.get("matched_images", [])
        for img_meta in matched_images:
            image_id = img_meta.get("image_id", "")
            section_images.append({
                "image_id": image_id,
                "caption": img_meta.get("figure_title", ""),
                "storage_path": img_meta.get("storage_path", ""),
                "assign_reason": img_meta.get("assign_reason", ""),
            })

        # 3. Extract reference HLD guidance from retrieval
        reference_chunks: list = []
        if rag_content:
            ref_answer = rag_content.get("reference_from_past_HLDs", "")
            if ref_answer:
                reference_chunks = [ref_answer]
        matched_tables: list = section_plan.get("matched_tables", [])

        # 4. Build Prompt — pass parsed_content as grounding context so the
        #    LLM can extract customer-specific details (site names, IPs, etc.)
        prompt = self.prompt_builder.build_hybrid_prompt(
            section_plan,
            rag_chunks,
            project_context,
            section_images,
            template_variables,
            grounding_context=parsed_content[:12000] if parsed_content else "",
            reference_chunks=reference_chunks,
            matched_tables=matched_tables,
        )

        # 5. Call LLM
        try:
            generated_markdown = await self.llm_client.chat(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt
            )

            # 6. Create Metadata
            metadata = GenerationMetadata(
                strategy_used="hybrid",
                retrieved_chunks_used=len(rag_chunks),
                project_data_fields_used=list(project_context.keys()),
                generation_time_seconds=0.0,
                quality_self_assessment=0.85 if rag_chunks else 0.7,
                model_name="oci-genai"
            )

            return GeneratedSection(
                section_id=section_id,
                section_number=section_plan.get("section_number", ""),
                title=title,
                markdown_content=generated_markdown,
                word_count=len(generated_markdown.split()),
                subsections_generated=len(section_plan.get("subsections", [])),
                images_inserted=[
                    {"image_id": img["image_id"], "caption": img["caption"], "storage_path": img["storage_path"]}
                    for img in section_images
                ],
                generation_metadata=metadata
            )

        except Exception as e:
            logger.error(f"Generation failed for {section_id}: {str(e)}")
            raise
