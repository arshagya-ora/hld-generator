"""
Professional DOCX exporter for HLD Generator.

Converts the assembled HLD content into a formatted Word document matching
the style of the reference TCL_DSR_HLD.docx:
  - Brand-colored heading hierarchy
  - Embedded images with captions
  - Formatted Word tables from markdown tables
  - Cover page with project metadata
  - Header (document title) + Footer (page numbers)
  - Page margins: 0.94" top/bottom, 1.0" left/right
"""

import re
import logging
from datetime import date
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class HLDDocxExporter:
    """
    Professional DOCX exporter for High Level Design documents.

    Usage:
        exporter = HLDDocxExporter()
        path = exporter.export(parts, blueprint, generated_sections, output_path)
    """

    # Document heading colors
    H1_COLOR_HEX  = "1F4E78"   # Dark blue for H1
    H2_COLOR_HEX  = "2E75B5"   # Medium blue for H2
    H3_COLOR_HEX  = "5B9BD5"   # Light blue for H3
    H4_COLOR_HEX  = "70AD47"   # Green for H4
    CAP_COLOR_HEX = "404040"   # dark gray (captions)

    # Font settings
    FONT_FAMILY = "Aptos"
    BODY_FONT_SIZE = 11        # points

    # Image width when embedded (inches)
    IMAGE_WIDTH_INCHES = 5.5

    # -------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------

    def export(
        self,
        parts: Dict[str, str],
        blueprint: Dict[str, Any],
        generated_sections: Dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Build and save the DOCX file.

        Args:
            parts: Dict with keys executive_summary, toc_content,
                   list_of_figures, list_of_tables, appendices_content.
            blueprint: Blueprint metadata (customer_name, product, etc.)
            generated_sections: Dict of section_id -> GeneratedSection dict,
                                 each with markdown_content + images_inserted.
            output_path: Absolute path for the output .docx file.

        Returns:
            Absolute path string of the saved file.
        """
        try:
            from docx import Document
            from docx.shared import Inches, Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            raise ImportError("python-docx is required. Install with: pip install python-docx")

        self._Inches = Inches
        self._Pt = Pt
        self._RGBColor = RGBColor
        self._WD_ALIGN = WD_ALIGN_PARAGRAPH

        doc = Document()

        self._set_page_margins(doc)
        self._configure_default_styles(doc)
        self._apply_heading_styles(doc)
        self._add_cover_page(doc, blueprint)
        self._add_headers_footers(doc, blueprint)

        # Build image_id → {storage_path, caption} lookup from all sections
        image_lookup = self._build_image_lookup(generated_sections)

        # ── Front matter ──────────────────────────────────────────────
        if parts.get("executive_summary"):
            self._parse_and_insert(doc, parts["executive_summary"], image_lookup)
            doc.add_page_break()

        if parts.get("toc_content"):
            self._parse_and_insert(doc, parts["toc_content"], image_lookup)

        if parts.get("list_of_figures"):
            self._parse_and_insert(doc, parts["list_of_figures"], image_lookup)

        if parts.get("list_of_tables"):
            self._parse_and_insert(doc, parts["list_of_tables"], image_lookup)

        if parts.get("toc_content") or parts.get("executive_summary"):
            doc.add_page_break()

        # ── Main sections ─────────────────────────────────────────────
        sorted_sections = sorted(
            generated_sections.values(),
            key=lambda s: self._section_sort_key(s.get("section_number", "999"))
        )

        for section_dict in sorted_sections:
            self._insert_section(doc, section_dict, image_lookup)

        # ── Appendices ────────────────────────────────────────────────
        if parts.get("appendices_content"):
            self._parse_and_insert(doc, parts["appendices_content"], image_lookup)

        doc.save(output_path)
        logger.info(f"DOCX saved to {output_path}")
        return str(Path(output_path).absolute())

    # -------------------------------------------------------------------
    # Document setup
    # -------------------------------------------------------------------

    def _set_page_margins(self, doc) -> None:
        """Apply 0.94" top/bottom, 1.0" left/right margins."""
        Inches = self._Inches
        for section in doc.sections:
            section.top_margin    = Inches(0.94)
            section.bottom_margin = Inches(0.94)
            section.left_margin   = Inches(1.0)
            section.right_margin  = Inches(1.0)

    def _configure_default_styles(self, doc) -> None:
        """Configure Normal and list styles for a consistent font."""
        Pt = self._Pt

        # Configure Normal style (body text)
        try:
            normal_style = doc.styles['Normal']
            normal_style.font.name = self.FONT_FAMILY
            normal_style.font.size = Pt(self.BODY_FONT_SIZE)
        except KeyError:
            logger.warning("Normal style not found")

        # Configure List Bullet style
        try:
            bullet_style = doc.styles['List Bullet']
            bullet_style.font.name = self.FONT_FAMILY
            bullet_style.font.size = Pt(self.BODY_FONT_SIZE)
        except KeyError:
            logger.debug("List Bullet style not found")

        # Configure List Number style
        try:
            number_style = doc.styles['List Number']
            number_style.font.name = self.FONT_FAMILY
            number_style.font.size = Pt(self.BODY_FONT_SIZE)
        except KeyError:
            logger.debug("List Number style not found")

    def _apply_heading_styles(self, doc) -> None:
        """
        Modify the built-in Word heading styles to use document colors and font.
        Applied once at document creation so all headings inherit automatically.
        """
        Pt = self._Pt
        RGBColor = self._RGBColor

        def _hex_to_rgb(hex_str: str) -> RGBColor:
            h = hex_str.lstrip("#")
            return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

        # Heading sizes and colors
        specs = [
            ("Heading 1", 16, True,  False, self.FONT_FAMILY, self.H1_COLOR_HEX),
            ("Heading 2", 14, True,  False, self.FONT_FAMILY, self.H2_COLOR_HEX),
            ("Heading 3", 12, True,  False, self.FONT_FAMILY, self.H3_COLOR_HEX),
            ("Heading 4", 11, True,  False, self.FONT_FAMILY, self.H4_COLOR_HEX),
        ]

        for style_name, size_pt, bold, italic, font_name, color_hex in specs:
            try:
                style = doc.styles[style_name]
                style.font.size   = Pt(size_pt)
                style.font.bold   = bold
                style.font.italic = italic
                style.font.color.rgb = _hex_to_rgb(color_hex)
                if font_name:
                    style.font.name = font_name
            except KeyError:
                logger.debug(f"Style '{style_name}' not found, skipping")

    # -------------------------------------------------------------------
    # Cover page
    # -------------------------------------------------------------------

    def _add_cover_page(self, doc, blueprint: Dict[str, Any]) -> None:
        """Add a professional cover page followed by a page break."""
        Pt = self._Pt
        WD_ALIGN = self._WD_ALIGN
        RGBColor = self._RGBColor

        def _hex_to_rgb(hex_str: str) -> RGBColor:
            h = hex_str.lstrip("#")
            return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

        customer    = blueprint.get("customer_name", "Customer")
        product     = blueprint.get("product", "Product")
        doc_type    = blueprint.get("document_type", "High Level Design")
        project     = blueprint.get("project_name", blueprint.get("title", f"{product} {doc_type}"))
        today_str   = date.today().strftime("%B %d, %Y")

        # Vertical spacers
        for _ in range(6):
            doc.add_paragraph()

        # Document title
        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN.CENTER
        title_run = title_para.add_run(project)
        title_run.font.size  = Pt(28)
        title_run.font.bold  = True
        title_run.font.color.rgb = _hex_to_rgb(self.H1_COLOR_HEX)

        doc.add_paragraph()

        # Horizontal rule (thin blue bar via paragraph border)
        rule_para = doc.add_paragraph()
        rule_para.alignment = WD_ALIGN.CENTER
        rule_para.paragraph_format.space_before = Pt(0)
        rule_para.paragraph_format.space_after  = Pt(0)
        try:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            pPr  = rule_para._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"),   "single")
            bottom.set(qn("w:sz"),    "12")
            bottom.set(qn("w:space"), "1")
            bottom.set(qn("w:color"), self.H1_COLOR_HEX)
            pBdr.append(bottom)
            pPr.append(pBdr)
        except Exception:
            pass  # border is cosmetic only

        doc.add_paragraph()
        doc.add_paragraph()

        # Metadata table (label + value)
        meta_rows = [
            ("Customer",        customer),
            ("Product",         product),
            ("Document Type",   doc_type),
            ("Date",            today_str),
            ("Classification",  "Pending review"),
        ]
        for label, value in meta_rows:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN.CENTER
            bold_run = para.add_run(f"{label}:  ")
            bold_run.bold = True
            bold_run.font.size = Pt(12)
            val_run = para.add_run(value)
            val_run.font.size = Pt(12)

        doc.add_page_break()

    # -------------------------------------------------------------------
    # Header / Footer
    # -------------------------------------------------------------------

    def _add_headers_footers(self, doc, blueprint: Dict[str, Any]) -> None:
        """Add document title to header and page number to footer."""
        Pt = self._Pt
        WD_ALIGN = self._WD_ALIGN
        RGBColor = self._RGBColor

        product  = blueprint.get("product", "")
        doc_type = blueprint.get("document_type", "HLD")
        header_text = f"{doc_type} – {product}".strip(" –")

        section = doc.sections[0]

        # ── Header ────────────────────────────────────────────────────
        header = section.header
        if header.paragraphs:
            hp = header.paragraphs[0]
        else:
            hp = header.add_paragraph()
        hp.clear()
        hp.alignment = WD_ALIGN.RIGHT
        h_run = hp.add_run(header_text)
        h_run.font.size = Pt(9)
        h_run.font.color.rgb = RGBColor(0x60, 0x60, 0x60)

        # ── Footer ────────────────────────────────────────────────────
        footer = section.footer
        if footer.paragraphs:
            fp = footer.paragraphs[0]
        else:
            fp = footer.add_paragraph()
        fp.clear()
        fp.alignment = WD_ALIGN.CENTER

        prefix_run = fp.add_run("Classification pending review  |  Page ")
        prefix_run.font.size = Pt(9)

        # Inline PAGE field
        try:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            page_run = fp.add_run()
            page_run.font.size = Pt(9)
            for tag, text in [
                ("w:fldChar", None),   # begin
                ("w:instrText", " PAGE "),
                ("w:fldChar", None),   # end
            ]:
                elem = OxmlElement(tag)
                if tag == "w:fldChar":
                    elem.set(qn("w:fldCharType"), "begin" if text is None else "end")
                else:
                    elem.text = text
                page_run._r.append(elem)
            # Fix: "begin" vs "end" distinction
            fld_chars = page_run._r.findall(qn("w:fldChar"))
            if len(fld_chars) >= 2:
                fld_chars[0].set(qn("w:fldCharType"), "begin")
                fld_chars[1].set(qn("w:fldCharType"), "end")
        except Exception as exc:
            logger.debug(f"Page number field insertion failed (non-fatal): {exc}")
            fp.add_run(" [page]").font.size = Pt(9)

    # -------------------------------------------------------------------
    # Image lookup
    # -------------------------------------------------------------------

    def _build_image_lookup(self, generated_sections: Dict[str, Any]) -> Dict[str, Dict]:
        """
        Build {image_id: {"storage_path": str, "caption": str}} from all
        images_inserted entries across every generated section.
        """
        lookup: Dict[str, Dict] = {}
        for section in generated_sections.values():
            for img in section.get("images_inserted", []):
                img_id = img.get("image_id", "")
                if img_id:
                    lookup[img_id] = {
                        "storage_path": img.get("storage_path", ""),
                        "caption":      img.get("caption", ""),
                    }
        return lookup

    # -------------------------------------------------------------------
    # Section insertion (from generated_sections dict)
    # -------------------------------------------------------------------

    def _insert_section(
        self,
        doc,
        section_dict: Dict[str, Any],
        image_lookup: Dict[str, Dict],
    ) -> None:
        """
        Insert one section into the document:
        1. Parse and insert its markdown_content.
        2. Insert images_inserted entries (those not already inline in the markdown).
        """
        markdown_content = section_dict.get("markdown_content", "")
        images_inserted  = section_dict.get("images_inserted", [])

        # Track which image_ids appear inline in the markdown (both syntaxes)
        inline_image_ids = set(re.findall(r'!\[[^\]]*\]\(([^)]+)\)', markdown_content))
        inline_image_ids |= set(re.findall(r'\{\{FIGURE:([^}]+)\}\}', markdown_content))

        self._parse_and_insert(doc, markdown_content, image_lookup)

        # Insert any images that were not referenced inline
        for img in images_inserted:
            img_id = img.get("image_id", "")
            if img_id and img_id not in inline_image_ids:
                self._insert_image(doc, img_id, img.get("caption", ""), image_lookup)

    # -------------------------------------------------------------------
    # Markdown parser
    # -------------------------------------------------------------------

    def _parse_and_insert(
        self,
        doc,
        markdown_str: str,
        image_lookup: Dict[str, Dict],
    ) -> None:
        """
        Line-by-line markdown parser. Handles:
          - Headings (#, ##, ###, ####)
          - Images (![caption](image_id))
          - Markdown tables (| col | col |)
          - Bullet and numbered lists
          - Bold/italic inline formatting
          - Section separators (--- → skipped; page-level breaks handled at caller)
          - Blank lines → skipped
        """
        lines = markdown_str.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # ── Empty line ────────────────────────────────────────────
            if not stripped:
                i += 1
                continue

            # ── Code fence block (```lang ... ```) ───────────────────
            if stripped.startswith("```"):
                i += 1
                # Render content inside fences; headings and paragraphs both parsed
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    inner = lines[i].strip()
                    if inner:
                        if inner.startswith("#### "):
                            self._add_heading(doc, inner[5:], 4, self.H4_COLOR_HEX)
                        elif inner.startswith("### "):
                            self._add_heading(doc, inner[4:], 3, self.H3_COLOR_HEX)
                        elif inner.startswith("## "):
                            self._add_heading(doc, inner[3:], 2, self.H2_COLOR_HEX)
                        elif inner.startswith("# "):
                            self._add_heading(doc, inner[2:], 1, self.H1_COLOR_HEX)
                        elif inner == "---":
                            doc.add_paragraph()
                        else:
                            self._add_formatted_paragraph(doc, inner)
                    i += 1
                if i < len(lines):
                    i += 1  # skip closing fence
                continue

            # ── Section separator ─────────────────────────────────────
            if stripped == "---":
                # Don't add a hard page break for every --- separator;
                # sections flow naturally within the document.
                doc.add_paragraph()
                i += 1
                continue

            # ── Markdown table block ──────────────────────────────────
            if stripped.startswith("|") and stripped.endswith("|"):
                table_lines: List[str] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                self._insert_markdown_table(doc, table_lines)
                continue

            # ── Double-brace figure reference {{FIGURE:image_id}} ────
            brace_fig = re.match(r'\{\{FIGURE:([^}]+)\}\}', stripped)
            if brace_fig:
                image_id = brace_fig.group(1).strip()
                entry    = image_lookup.get(image_id, {})
                caption  = entry.get("caption", "")
                self._insert_image(doc, image_id, caption, image_lookup)
                i += 1
                continue

            # ── Image reference ───────────────────────────────────────
            img_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
            if img_match:
                caption  = img_match.group(1)
                image_id = img_match.group(2)
                self._insert_image(doc, image_id, caption, image_lookup)
                i += 1
                continue

            # ── Headings ──────────────────────────────────────────────
            if stripped.startswith("#### "):
                self._add_heading(doc, stripped[5:], 4, self.H4_COLOR_HEX)
            elif stripped.startswith("### "):
                self._add_heading(doc, stripped[4:], 3, self.H3_COLOR_HEX)
            elif stripped.startswith("## "):
                self._add_heading(doc, stripped[3:], 2, self.H2_COLOR_HEX)
            elif stripped.startswith("# "):
                self._add_heading(doc, stripped[2:], 1, self.H1_COLOR_HEX)

            # ── Horizontal rule (non-leading ---) ─────────────────────
            elif re.match(r"^-{3,}$", stripped) or re.match(r"^={3,}$", stripped):
                doc.add_paragraph()

            # ── Everything else ───────────────────────────────────────
            else:
                self._add_formatted_paragraph(doc, stripped)

            i += 1

    # -------------------------------------------------------------------
    # Heading helper
    # -------------------------------------------------------------------

    def _add_heading(self, doc, text: str, level: int, color_hex: str) -> None:
        """Add a heading at the given level and apply the brand color to its runs."""
        RGBColor = self._RGBColor
        Pt = self._Pt

        # Strip markdown bold syntax from heading text
        clean_text = self._strip_markdown_formatting(text)

        h = doc.add_heading(clean_text, level=level)
        color = RGBColor(*[int(color_hex[i:i+2], 16) for i in (0, 2, 4)])
        for run in h.runs:
            run.font.color.rgb = color

        # Fallback: if add_heading placed text without a run, add one
        if not h.runs:
            run = h.add_run(clean_text)
            run.font.color.rgb = color

    def _strip_markdown_formatting(self, text: str) -> str:
        """Strip markdown formatting from text (bold, italic, backticks)."""
        # Remove **bold**
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        # Remove *italic*
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        # Remove `code`
        text = re.sub(r'`(.+?)`', r'\1', text)
        return text

    # -------------------------------------------------------------------
    # Image insertion
    # -------------------------------------------------------------------

    def _insert_image(
        self,
        doc,
        image_id: str,
        caption: str,
        image_lookup: Dict[str, Dict],
    ) -> None:
        """
        Embed an image from its storage_path and add a caption paragraph.
        Falls back gracefully to a text placeholder if the file is missing.
        """
        Inches = self._Inches
        Pt = self._Pt
        WD_ALIGN = self._WD_ALIGN
        RGBColor = self._RGBColor

        cap_color = RGBColor(*[int(self.CAP_COLOR_HEX[i:i+2], 16) for i in (0, 2, 4)])

        entry = image_lookup.get(image_id, {})
        raw_path = entry.get("storage_path", "")
        display_caption = caption or entry.get("caption", image_id)

        resolved: Optional[Path] = None
        if raw_path:
            p = Path(raw_path)
            if p.exists():
                resolved = p
            else:
                # Try resolving relative to cwd
                p2 = Path.cwd() / raw_path
                if p2.exists():
                    resolved = p2

        if resolved:
            try:
                doc.add_picture(str(resolved), width=Inches(self.IMAGE_WIDTH_INCHES))
                # Center the image paragraph that was just added
                last_para = doc.paragraphs[-1]
                last_para.alignment = WD_ALIGN.CENTER

                # Caption below
                cap_para = doc.add_paragraph()
                cap_para.alignment = WD_ALIGN.CENTER
                cap_run = cap_para.add_run(f"Figure: {display_caption}")
                cap_run.font.italic = True
                cap_run.font.size   = Pt(10)
                cap_run.font.color.rgb = cap_color
                return
            except Exception as exc:
                logger.warning(f"Could not embed image '{image_id}' at '{resolved}': {exc}")

        # Placeholder when image is unavailable
        ph_para = doc.add_paragraph()
        ph_para.alignment = WD_ALIGN.CENTER
        ph_run = ph_para.add_run(f"[Figure: {display_caption}]")
        ph_run.font.italic = True
        ph_run.font.size   = Pt(10)
        ph_run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

    # -------------------------------------------------------------------
    # Markdown table → Word table
    # -------------------------------------------------------------------

    def _insert_markdown_table(self, doc, table_lines: List[str]) -> None:
        """
        Convert markdown table lines to a styled Word table.

        Expected input:
            | Header 1 | Header 2 |
            |----------|----------|
            | cell     | cell     |
        """
        # Separator detection: lines like |---|---|
        separator_re = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")

        def parse_row(raw_line: str) -> List[str]:
            return [c.strip() for c in raw_line.strip().strip("|").split("|")]

        data_lines = [l for l in table_lines if not separator_re.match(l)]
        if not data_lines:
            return

        header_cells = parse_row(data_lines[0])
        data_rows    = [parse_row(l) for l in data_lines[1:]]
        num_cols     = max(len(header_cells), 1)

        # Normalize row lengths
        def pad(row, n):
            return row[:n] + [""] * max(0, n - len(row))

        header_cells = pad(header_cells, num_cols)
        data_rows    = [pad(r, num_cols) for r in data_rows]

        try:
            tbl = doc.add_table(rows=1 + len(data_rows), cols=num_cols)
            tbl.style = "Table Grid"
            Pt = self._Pt
            RGBColor = self._RGBColor

            # Header row with a blue background
            hdr_row = tbl.rows[0]
            for col_idx, cell_text in enumerate(header_cells):
                cell = hdr_row.cells[col_idx]
                cell.text = cell_text
                for para in cell.paragraphs:
                    for run in para.runs:
                        run.bold = True
                        run.font.name = self.FONT_FAMILY
                        run.font.size = Pt(self.BODY_FONT_SIZE)
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)  # White text
                # Apply blue header shading
                self._shade_cell(cell, self.H2_COLOR_HEX)

            # Data rows with the document font
            for row_idx, row_cells in enumerate(data_rows):
                row = tbl.rows[row_idx + 1]
                for col_idx, cell_text in enumerate(row_cells):
                    cell = row.cells[col_idx]
                    cell.text = cell_text
                    # Apply the document font to data cells
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.font.name = self.FONT_FAMILY
                            run.font.size = Pt(self.BODY_FONT_SIZE)

        except Exception as exc:
            logger.warning(f"Table insertion failed (non-fatal): {exc}")
            # Fall back to plain text rows
            for line in data_lines:
                doc.add_paragraph(line.strip("|").strip())

    def _shade_cell(self, cell, fill_hex: str) -> None:
        """Apply background shading to a table cell via XML."""
        try:
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            tc   = cell._tc
            tcPr = tc.get_or_add_tcPr()
            shd  = OxmlElement("w:shd")
            shd.set(qn("w:fill"),  fill_hex)
            shd.set(qn("w:val"),   "clear")
            shd.set(qn("w:color"), "auto")
            tcPr.append(shd)
        except Exception:
            pass  # shading is cosmetic only

    # -------------------------------------------------------------------
    # Inline formatted paragraph
    # -------------------------------------------------------------------

    def _add_formatted_paragraph(self, doc, text: str) -> None:
        """
        Add a paragraph with inline bold/italic handled via run splitting.
        Handles: - / * / • bullets, numbered lists (explicit number), regular prose.
        """
        # ── Bullet list (-, *, •)  ─────────────────────────────────────────────
        if re.match(r'^[-*•]\s', text):
            item_text = text[1:].lstrip()
            para = doc.add_paragraph(style="List Bullet")
            self._add_inline_runs(para, item_text)
            return

        # ── Numbered list — render explicit number to avoid Word's global counter ──
        # (style="List Number" uses one auto-incrementing global counter across the
        #  entire document; if the TOC has 16 entries, the first body list starts
        #  at 17.  Rendering the markdown number explicitly solves this cleanly.)
        num_match = re.match(r'^(\d+)\.\s+(.+)$', text)
        if num_match:
            num       = num_match.group(1)
            item_text = num_match.group(2)
            para = doc.add_paragraph()
            para.paragraph_format.left_indent       = self._Inches(0.35)
            para.paragraph_format.first_line_indent = self._Inches(-0.35)
            para.add_run(f"{num}. ")
            self._add_inline_runs(para, item_text)
            return

        # ── Regular paragraph ──────────────────────────────────────────────────
        para = doc.add_paragraph()
        self._add_inline_runs(para, text)

    def _add_inline_runs(self, para, text: str) -> None:
        """
        Parse **bold** and *italic* tokens and add formatted runs to para.
        Shared by all paragraph types so inline markup works everywhere.
        """
        token_re = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")
        for part in token_re.split(text):
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                para.add_run(part[2:-2]).bold = True
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                para.add_run(part[1:-1]).italic = True
            elif part:
                para.add_run(part)

    # -------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------

    @staticmethod
    def _section_sort_key(section_number: str) -> Tuple:
        """
        Convert section numbers like "1", "1.1", "2.3.1" to a sortable tuple.
        """
        try:
            return tuple(int(x) for x in str(section_number).split("."))
        except (ValueError, AttributeError):
            return (999,)
