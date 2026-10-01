"""
Assembly Quality Checks - Prevents hallucinations and validates assembled HLD.

Deterministic quality validation checks that run after assembly:
1. Section numbering sequential (no gaps like 4 → 6)
2. No orphaned figure/table placeholders (unresolved {{FIGURE:...}})
3. No meta-commentary (self-referential writing)
4. Acronyms valid (no false positives)
5. TOC completeness (page numbers, all sections present)
6. Appendix order correct (A → B → D)
"""

import re
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class QualityChecker:
    """
    Assembly quality validation to prevent hallucinations.

    All checks are deterministic (no LLM calls) for speed and reliability.
    """

    def check_all(
        self,
        compiled_markdown: str,
        sections: Dict[str, Dict[str, Any]],
        toc_content: str = "",
        appendices_content: str = "",
        executive_summary: str = "",
    ) -> Dict[str, Any]:
        """
        Run all quality checks on the assembled HLD.

        Args:
            compiled_markdown: Full compiled markdown content
            sections: Generated sections dict (section_id → section dict)
            toc_content: Generated TOC markdown
            appendices_content: Generated appendices markdown
            executive_summary: Generated executive summary markdown

        Returns:
            {
                "passed": bool (True if all critical checks pass),
                "checks": [{"name": str, "status": "pass|fail|warning", "details": str}]
            }
        """
        checks = []

        checks.append(self.check_section_numbering(sections))
        checks.append(self.check_orphaned_placeholders(compiled_markdown))
        checks.append(self.check_meta_commentary(sections))
        checks.append(self.check_acronyms_valid(appendices_content))
        checks.append(self.check_toc_completeness(toc_content, sections))
        checks.append(self.check_appendix_order(appendices_content))

        # "passed" = no "fail" status (warnings are acceptable)
        all_passed = all(c["status"] != "fail" for c in checks)

        for check in checks:
            if check["status"] != "pass":
                logger.warning(f"Quality check [{check['name']}]: {check['status']} - {check['details']}")

        return {
            "passed": all_passed,
            "checks": checks,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 1: Section Numbering Sequential
    # ─────────────────────────────────────────────────────────────────────

    def check_section_numbering(self, sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Check for gaps in top-level section numbering (e.g., 4 → 6 skips 5).

        Excludes appendices and executive summary from numbering check.
        """
        # Extract top-level section numbers (integers only)
        top_level_numbers = []
        for section in sections.values():
            section_num = str(section.get("section_number", ""))
            section_id = section.get("section_id", "")

            # Skip appendices and executive summary
            if section_id.startswith("sec_appendix") or section_id == "sec_executive_summary":
                continue

            # Extract top-level number
            try:
                top = int(section_num.split(".")[0])
                if top not in top_level_numbers:
                    top_level_numbers.append(top)
            except (ValueError, IndexError):
                continue

        top_level_numbers.sort()

        # Check for gaps
        gaps = []
        for i in range(len(top_level_numbers) - 1):
            current = top_level_numbers[i]
            next_num = top_level_numbers[i + 1]
            if next_num - current > 1:
                missing = list(range(current + 1, next_num))
                gaps.append(f"{current} → {next_num} (missing: {missing})")

        if gaps:
            return {
                "name": "section_numbering_sequential",
                "status": "warning",
                "details": f"Section number gaps detected: {'; '.join(gaps)}",
            }

        return {
            "name": "section_numbering_sequential",
            "status": "pass",
            "details": f"Section numbering is sequential ({len(top_level_numbers)} top-level sections)",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 2: Orphaned Figure/Table Placeholders
    # ─────────────────────────────────────────────────────────────────────

    def check_orphaned_placeholders(self, compiled_markdown: str) -> Dict[str, Any]:
        """
        Detect unresolved {{FIGURE:...}} or {{TABLE:...}} placeholders in final output.
        """
        figure_orphans = re.findall(r'\{\{FIGURE:([^}]+)\}\}', compiled_markdown)
        table_orphans = re.findall(r'\{\{TABLE:([^}]+)\}\}', compiled_markdown)

        if figure_orphans or table_orphans:
            details_parts = []
            if figure_orphans:
                details_parts.append(f"{len(figure_orphans)} unresolved figures: {figure_orphans[:5]}")
            if table_orphans:
                details_parts.append(f"{len(table_orphans)} unresolved tables: {table_orphans[:5]}")

            return {
                "name": "no_orphaned_placeholders",
                "status": "fail",
                "details": "; ".join(details_parts),
            }

        return {
            "name": "no_orphaned_placeholders",
            "status": "pass",
            "details": "All figure/table placeholders resolved",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 3: Meta-Commentary Detection
    # ─────────────────────────────────────────────────────────────────────

    def check_meta_commentary(self, sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Detect self-referential writing (LLM writing about the document
        instead of writing actual content).

        Phrases like "the reference materials indicate..." or
        "based strictly on the source documents..." are meta-commentary.
        """
        meta_phrases = [
            "the reference materials",
            "based strictly on",
            "as no deployment-specific data is included",
            "the document indicates",
            "according to the source materials",
            "the provided documents",
            "as per the input documents",
            "the source document states",
            "no specific data was provided",
            "the reference document mentions",
            "based on the available documentation",
            "the input material",
        ]

        flagged = []
        for section_id, section in sections.items():
            content = section.get("markdown_content", "")
            if not content:
                continue

            content_lower = content.lower()
            for phrase in meta_phrases:
                if phrase in content_lower:
                    flagged.append({
                        "section_id": section_id,
                        "title": section.get("title", ""),
                        "phrase": phrase,
                    })
                    break  # One match per section is enough

        if flagged:
            section_names = [f["title"] or f["section_id"] for f in flagged]
            return {
                "name": "no_meta_commentary",
                "status": "warning",
                "details": f"Meta-commentary detected in {len(flagged)} sections: {section_names[:5]}",
            }

        return {
            "name": "no_meta_commentary",
            "status": "pass",
            "details": "No meta-commentary detected",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 4: Acronym Validity
    # ─────────────────────────────────────────────────────────────────────

    def check_acronyms_valid(self, appendices_content: str) -> Dict[str, Any]:
        """
        Validate acronym definitions in appendices.

        Detects common false positives from regex-based extraction:
        - Acronym followed by unrelated text (e.g., "CPU - Memory")
        - Section titles mistaken as definitions
        - TOC entries mistaken as definitions
        """
        if not appendices_content:
            return {
                "name": "acronyms_valid",
                "status": "pass",
                "details": "No appendices content to check",
            }

        # Known false positive patterns
        false_positive_patterns = [
            r'\b[A-Z]{2,}\s*[-–—]\s*(Introduction|Overview|Architecture|Deployment|Section|Chapter)',
            r'\b[A-Z]{2,}\s*[-–—]\s*(Memory|Disk|Storage|Port|Interface)\b',
            r'\b[A-Z]{2,}\s*[-–—]\s*\d+',  # Acronym - number (e.g., "VIL - 10.1")
        ]

        found_false_positives = []
        for pattern in false_positive_patterns:
            matches = re.findall(pattern, appendices_content)
            found_false_positives.extend(matches)

        # Check for very short definitions (likely wrong)
        acronym_lines = [
            line for line in appendices_content.split("\n")
            if re.match(r'^\|?\s*[A-Z]{2,}\s*\|', line)
        ]
        short_definitions = [
            line for line in acronym_lines
            if len(line.split("|")[-2].strip() if "|" in line and len(line.split("|")) > 2 else "") < 3
        ]

        issues = []
        if found_false_positives:
            issues.append(f"{len(found_false_positives)} potential false positive acronyms")
        if short_definitions:
            issues.append(f"{len(short_definitions)} acronyms with very short definitions")

        if issues:
            return {
                "name": "acronyms_valid",
                "status": "warning",
                "details": "; ".join(issues),
            }

        return {
            "name": "acronyms_valid",
            "status": "pass",
            "details": "Acronym definitions appear valid",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 5: TOC Completeness
    # ─────────────────────────────────────────────────────────────────────

    def check_toc_completeness(
        self,
        toc_content: str,
        sections: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Verify TOC covers all generated sections.
        """
        if not toc_content:
            return {
                "name": "toc_completeness",
                "status": "warning",
                "details": "No TOC content generated",
            }

        # Count non-empty TOC entries
        toc_lines = [
            line.strip() for line in toc_content.split("\n")
            if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("---")
        ]

        # Count sections that should appear in TOC
        expected_sections = [
            s for s in sections.values()
            if s.get("section_number") and not s.get("section_id", "").startswith("sec_appendix")
        ]

        if len(toc_lines) < len(expected_sections) * 0.5:
            return {
                "name": "toc_completeness",
                "status": "warning",
                "details": f"TOC has {len(toc_lines)} entries but {len(expected_sections)} sections expected",
            }

        return {
            "name": "toc_completeness",
            "status": "pass",
            "details": f"TOC has {len(toc_lines)} entries for {len(expected_sections)} sections",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Check 6: Appendix Order
    # ─────────────────────────────────────────────────────────────────────

    def check_appendix_order(self, appendices_content: str) -> Dict[str, Any]:
        """
        Verify appendices appear in correct order (A before B before C/D).
        """
        if not appendices_content:
            return {
                "name": "appendix_order_correct",
                "status": "pass",
                "details": "No appendices to check",
            }

        # Find appendix headers in order they appear
        appendix_pattern = r'#+\s*Appendix\s+([A-Z])'
        found_letters = re.findall(appendix_pattern, appendices_content)

        if not found_letters:
            return {
                "name": "appendix_order_correct",
                "status": "pass",
                "details": "No appendix headers found",
            }

        # Verify alphabetical order
        for i in range(len(found_letters) - 1):
            if ord(found_letters[i]) > ord(found_letters[i + 1]):
                return {
                    "name": "appendix_order_correct",
                    "status": "warning",
                    "details": f"Appendix order wrong: found {found_letters}, expected alphabetical",
                }

        return {
            "name": "appendix_order_correct",
            "status": "pass",
            "details": f"Appendix order correct: {found_letters}",
        }
