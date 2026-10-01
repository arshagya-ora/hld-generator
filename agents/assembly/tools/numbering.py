"""
Auto-numbering tool for figures, tables, and sections.

Assigns sequential numbers and updates references in markdown content.
"""

import re
import logging
from typing import List, Dict, Any, Tuple

from hld_generator.agents.assembly.state.models import (
    FigureReference,
    TableReference,
    SectionReference,
)

logger = logging.getLogger(__name__)


def _sec_sort_key(s: dict) -> tuple:
    """Numeric sort key for section dicts — prevents "10" sorting before "2"."""
    try:
        return tuple(int(x) for x in str(s.get("section_number", "0")).split("."))
    except ValueError:
        return (999,)


class AutoNumbering:
    """Automatic numbering for document elements."""

    def __init__(self):
        self.figure_counter = {}  # section_num → counter
        self.table_counter = {}  # section_num → counter

    def number_figures(
        self,
        sections: List[Dict[str, Any]],
        image_library: Dict[str, Any],
    ) -> List[FigureReference]:
        """
        Assign sequential figure numbers.

        Args:
            sections: List of GeneratedSection dicts
            image_library: Image library from Image Generation Agent

        Returns:
            List of FigureReference objects with assigned numbers
        """
        figure_refs = []

        for section in sorted(sections, key=_sec_sort_key):
            section_num = section.get("section_number", "1")
            section_id = section.get("section_id", "")

            # Get base section number (e.g., "5" from "5.2.1")
            base_num = section_num.split(".")[0]

            if base_num not in self.figure_counter:
                self.figure_counter[base_num] = 0

            # Find images in section
            images = section.get("images_inserted", [])

            for img in images:
                self.figure_counter[base_num] += 1
                figure_num = f"{base_num}.{self.figure_counter[base_num]}"

                figure_ref = FigureReference(
                    figure_number=figure_num,
                    title=img.get("caption", f"Figure {figure_num}"),
                    section_id=section_id,
                    image_id=img.get("image_id", ""),
                )

                figure_refs.append(figure_ref)

        logger.info(f"Assigned numbers to {len(figure_refs)} figures")
        return figure_refs

    def number_tables(
        self,
        sections: List[Dict[str, Any]],
    ) -> List[TableReference]:
        """
        Assign sequential table numbers.

        Args:
            sections: List of GeneratedSection dicts

        Returns:
            List of TableReference objects with assigned numbers
        """
        table_refs = []

        for section in sorted(sections, key=_sec_sort_key):
            section_num = section.get("section_number", "1")
            section_id = section.get("section_id", "")

            # Get base section number
            base_num = section_num.split(".")[0]

            if base_num not in self.table_counter:
                self.table_counter[base_num] = 0

            # Find tables in section
            tables = section.get("tables_inserted", [])

            for table in tables:
                self.table_counter[base_num] += 1
                table_num = f"{base_num}.{self.table_counter[base_num]}"

                table_ref = TableReference(
                    table_number=table_num,
                    title=table.get("caption", f"Table {table_num}"),
                    section_id=section_id,
                )

                table_refs.append(table_ref)

        logger.info(f"Assigned numbers to {len(table_refs)} tables")
        return table_refs

    def number_sections(
        self,
        sections: List[Dict[str, Any]],
    ) -> List[SectionReference]:
        """
        Extract and organize section numbering, including subsections from markdown content.

        Args:
            sections: List of GeneratedSection dicts

        Returns:
            List of SectionReference objects
        """
        section_refs = []

        for section in sorted(sections, key=_sec_sort_key):
            section_num = section.get("section_number", "1")
            section_id = section.get("section_id", "")
            title = section.get("title", "Untitled")

            # Determine heading level by counting dots
            level = section_num.count(".") + 1

            # Add main section
            section_ref = SectionReference(
                section_number=section_num,
                title=title,
                section_id=section_id,
                level=level,
            )
            section_refs.append(section_ref)

            # Extract subsections from markdown content
            markdown_content = section.get("markdown_content", "")
            subsection_refs = self._extract_subsections_from_markdown(
                markdown_content,
                section_num,
                section_id,
            )
            section_refs.extend(subsection_refs)

        logger.info(f"Organized {len(section_refs)} section references (including subsections)")
        return section_refs

    def _extract_subsections_from_markdown(
        self,
        markdown_content: str,
        parent_section_num: str,
        parent_section_id: str,
    ) -> List[SectionReference]:
        """
        Extract subsection headings from markdown content.

        Args:
            markdown_content: Markdown text
            parent_section_num: Parent section number (e.g., "3")
            parent_section_id: Parent section ID

        Returns:
            List of subsection SectionReference objects
        """
        subsection_refs = []
        lines = markdown_content.split("\n")

        for line in lines:
            # Match markdown headings with numbers: ## 3.1 Title or ### 3.2.1 Title
            heading_match = re.match(r'^(#{2,6})\s+(\d+(?:\.\d+)+)\.\s+(.+)$', line.strip())

            if heading_match:
                hash_count = len(heading_match.group(1))
                subsection_num = heading_match.group(2)
                subsection_title = heading_match.group(3).strip()

                # Only include if it's a child of current section
                if subsection_num.startswith(parent_section_num + "."):
                    # Calculate level from dots
                    level = subsection_num.count(".") + 1

                    subsection_ref = SectionReference(
                        section_number=subsection_num,
                        title=subsection_title,
                        section_id=f"{parent_section_id}_sub_{subsection_num}",
                        level=level,
                    )
                    subsection_refs.append(subsection_ref)

        return subsection_refs

    def update_figure_references(
        self,
        content: str,
        figure_refs: List[FigureReference],
    ) -> str:
        """
        Update figure references in markdown content.

        Converts:
        - {{FIGURE:image_id}} → ![Figure 5.2: Caption](storage_path)  [inline LLM-placed]
        - ![diagram](image_id) → ![Figure 5.2: Caption](image_id)     [assembly-appended]

        Orphaned placeholders (figures not in figure_refs) are replaced with warning text.

        Args:
            content: Markdown content
            figure_refs: List of figure references

        Returns:
            Updated markdown content
        """
        updated_content = content

        for fig in figure_refs:
            caption = f"Figure {fig.figure_number}: {fig.title}" if fig.title else f"Figure {fig.figure_number}"

            # Pattern 1: Replace {{FIGURE:image_id}} placeholders embedded inline by the LLM
            brace_pattern = r"\{\{FIGURE:" + re.escape(fig.image_id) + r"\}\}"
            brace_replacement = f"\n\n![{caption}]({fig.image_id})\n"
            updated_content = re.sub(brace_pattern, brace_replacement, updated_content)

            # Pattern 2: Update standard markdown image syntax ![...](image_id)
            image_pattern = rf"!\[(.*?)\]\({re.escape(fig.image_id)}\)"
            updated_content = re.sub(image_pattern, f"![{caption}]({fig.image_id})", updated_content)

        # Pattern 3: Handle orphaned {{FIGURE:...}} placeholders (not in figure_refs)
        # Find all remaining {{FIGURE:...}} patterns
        orphaned_pattern = r"\{\{FIGURE:([^}]+)\}\}"
        orphaned_matches = re.findall(orphaned_pattern, updated_content)

        if orphaned_matches:
            logger.warning(
                f"Found {len(orphaned_matches)} orphaned figure placeholders: {orphaned_matches[:5]}"
            )

            # Replace each orphaned placeholder with warning text
            for orphaned_id in set(orphaned_matches):  # Use set to avoid duplicate processing
                orphan_pattern = r"\{\{FIGURE:" + re.escape(orphaned_id) + r"\}\}"
                warning_text = f"*[Figure {orphaned_id} not found in figure library]*"
                updated_content = re.sub(orphan_pattern, warning_text, updated_content)

        return updated_content

    def update_table_references(
        self,
        content: str,
        table_refs: List[TableReference],
    ) -> str:
        """
        Update table references in markdown content.

        Converts:
        - [INSERT_TABLE: table_id] → Table X.Y: Title
        - bare "Table table_id" references → "Table X.Y"

        Args:
            content: Markdown content
            table_refs: List of table references

        Returns:
            Updated markdown content
        """
        updated_content = content

        for table in table_refs:
            table_id = getattr(table, "table_id", None)
            if not table_id:
                continue

            escaped_id = re.escape(table_id)

            # Pattern 1: [INSERT_TABLE: table_id]
            placeholder_pattern = rf"\[INSERT_TABLE:\s*{escaped_id}\]"
            replacement = f"Table {table.table_number}: {table.title}"
            updated_content = re.sub(placeholder_pattern, replacement, updated_content)

            # Pattern 2: bare "Table table_id" references
            bare_pattern = rf"\bTable\s+{escaped_id}\b"
            updated_content = re.sub(bare_pattern, f"Table {table.table_number}", updated_content)

        return updated_content
