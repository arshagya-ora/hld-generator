"""
Section normalization tool for assembly agent.

Fixes:
1. Section numbering (ensures hierarchical numbering like 3.1, 3.2.1)
2. Heading levels (main sections = H2, subsections = H3, etc.)
3. Missing section numbers in headings
4. Markdown bold syntax in headings
"""

import re
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class SectionNormalizer:
    """Normalizes section structure and formatting."""

    def normalize_sections(
        self,
        generated_sections: Dict[str, Any],
        blueprint: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Normalize all sections based on blueprint hierarchy.

        Args:
            generated_sections: Dict of section_id -> GeneratedSection
            blueprint: Blueprint with correct section hierarchy

        Returns:
            Normalized generated_sections dict
        """
        # Build section number mapping from blueprint
        number_map = self._build_number_mapping(blueprint)

        normalized_sections = {}

        for section_id, section in generated_sections.items():
            # Get correct section number from blueprint
            correct_number = number_map.get(section_id, section.get("section_number"))

            # Calculate correct heading level (count dots + 1)
            level = correct_number.count(".") + 1 if correct_number else 1

            # Normalize markdown content
            normalized_content = self._normalize_markdown_content(
                section.get("markdown_content", ""),
                section.get("section_number", ""),
                correct_number,
                section.get("title", ""),
                level,
            )

            # Update section dict with correct number and normalized content
            normalized_section = section.copy()
            normalized_section["section_number"] = correct_number
            normalized_section["markdown_content"] = normalized_content
            normalized_section["heading_level"] = level

            # Also update the title to remove any markdown bold syntax
            original_title = normalized_section.get("title", "")
            clean_title = self._strip_markdown_bold(original_title)
            normalized_section["title"] = clean_title

            normalized_sections[section_id] = normalized_section

            logger.debug(f"Normalized {section_id}: {section.get('section_number')} → {correct_number}")

        logger.info(f"Normalized {len(normalized_sections)} sections")
        return normalized_sections

    def _build_number_mapping(self, blueprint: Dict[str, Any]) -> Dict[str, str]:
        """
        Build mapping of section_id -> correct_section_number from blueprint.

        Handles both flat sections and nested subsections.
        """
        number_map = {}

        sections = blueprint.get("sections", [])

        for section in sections:
            section_id = section.get("section_id", "")
            section_number = section.get("section_number", "")

            if section_id:
                number_map[section_id] = section_number

            # Process subsections recursively
            self._process_subsections(
                section.get("subsections", []),
                number_map,
            )

        return number_map

    def _process_subsections(
        self,
        subsections: List[Dict[str, Any]],
        number_map: Dict[str, str],
    ) -> None:
        """Recursively process subsections to build number mapping."""
        for subsection in subsections:
            section_id = subsection.get("section_id", "")
            subsection_number = subsection.get("subsection_number", "")

            if section_id and subsection_number:
                number_map[section_id] = subsection_number

            # Process nested sub-subsections
            sub_subsections = subsection.get("sub_subsections", [])
            if sub_subsections:
                self._process_subsections(sub_subsections, number_map)

    def _normalize_markdown_content(
        self,
        content: str,
        old_number: str,
        correct_number: str,
        title: str,
        target_level: int,
    ) -> str:
        """
        Normalize markdown content:
        1. Fix heading levels
        2. Add/correct section numbers (including subsections!)
        3. Strip markdown bold from headings
        """
        lines = content.split("\n")
        normalized_lines = []
        main_section_found = False
        subsection_counter = {}  # Track subsection numbering

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Check if this is a heading
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)

            if heading_match:
                hash_count = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                # Strip markdown bold syntax from heading
                heading_text = self._strip_markdown_bold(heading_text)

                # Determine if this is the main section heading
                is_main_heading = (not main_section_found and i < 10 and title and title in heading_text)

                if is_main_heading:
                    # Main section heading - fix level and number
                    main_section_found = True
                    correct_level = target_level

                    # Remove old number if present
                    heading_text = re.sub(r'^\d+(\.\d+)*\.?\s*', '', heading_text)

                    # Add correct number
                    heading_text = f"{correct_number}. {heading_text}"

                    # Generate correct markdown heading
                    normalized_line = f"{'#' * correct_level} {heading_text}"
                    normalized_lines.append(normalized_line)
                else:
                    # Sub-heading - need to renumber AND adjust level
                    # Check if this heading has a number at the start (like "1.", "2.1", etc.)
                    number_match = re.match(r'^(\d+(?:\.\d+)*)\.?\s+(.+)$', heading_text)

                    if number_match and main_section_found:
                        # This is a numbered subsection - renumber it!
                        old_subsection_num = number_match.group(1)
                        subsection_title = number_match.group(2)

                        # Renumber: "1" → "3.1", "2" → "3.2", "2.1" → "3.2.1"
                        # Split the old number and prepend correct_number
                        old_parts = old_subsection_num.split('.')

                        # If it's a top-level subsection (e.g., "1"), make it "3.1"
                        # If it's nested (e.g., "2.1"), make it "3.2.1"
                        new_subsection_num = f"{correct_number}.{old_subsection_num}"

                        heading_text = f"{new_subsection_num}. {subsection_title}"

                        # Adjust heading level: subsections should be one level deeper
                        # Original heading level + 1 (to make subsection deeper than main)
                        adjusted_level = min(hash_count + 1, 6)

                        normalized_line = f"{'#' * adjusted_level} {heading_text}"
                        normalized_lines.append(normalized_line)
                    else:
                        # Unnumbered sub-heading - just adjust level
                        offset = target_level - 1  # e.g., if main is H2, offset = 1
                        adjusted_level = min(hash_count + offset, 6)

                        normalized_line = f"{'#' * adjusted_level} {heading_text}"
                        normalized_lines.append(normalized_line)
            else:
                # Not a heading - keep as is
                normalized_lines.append(line)

        return "\n".join(normalized_lines)

    def _strip_markdown_bold(self, text: str) -> str:
        """Strip **bold** markdown syntax from text."""
        # Remove **text**
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        return text

    def ensure_main_section_heading_level(
        self,
        markdown_content: str,
        target_level: int = 2,
    ) -> str:
        """
        Ensure the first heading in content uses the target level.

        All main sections should be H2 for consistent document structure.
        """
        lines = markdown_content.split("\n")

        for i, line in enumerate(lines):
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
            if heading_match:
                heading_text = heading_match.group(2)
                # Replace with target level
                lines[i] = f"{'#' * target_level} {heading_text}"
                break

        return "\n".join(lines)
