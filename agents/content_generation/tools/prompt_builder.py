"""
Prompt Builder - Constructs comprehensive prompts for content generation.
Handles combining templates, RAG content, project context, and instructions.
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Helper class to build structured prompts for the LLM.
    """

    def build_hybrid_prompt(
        self,
        section_plan: Dict[str, Any],
        rag_chunks: List[str],
        project_context: Dict[str, Any],
        images: List[Dict[str, Any]],
        template_variables: Dict[str, str],
        grounding_context: str = "",
        reference_chunks: List[str] = None,
        matched_tables: List[Dict[str, Any]] = None,
    ) -> str:
        """
        Build a comprehensive prompt for section generation.

        Prompt structure (ordered by priority):
        1. Role & Task Definition
        2. Project Context (always injected)
        3. Product Knowledge (profile content_patterns — PRIMARY content source)
        4. Source Document (parsed doc excerpt for grounding)
        5. Structure Guide (Subsections)
        6. Retrieved Reference Content (RAG — supplements product knowledge)
        7. HLD Writing Reference (past HLDs for style)
        8. Key Project Facts, Generation Steps, Requirements
        9. Figure & Table Placements
        10. Quality Checks & Style Guidelines
        """
        title = section_plan.get("title", "Untitled Section")
        section_num = section_plan.get("section_number", "")

        # ── 1. Role & Task ──────────────────────────────────────────────
        prompt = (
            f"You are an expert technical writer using uploaded sources and product profile guidance. "
            f"Your task is to write Section {section_num}: '{title}' for a "
            f"High Level Design (HLD) document.\n\n"
        )

        # ── 2. Project Context (always injected) ────────────────────────
        prompt += "## PROJECT CONTEXT\n"
        prompt += f"Product: {project_context.get('product', 'Unknown')}\n"
        prompt += f"Customer: {template_variables.get('customer_name', 'Unknown')}\n"
        prompt += f"Document Type: {template_variables.get('document_type', 'HLD')}\n"
        if 'sites' in project_context:
            prompt += f"Sites: {project_context['sites']}\n"
        if 'deployment_model' in template_variables:
            prompt += f"Deployment Model: {template_variables['deployment_model']}\n"
        if 'platform_version' in template_variables:
            prompt += f"Platform: {template_variables['platform_version']}\n"
        prompt += "\n"

        # ── 3. Product Knowledge (profile section data — PRIMARY source) ─
        # ALWAYS provide product knowledge context, even if content_patterns is empty
        content_patterns = section_plan.get("content_patterns", {})
        profile_generation_notes = section_plan.get("generation_notes", "")

        # Extract generation_flow from section_plan (comes from profile section.generation.generation_flow)
        generation_flow = section_plan.get("generation_flow", [])

        # Build product knowledge section from available profile data
        has_profile_data = bool(content_patterns or profile_generation_notes or generation_flow)

        if True:  # Always include the profile guidance section
            prompt += (
                "## PRODUCT PROFILE GUIDANCE\n"
                "Use this planning guidance for structure. Check technical and customer "
                "claims against the supplied source documents and retrieved references.\n\n"
            )

            # Add content_patterns if available
            if content_patterns:
                for key, value in content_patterns.items():
                    # Master glossary handled separately below
                    if key == "master_glossary":
                        continue
                    if isinstance(value, dict):
                        prompt += f"### {key}\n"
                        for sub_key, sub_val in value.items():
                            prompt += f"- **{sub_key}**: {sub_val}\n"
                        prompt += "\n"
                    elif isinstance(value, list):
                        prompt += f"### {key}\n"
                        for item in value:
                            prompt += f"- {item}\n"
                        prompt += "\n"
                    elif isinstance(value, str) and value.strip():
                        prompt += f"### {key}\n{value[:1000]}\n\n"

            # Add profile generation notes as product guidance
            if profile_generation_notes:
                prompt += f"### Profile guidance\n{profile_generation_notes}\n\n"

            # Add generation_flow as structured writing steps
            if generation_flow:
                prompt += "### Profile generation flow\n"
                for step in generation_flow:
                    prompt += f"- {step}\n"
                prompt += "\n"

            # If no profile data at all, provide minimal context to prevent meta-commentary
            if not has_profile_data:
                prompt += (
                    "**HLD Section**: Write this section for '{title}' using "
                    "professional technical language and industry-standard structure. "
                    "Do not invent product facts when no product context is available.\n\n"
                ).format(title=title)

            prompt += "\n"

        # ── 3a. Master Glossary ──────────────────────────────────────────
        if content_patterns.get("master_glossary"):
            prompt += "## MASTER GLOSSARY (Use Exactly As Provided)\n"
            prompt += "The following glossary is authoritative. Use these definitions EXACTLY:\n\n"
            for term in content_patterns["master_glossary"]:
                prompt += f"- {term}\n"
            prompt += "\n"

        # ── 3b. Hallucination Guards ─────────────────────────────────────
        hallucination_guards = section_plan.get("hallucination_guards", [])
        if hallucination_guards:
            prompt += "## HALLUCINATION GUARDS (CRITICAL — customer-specific values only)\n"
            prompt += "Do NOT invent the following customer-specific deployment details — mark as TBD if unknown:\n"
            for guard in hallucination_guards:
                prompt += f"- {guard}\n"
            prompt += "\n"
            prompt += (
                "**NOTE**: Product-standard values (typical traffic capacities, hardware specs, "
                "software features) require support from supplied sources; mark unknowns for review.\n\n"
            )

        # ── 4. Source Document (grounding context) ───────────────────────
        if grounding_context:
            prompt += (
                "## SOURCE DOCUMENT (extract project-specific details from here "
                "— use for customer-specific facts, site names, IP ranges, etc.)\n"
            )
            prompt += grounding_context[:12000]
            prompt += "\n\n"

        # ── 5. Structure Guide ───────────────────────────────────────────
        subsections = section_plan.get("subsections", [])
        if subsections:
            prompt += "## SECTION STRUCTURE\n"
            prompt += "Follow this subsection structure exactly:\n"
            for sub in subsections:
                notes = sub.get('generation_notes', '')
                notes_hint = f": {notes}" if notes else ""
                prompt += f"- {sub.get('subsection_number')} {sub.get('title')}{notes_hint}\n"
            prompt += "\n"

        # ── 5a. Generation Steps ─────────────────────────────────────────
        generation_steps = section_plan.get("generation_steps", [])
        if generation_steps:
            prompt += "## GENERATION INSTRUCTIONS (follow in order)\n"
            for step in generation_steps:
                prompt += f"- {step}\n"
            prompt += "\n"

        # ── 5b. Key Project Facts ────────────────────────────────────────
        content_facts = section_plan.get("content_facts", [])
        section_project_facts = section_plan.get("section_project_facts", [])
        all_facts = content_facts + [f for f in section_project_facts if f not in content_facts]
        if all_facts:
            prompt += "## KEY PROJECT FACTS (inject these verbatim where appropriate)\n"
            for fact in all_facts:
                prompt += f"- {fact}\n"
            prompt += "\n"

        # ── 5c. Style Reference (exemplar from real HLD) ────────────────
        exemplar = section_plan.get("exemplar_snippet")
        if exemplar:
            prompt += "## STYLE REFERENCE (match this tone and depth)\n"
            prompt += exemplar[:800]
            prompt += "\n\n"

        # ── 6. Retrieved Content (RAG — supplements product knowledge) ──
        if rag_chunks:
            prompt += "## RETRIEVED REFERENCE CONTENT (additional technical detail)\n"
            for i, chunk in enumerate(rag_chunks, 1):
                prompt += f"--- Source {i} ---\n{chunk}\n\n"
            prompt += "\n"

        # ── 6b. HLD Writing Reference (past completed HLDs) ─────────────
        if reference_chunks:
            prompt += (
                "## HLD WRITING REFERENCE (from past completed HLD documents — "
                "use as style and depth guide, NOT as project facts)\n"
            )
            prompt += (
                "The following shows how this section is typically written in completed "
                "HLD documents. Match the depth, sub-topics covered, and professional tone:\n\n"
            )
            for i, chunk in enumerate(reference_chunks, 1):
                prompt += f"--- Past HLD Reference {i} ---\n{chunk}\n\n"
            prompt += "\n"

        # ── 7. Requirements ──────────────────────────────────────────────
        reqs = section_plan.get("requirements_to_address", [])
        if reqs:
            prompt += "## REQUIREMENTS TO ADDRESS\n"
            for req in reqs:
                prompt += f"- {req}\n"
            prompt += "\n"

        # ── 8. Figure placements ─────────────────────────────────────────
        if images:
            prompt += "## FIGURE PLACEMENTS\n"
            prompt += (
                "At contextually appropriate points in your writing, insert figure placeholders "
                "using EXACTLY this format (no other image syntax):\n"
                "  {{FIGURE:image_id}}\n\n"
                "The Assembler will replace each placeholder with the actual image in the final document. "
                "Available figures for this section:\n"
            )
            for img in images:
                caption = img.get("caption", "")
                hint = f" — {caption}" if caption else ""
                prompt += f"- {{{{FIGURE:{img.get('image_id')}}}}}{hint}\n"
            prompt += "\n"

        # ── 8b. Extracted Tables from source document ────────────────────
        effective_tables = matched_tables or []
        tables_with_content = [t for t in effective_tables if t.get("markdown", "").strip()]
        if tables_with_content:
            prompt += "## EXTRACTED TABLES FROM SOURCE DOCUMENT (inject verbatim with appropriate context)\n"
            for t in tables_with_content:
                label = t.get("use_as") or t.get("description") or t.get("extracted_table_id", "Table")
                prompt += f"**Table: {label}**\n"
                prompt += t["markdown"].strip()
                prompt += "\n\n"
            prompt += "\n"

        # ── 9. Quality Checks ────────────────────────────────────────────
        quality_checks = section_plan.get("quality_checks", [])
        if quality_checks:
            prompt += "## QUALITY CHECKS (your output must satisfy all of these)\n"
            for check in quality_checks:
                prompt += f"- {check}\n"
            prompt += "\n"

        # ── 10. Style Guide + Anti-Meta-Commentary Rules ─────────────────
        prompt += "## STYLE GUIDELINES\n"
        prompt += "- Use professional, objective technical language.\n"
        prompt += "- Use Markdown formatting (## for subsections, **bold** for emphasis, lists where appropriate).\n"
        prompt += "- Ensure all technical terms match the Product Knowledge and Reference Content.\n"
        prompt += "\n"
        prompt += "## TBD USAGE POLICY (use sparingly - only for customer-specific deployment details)\n"
        prompt += "- Use TBD ONLY for: customer-specific IPs, hostnames, site names, VLAN IDs, exact deployment counts.\n"
        prompt += "- Do NOT use TBD for: product capacities, hardware specs, software features, standard architectures.\n"
        prompt += "- For product-standard values: Use supplied evidence; mark unsupported specifics for review.\n"
        prompt += "  Example: 'The SBC supports up to 10,000 concurrent sessions' (product capability, not TBD).\n"
        prompt += "  Example: 'Deployed at site [TBD] with IP address [TBD]' (customer-specific, use TBD).\n"
        prompt += "\n"
        prompt += "## ABSOLUTE RULES — NEVER VIOLATE\n"
        prompt += "1. ANTI-META-COMMENTARY (CRITICAL — violations will be rejected):\n"
        prompt += "   - NEVER write about the document itself, the sources, the data availability, or the writing process.\n"
        prompt += "   - FORBIDDEN PHRASES (never use these):\n"
        prompt += "     * 'no reference material', 'no data is available', 'no information was provided'\n"
        prompt += "     * 'based on general knowledge', 'based strictly on', 'It appears that'\n"
        prompt += "     * 'the Document Analyzer', 'the reference materials indicate', 'the source documents'\n"
        prompt += "     * 'please supply', 'cannot be confirmed', 'requires clarification'\n"
        prompt += "     * 'As no deployment-specific data is included', 'pending customer input'\n"
        prompt += "   - Do NOT start with: 'Here is the section', 'This section describes', 'Based on available data'.\n"
        prompt += "   - Start DIRECTLY with technical content grounded in the supplied product context.\n\n"
        prompt += "2. ALWAYS PRODUCE SUBSTANTIVE CONTENT:\n"
        prompt += "   - NEVER refuse to write a section.\n"
        prompt += "   - The PRODUCT KNOWLEDGE section IS your reference material — use it as the primary source.\n"
        prompt += "   - For gaps in customer-specific details: write the generic product description, mark specifics as TBD.\n"
        prompt += "   - Example: 'The SBC HA pair is deployed at [TBD site] with virtual IP [TBD].' (correct)\n"
        prompt += "   - Example: 'No information is available about the SBC deployment.' (WRONG - meta-commentary)\n\n"

        return prompt
