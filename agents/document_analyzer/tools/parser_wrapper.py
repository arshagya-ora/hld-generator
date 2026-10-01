"""
Document parser wrapper using Docling.

Handles parsing of DOCX, PPTX, and PDF files, extracting text, tables, and
structure.  DOCX/PPTX files are first converted to PDF via LibreOffice headless
so that Docling's superior PDF pipeline (OCR, table structure, image extraction)
is used for all document types.
"""

import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
import tempfile
import os

# Docling imports
try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False

logger = logging.getLogger(__name__)


class ParserWrapper:
    """
    Wrapper for Docling document parsing.

    Supports:
    - PDF files (native Docling PDF pipeline)
    - DOCX files (converted to PDF via LibreOffice, then parsed as PDF)
    - PPTX files (converted to PDF via LibreOffice, then parsed as PDF)
    - Image files (PNG, JPG, JPEG, TIFF, BMP, GIF - processed directly with OCR)
    - Text extraction
    - Table extraction
    - Document structure analysis

    Usage:
        parser = ParserWrapper()
        result = await parser.parse("document.docx")
        text = result["text"]
        tables = result["tables"]
    """

    # File extensions that need LibreOffice conversion before Docling parsing
    _CONVERTIBLE_EXTENSIONS = {".docx", ".doc", ".pptx", ".ppt"}

    # Image file extensions (processed directly by Docling)
    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"}

    def __init__(self):
        """Initialize the parser wrapper"""
        if not DOCLING_AVAILABLE:
            raise ImportError(
                "Docling is not installed. Install with: pip install docling"
            )

        # Configure PDF pipeline for text + table + image extraction in one pass.
        # generate_picture_images=True lets the ConversionResult be reused by
        # the ImageExtractor, avoiding a second full Docling conversion.
        self.pdf_pipeline_options = PdfPipelineOptions()
        self.pdf_pipeline_options.do_table_structure = True
        self.pdf_pipeline_options.do_ocr = True  # Enabled OCR for scanned documents
        self.pdf_pipeline_options.generate_picture_images = True
        self.pdf_pipeline_options.images_scale = 1.0  # Reduced from 2.0 to prevent memory errors on large PDFs

        self.converter = DocumentConverter()

        # Detect LibreOffice binary once at init
        self._soffice_bin = self._find_soffice()

    # ── LibreOffice detection ────────────────────────────────────────────

    @staticmethod
    def _find_soffice() -> Optional[str]:
        """
        Locate the LibreOffice ``soffice`` binary on the system.

        Returns the path string if found, or None.
        """
        # shutil.which covers Linux PATH and Windows registry
        path = shutil.which("soffice")
        if path:
            return path

        # Common Linux paths not always on PATH
        for candidate in [
            "/usr/bin/soffice",
            "/usr/local/bin/soffice",
            "/snap/bin/soffice",
        ]:
            if Path(candidate).is_file():
                return candidate

        # Common Windows paths
        for candidate in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]:
            if Path(candidate).is_file():
                return candidate

        return None

    # ── LibreOffice conversion ───────────────────────────────────────────

    async def _convert_to_pdf_via_libreoffice(self, source_path: Path) -> Path:
        """
        Convert a DOCX/PPTX file to PDF using LibreOffice headless.

        Uses a unique ``UserInstallation`` profile per call so that multiple
        conversions can run concurrently without locking each other.

        Args:
            source_path: Path to the .docx / .pptx file.

        Returns:
            Path to the generated PDF (in a temp directory).

        Raises:
            RuntimeError: If LibreOffice is not installed or conversion fails.
        """
        if not self._soffice_bin:
            raise RuntimeError(
                "LibreOffice is not installed or not on PATH. "
                "Install it (e.g. `sudo apt install libreoffice-common`) "
                "to enable DOCX/PPTX → PDF conversion."
            )

        # Create a temp output directory for the PDF
        out_dir = Path(tempfile.mkdtemp(prefix="hld_lo_"))

        # Unique user profile so concurrent calls don't conflict
        profile_dir = Path(tempfile.mkdtemp(prefix="hld_lo_profile_"))
        profile_uri = profile_dir.as_uri()  # file:///tmp/...

        cmd = [
            self._soffice_bin,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to", "pdf",
            "--outdir", str(out_dir),
            str(source_path),
        ]

        logger.info(
            f"Converting {source_path.name} to PDF via LibreOffice ..."
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300  # 5 min max
            )

            if proc.returncode != 0:
                err_msg = stderr.decode(errors="replace").strip()
                raise RuntimeError(
                    f"LibreOffice conversion failed (rc={proc.returncode}): {err_msg}"
                )

            # The output PDF has the same stem as the source file
            pdf_path = out_dir / (source_path.stem + ".pdf")
            if not pdf_path.exists():
                # Some LibreOffice versions lower-case the extension
                candidates = list(out_dir.glob("*.pdf"))
                if candidates:
                    pdf_path = candidates[0]
                else:
                    raise RuntimeError(
                        f"LibreOffice ran but no PDF produced in {out_dir}"
                    )

            logger.info(
                f"Conversion complete: {pdf_path.name} "
                f"({pdf_path.stat().st_size:,} bytes)"
            )
            return pdf_path

        except asyncio.TimeoutError:
            raise RuntimeError(
                f"LibreOffice conversion timed out after 300s for {source_path.name}"
            )
        finally:
            # Clean up the temporary profile directory
            shutil.rmtree(profile_dir, ignore_errors=True)

    # ── Main parse entry point ───────────────────────────────────────────

    async def parse(
        self,
        file_path: str,
        extract_tables: bool = True,
        extract_images: bool = False
    ) -> Dict[str, Any]:
        """
        Parse a document file.

        Processing workflow:
        - DOCX/PPTX: Converted to PDF via LibreOffice → Docling PDF pipeline
        - PDF: Parsed directly via Docling PDF pipeline
        - Images: Parsed directly via Docling with OCR

        Args:
            file_path: Path to DOCX, PPTX, PDF, or image file
            extract_tables: Whether to extract tables (PDF/DOCX/PPTX only)
            extract_images: Whether to extract images/diagrams (PDF/DOCX/PPTX only)

        Returns:
            Dictionary with:
                - text: Full document text (OCR applied for images)
                - tables: List of extracted tables
                - structure: Document structure (sections, headings)
                - metadata: File info and parsing stats
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")

        file_ext = file_path.suffix.lower()
        original_file_path = file_path  # preserve for metadata
        converted_pdf_path = None

        try:
            if file_ext in self._CONVERTIBLE_EXTENSIONS:
                # Convert DOCX/PPTX → PDF via LibreOffice, then parse as PDF
                converted_pdf_path = await self._convert_to_pdf_via_libreoffice(file_path)
                result = await self._parse_pdf(
                    converted_pdf_path, extract_tables, extract_images
                )
                # Override metadata to reflect the original source file
                result["metadata"]["file_type"] = file_ext.lstrip(".")
                result["metadata"]["file_name"] = original_file_path.name
                result["metadata"]["file_size"] = original_file_path.stat().st_size
                result["metadata"]["converted_from"] = file_ext
                result["metadata"]["converted_pdf"] = str(converted_pdf_path)
                return result

            elif file_ext == ".pdf":
                return await self._parse_pdf(file_path, extract_tables, extract_images)

            elif file_ext in self._IMAGE_EXTENSIONS:
                # Images go directly to Docling's image pipeline
                return await self._parse_image(file_path)

            else:
                raise ValueError(
                    f"Unsupported file type: {file_ext}. "
                    f"Supported: .pdf, .docx, .doc, .pptx, .ppt, and image files (.png, .jpg, .jpeg, etc.)"
                )
        finally:
            # Clean up the converted PDF's temp directory after parsing is done
            if converted_pdf_path and converted_pdf_path.exists():
                shutil.rmtree(converted_pdf_path.parent, ignore_errors=True)
    
    # Base directory for all extracted images (persistent, not a tempdir)
    IMAGES_BASE_DIR = Path("./images/parsed")

    def _make_image_dir(self, file_path: Path) -> Path:
        """
        Return (and create) a persistent directory for images extracted from
        *file_path*.  The directory is named after the document stem so it
        survives between the parse node and the image-extraction node.
        """
        image_dir = self.IMAGES_BASE_DIR / file_path.stem
        image_dir.mkdir(parents=True, exist_ok=True)
        return image_dir

    async def _parse_pdf(
        self,
        file_path: Path,
        extract_tables: bool,
        extract_images: bool
    ) -> Dict[str, Any]:
        """Parse PDF file using Docling with table/image extraction in one pass."""
        try:
            # PdfFormatOption wraps the pipeline options — passing raw PdfPipelineOptions
            # directly causes Docling to ignore the options and return empty text.
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=self.pdf_pipeline_options)
                }
            )

            # Single Docling conversion (text + tables + picture images)
            result = converter.convert(str(file_path))

            # Create a persistent image directory for this document.
            image_dir = self._make_image_dir(file_path)

            # Export to markdown WITH referenced-image mode so that:
            #   • images are saved to image_dir (persistent on disk)
            #   • the markdown text contains inline ![caption](path) references
            # This means Cognee indexes the document WITH image context preserved.
            try:
                full_text = result.document.export_to_markdown(
                    image_mode="referenced",
                    image_dir=image_dir,
                )
            except TypeError:
                # Older Docling versions may not support image_mode/image_dir
                full_text = result.document.export_to_markdown()

            # Extract tables
            tables = []
            if extract_tables and hasattr(result.document, 'tables'):
                tables = self._extract_tables(result.document)

            # Extract structure from the already-exported markdown (avoid re-export)
            structure = self._extract_structure_from_text(full_text)

            return {
                "text": full_text,
                "tables": tables,
                "structure": structure,
                # Raw Docling ConversionResult — the ImageExtractor reuses this so
                # it can skip a second full Docling conversion of the same file.
                "converter_result": result,
                # Persistent dir where images were saved.
                "image_dir": str(image_dir),
                "metadata": {
                    "file_type": "pdf",
                    "file_name": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "page_count": getattr(result.document, 'num_pages', None),
                    "success": True
                }
            }

        except Exception as e:
            return {
                "text": "",
                "tables": [],
                "structure": {},
                "converter_result": None,
                "image_dir": None,
                "metadata": {
                    "file_type": "pdf",
                    "file_name": file_path.name,
                    "success": False,
                    "error": str(e)
                }
            }

    async def _parse_image(self, file_path: Path) -> Dict[str, Any]:
        """
        Parse image file using Docling's image pipeline.

        Images are processed directly by Docling without conversion.
        OCR is applied to extract any text content.

        Args:
            file_path: Path to the image file

        Returns:
            Dictionary with extracted text and metadata
        """
        try:
            # Docling supports images directly via InputFormat.IMAGE
            converter = DocumentConverter()

            # Convert the image (Docling will apply OCR if needed)
            result = converter.convert(str(file_path))

            # Extract text from the image
            try:
                full_text = result.document.export_to_markdown()
            except Exception:
                full_text = ""

            # Images typically don't have complex structure, but extract what we can
            structure = self._extract_structure_from_text(full_text)

            return {
                "text": full_text,
                "tables": [],  # Images processed as images won't have table extraction
                "structure": structure,
                "converter_result": result,
                "image_dir": None,  # Not applicable for single image input
                "metadata": {
                    "file_type": file_path.suffix.lstrip("."),
                    "file_name": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "is_image": True,
                    "success": True
                }
            }

        except Exception as e:
            logger.error(f"Image parsing failed for {file_path.name}: {e}")
            return {
                "text": "",
                "tables": [],
                "structure": {},
                "converter_result": None,
                "image_dir": None,
                "metadata": {
                    "file_type": file_path.suffix.lstrip("."),
                    "file_name": file_path.name,
                    "is_image": True,
                    "success": False,
                    "error": str(e)
                }
            }

    def _calculate_table_dimensions(self, markdown: str) -> tuple[int, int]:
        """
        Calculate table dimensions from markdown representation.

        Handles standard markdown tables:
        | Header 1 | Header 2 | Header 3 |
        |----------|----------|----------|
        | Cell 1   | Cell 2   | Cell 3   |
        | Cell 4   | Cell 5   | Cell 6   |

        Args:
            markdown: Table in markdown format

        Returns:
            (num_rows, num_cols) where num_rows includes header row
        """
        if not markdown or not markdown.strip():
            return (0, 0)

        try:
            lines = [line.strip() for line in markdown.split('\n') if line.strip()]

            # Filter out separator lines (|---|---|)
            data_lines = []
            for line in lines:
                if not line.startswith('|'):
                    continue
                # Skip separator lines (only contain |, -, :, and spaces)
                if all(c in '|-: \t' for c in line):
                    continue
                data_lines.append(line)

            if not data_lines:
                return (0, 0)

            # Count columns from first row
            first_row = data_lines[0]
            cells = [cell.strip() for cell in first_row.split('|')]
            cells = [cell for cell in cells if cell]  # Remove empty strings
            num_cols = len(cells)

            # Count rows (all data lines including header)
            num_rows = len(data_lines)

            return (num_rows, num_cols)

        except Exception as e:
            logger.warning(f"Failed to calculate table dimensions: {e}")
            return (0, 0)

    def _extract_tables(self, document) -> List[Dict[str, Any]]:
        """
        Extract rich table data from document.

        Captures for each table:
          - Full markdown representation (table content verbatim)
          - Section/heading context (which section the table appears in)
          - Page number (from Docling provenance)
          - Caption/title (if present)
          - Row/column counts

        Docling extracts tables from BOTH text-based and image-based (scanned)
        pages, so this captures ALL tables in the document.
        """
        tables = []

        if not hasattr(document, 'tables'):
            return tables

        # Export full markdown once for section-context detection.
        try:
            full_markdown = document.export_to_markdown()
        except Exception:
            full_markdown = ""

        try:
            for idx, table in enumerate(document.tables):
                # ── markdown representation ──────────────────────────────────
                table_markdown = ""
                try:
                    if hasattr(table, 'export_to_markdown'):
                        table_markdown = table.export_to_markdown()
                except Exception:
                    pass

                # ── page number from provenance ──────────────────────────────
                page_no = None
                try:
                    if hasattr(table, 'prov') and table.prov:
                        page_no = table.prov[0].page_no
                except Exception:
                    pass

                # ── caption ──────────────────────────────────────────────────
                caption = ""
                try:
                    cap = getattr(table, 'caption', None)
                    if cap is not None:
                        caption = str(cap.text) if hasattr(cap, 'text') else str(cap)
                except Exception:
                    pass

                # ── section context ───────────────────────────────────────────
                # Find which heading immediately precedes this table in the
                # full markdown by locating the table's first ~80 chars and
                # scanning backward for the nearest heading.
                section_context = ""
                if table_markdown and full_markdown:
                    fingerprint = table_markdown.strip()[:80]
                    pos = full_markdown.find(fingerprint)
                    if pos != -1:
                        for line in reversed(full_markdown[:pos].split('\n')):
                            stripped = line.strip()
                            if stripped.startswith('#'):
                                section_context = stripped.lstrip('#').strip()
                                break

                # Calculate dimensions from markdown
                num_rows, num_cols = self._calculate_table_dimensions(table_markdown)

                tables.append({
                    "table_id": f"Table_{idx + 1}",
                    "caption": caption,
                    "section": section_context,
                    "page_number": page_no,
                    "markdown": table_markdown,
                    "num_rows": num_rows,      # ← CALCULATED
                    "num_cols": num_cols,      # ← CALCULATED
                    "source": "docling",
                })

        except Exception as e:
            print(f"Warning: Table extraction failed: {e}")

        return tables
    
    def _extract_structure_from_text(self, markdown_text: str) -> Dict[str, Any]:
        """
        Extract document structure (headings, sections) from already-exported
        markdown text.  This avoids calling export_to_markdown() a second time.
        """
        structure: Dict[str, Any] = {"sections": [], "headings": []}

        try:
            for line in markdown_text.split("\n"):
                if line.startswith("#"):
                    parts = line.split()
                    level = len(parts[0])        # number of '#' chars
                    heading_text = line.lstrip("#").strip()
                    structure["headings"].append({"level": level, "text": heading_text})
                    if level == 1:
                        structure["sections"].append(heading_text)
        except Exception as e:
            print(f"Warning: Structure extraction failed: {e}")

        return structure

    # Keep old name as an alias so existing callers don't break.
    def _extract_structure(self, document) -> Dict[str, Any]:
        try:
            return self._extract_structure_from_text(document.export_to_markdown())
        except Exception:
            return {"sections": [], "headings": []}
    


# Convenience function
async def parse_document(file_path: str) -> Dict[str, Any]:
    """
    Quick helper to parse a document.
    
    Args:
        file_path: Path to document file
        
    Returns:
        Parsed document data
    """
    parser = ParserWrapper()
    return await parser.parse(file_path)
