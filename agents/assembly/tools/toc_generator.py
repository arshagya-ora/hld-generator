"""
Table of Contents (TOC) generation tool.

Generates TOC, List of Figures, and List of Tables from document structure.
"""

import logging
from typing import List, Dict, Any

from hld_generator.agents.assembly.state.models import (
    FigureReference,
    TableReference,
    SectionReference,
)

logger = logging.getLogger(__name__)


class TOCGenerator:
    """Generates table of contents and related lists."""

    def generate_toc(
        self,
        section_refs: List[SectionReference],
        has_executive_summary: bool = False,
        appendix_sections: List[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate Table of Contents from section references.

        Args:
            section_refs: List of section references
            has_executive_summary: Whether to include Executive Summary in TOC
            appendix_sections: List of appendix section dicts from content generation

        Returns:
            Markdown-formatted TOC
        """
        toc_lines = ["# Table of Contents\n"]

        # Add Executive Summary first if present
        if has_executive_summary:
            toc_lines.append("Executive Summary")

        # Add main sections
        for section in sorted(section_refs, key=lambda s: self._sort_key(s.section_number)):
            # Indent based on level
            indent = "  " * (section.level - 1)

            # Create entry
            # Format: "1. Introduction ........................... 5"
            # For now, without page numbers (can be added later)
            entry = f"{indent}{section.section_number}. {section.title}"

            toc_lines.append(entry)

        # Add appendices at the end (in order: A, B, then any content-generated ones)
        # Note: Auto-generated appendices (A: Acronyms, B: References) are not in section_refs
        # but will be added automatically by the appendix generator
        toc_lines.append("Appendix A: Acronyms and Abbreviations")
        toc_lines.append("Appendix B: References")

        # Add content-generated appendices (like Appendix D)
        if appendix_sections:
            for appendix in appendix_sections:
                title = appendix.get("title", "")
                # Remove "TBD. " prefix if present
                title = title.replace("TBD. ", "")
                toc_lines.append(title)

        toc_content = "\n".join(toc_lines)
        total_entries = len(section_refs) + (1 if has_executive_summary else 0) + 2 + len(appendix_sections or [])
        logger.info(f"Generated TOC with {total_entries} entries ({len(section_refs)} main sections, {len(appendix_sections or [])} content appendices)")

        return toc_content

    def generate_list_of_figures(
        self,
        figure_refs: List[FigureReference],
    ) -> str:
        """
        Generate List of Figures.

        Args:
            figure_refs: List of figure references

        Returns:
            Markdown-formatted list of figures
        """
        if not figure_refs:
            return ""

        lof_lines = ["# List of Figures\n"]

        for fig in sorted(figure_refs, key=lambda f: self._sort_key(f.figure_number)):
            # Skip figures with no meaningful title (blank captions from source doc)
            title = (fig.title or "").strip()
            if not title:
                continue
            # Format: "Figure 1.1: Document Structure ................. 4"
            entry = f"Figure {fig.figure_number}: {title}"
            lof_lines.append(entry)

        # Return empty string if no figures have titles (avoids orphaned header)
        if len(lof_lines) == 1:
            logger.info("No figures with titles found — skipping List of Figures")
            return ""

        lof_content = "\n".join(lof_lines)
        titled_count = len(lof_lines) - 1
        logger.info(f"Generated List of Figures with {titled_count}/{len(figure_refs)} titled entries")

        return lof_content

    def generate_list_of_tables(
        self,
        table_refs: List[TableReference],
    ) -> str:
        """
        Generate List of Tables.

        Args:
            table_refs: List of table references

        Returns:
            Markdown-formatted list of tables
        """
        if not table_refs:
            return ""

        lot_lines = ["# List of Tables\n"]

        for table in sorted(table_refs, key=lambda t: self._sort_key(t.table_number)):
            # Format: "Table 1.1: VM Resource Requirements ............. 10"
            entry = f"Table {table.table_number}: {table.title}"
            lot_lines.append(entry)

        lot_content = "\n".join(lot_lines)
        logger.info(f"Generated List of Tables with {len(table_refs)} entries")

        return lot_content

    def _sort_key(self, number_str: str) -> tuple:
        """
        Convert number string (e.g., "5.2") to sortable tuple.

        Args:
            number_str: Number string like "5.2" or "10.15"

        Returns:
            Tuple of integers for sorting (TBD sections return 999 to sort last)
        """
        try:
            parts = number_str.split(".")
            return tuple(int(p) for p in parts)
        except ValueError:
            return (999,)  # Match numbering.py behavior - TBD sections sort last


class AppendixGenerator:
    """Generates appendices (acronyms, references) using AI — fully dynamic, no hardcoded content."""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM client for AI-powered appendix generation.
                        Required for proper operation.
        """
        self.llm_client = llm_client

    async def generate_acronyms(self, content: str) -> str:
        """
        Generate acronyms appendix by asking the LLM to extract all acronyms
        used in the document and provide their correct industry-standard definitions.

        The LLM sees the compiled document content and uses its knowledge of
        telecom products to produce accurate, context-appropriate definitions.

        Args:
            content: Full compiled document content

        Returns:
            Markdown-formatted acronyms appendix
        """
        if not self.llm_client:
            logger.warning("No LLM client for acronym generation — returning empty appendix")
            return "# Appendix A: Acronyms and Abbreviations\n\n*No acronyms extracted.*\n"

        # Send a representative excerpt to the LLM (first 15K + last 5K chars)
        # to keep within token limits while covering the full document scope
        if len(content) > 20000:
            doc_excerpt = content[:15000] + "\n\n[...middle sections omitted...]\n\n" + content[-5000:]
        else:
            doc_excerpt = content

        system_prompt = (
            "You are a technical document specialist. Your task is to extract ALL "
            "acronyms and abbreviations used in the provided HLD document and "
            "provide their correct, standard definitions.\n\n"
            "RULES:\n"
            "- Extract EVERY acronym that appears in the document (2+ uppercase letters).\n"
            "- Provide the standard industry/product definition for each acronym.\n"
            "- If the document contains a Terms and Definitions table, use those "
            "definitions as your primary source.\n"
            "- For product acronyms, use names from the supplied product documents.\n"
            "- For telecom acronyms, use standard 3GPP/IETF definitions.\n"
            "- Do NOT include generic English words that happen to be uppercase.\n"
            "- Sort alphabetically.\n"
            "- Include ONLY acronyms that are actually used in this document.\n\n"
            "OUTPUT FORMAT — return ONLY a markdown table, nothing else:\n"
            "| Acronym | Definition |\n"
            "|---------|------------|\n"
            "| AAA | Authentication, Authorization, and Accounting |\n"
            "| ... | ... |"
        )

        user_prompt = (
            "Extract all acronyms and their correct definitions from this HLD document:\n\n"
            f"{doc_excerpt}"
        )

        try:
            response = await self.llm_client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            # Validate response contains a markdown table
            if '|' in response:
                # Strip any preamble/postamble text — keep only the table
                table_lines = []
                in_table = False
                for line in response.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('|'):
                        in_table = True
                        table_lines.append(stripped)
                    elif in_table and not stripped.startswith('|'):
                        break  # End of table

                if len(table_lines) >= 3:  # header + separator + at least 1 row
                    acronym_count = len(table_lines) - 2  # minus header and separator
                    logger.info(f"LLM extracted {acronym_count} acronyms")
                    return (
                        "# Appendix A: Acronyms and Abbreviations\n\n"
                        + "\n".join(table_lines) + "\n"
                    )

            logger.warning("LLM acronym response did not contain a valid table — using raw response")
            return "# Appendix A: Acronyms and Abbreviations\n\n" + response + "\n"

        except Exception as e:
            logger.error(f"LLM acronym generation failed: {e}")
            return "# Appendix A: Acronyms and Abbreviations\n\n*Acronym extraction failed.*\n"

    async def generate_references(self, content: str) -> str:
        """
        Generate references appendix by asking the LLM to extract all references
        cited in the document (RFCs, 3GPP specs, product documentation, etc.).

        Args:
            content: Full compiled document content

        Returns:
            Markdown-formatted references appendix
        """
        if not self.llm_client:
            return "# Appendix B: References\n\n*No references extracted.*\n"

        # Focus on beginning of document where references section usually is
        doc_excerpt = content[:15000] if len(content) > 15000 else content

        system_prompt = (
            "You are a technical document specialist. Extract all references "
            "(industry standards, product documents, 3GPP specs, RFCs, GSMA docs, etc.) "
            "cited or relevant to the provided HLD document.\n\n"
            "RULES:\n"
            "- Include all RFCs, 3GPP specs, GSMA documents mentioned.\n"
            "- Include all product documentation referenced.\n"
            "- Number them sequentially [1], [2], etc.\n"
            "- Use the full formal title of each reference.\n"
            "- Only include references that are relevant to the product and content.\n\n"
            "OUTPUT FORMAT — return ONLY the numbered list, nothing else:\n"
            "[1] IETF RFC 3588 - Diameter Base Protocol\n"
            "[2] ..."
        )

        user_prompt = (
            "Extract all references from this HLD document:\n\n"
            f"{doc_excerpt}"
        )

        try:
            response = await self.llm_client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            logger.info("LLM generated references appendix")
            return "# Appendix B: References\n\n" + response + "\n"

        except Exception as e:
            logger.error(f"LLM reference generation failed: {e}")
            return "# Appendix B: References\n\n*Reference extraction failed.*\n"
