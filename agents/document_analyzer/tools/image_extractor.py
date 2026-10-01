"""
Image Extractor tool for the Document Analyzer Agent.

Uses Docling's native referenced image export to automatically save images
to disk, then filters by area and aspect ratio to skip small logos/icons
and narrow banners. Builds metadata with bounding boxes, page numbers,
and provenance information.
"""

import io
import hashlib
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat
    from docling_core.types.doc import PictureItem, TableItem
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False


class ImageExtractor:
    """
    Extracts images from documents using Docling's referenced export mode.

    Docling automatically saves images to a directory and provides references.
    We apply two-stage filtering to keep only meaningful diagrams:
      1. Area filter  — skip images smaller than `area_threshold` (default 15000 sq pts)
      2. Aspect ratio — skip images outside 0.3–3.0 range (banners, sidebars)

    Usage:
        extractor = ImageExtractor(area_threshold=15000)
        images = extractor.extract_images("document.pdf")
        # Returns list of dicts with image_bytes, page, bbox, caption, etc.
    """

    # Aspect ratio band for "meaningful" images (charts, diagrams, photos)
    ASPECT_RATIO_MIN = 0.3   # Narrower → likely a vertical sidebar / icon strip
    ASPECT_RATIO_MAX = 3.0   # Wider   → likely a horizontal banner / rule

    def __init__(
        self,
        area_threshold: float = 15000,
        images_scale: float = 2.0,
        aspect_ratio_range: tuple = None,
    ):
        """
        Initialize the ImageExtractor.

        Args:
            area_threshold: Minimum area (width * height in points) to keep.
                           Default 15000 filters out small logos/icons.
                           Reference: a 72-DPI page is ~612×792 pts.
            images_scale: Resolution multiplier for extracted images (default 2.0).
            aspect_ratio_range: Optional (min, max) tuple. Images outside this
                               range are skipped. Default (0.3, 3.0).
        """
        if not DOCLING_AVAILABLE:
            raise ImportError(
                "docling is required for image extraction. "
                "Install with: pip install docling"
            )
        self.area_threshold = area_threshold
        self.images_scale = images_scale
        if aspect_ratio_range is not None:
            self.ASPECT_RATIO_MIN, self.ASPECT_RATIO_MAX = aspect_ratio_range

    def extract_images(
        self,
        document_path: str,
        converter_result=None,
        image_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract images from a document using Docling's referenced export.

        Args:
            document_path: Path to the source document
            converter_result: Optional pre-existing Docling result
            image_dir: Optional path to a directory already populated with
                       exported images (e.g. from the parser's referenced-mode
                       export).  When provided the export step is skipped.

        Returns:
            List of dicts, each containing:
                - image_id: unique hash-based identifier
                - image_bytes: raw PNG binary data
                - source_page: page number (1-based)
                - source_section: enclosing heading text
                - caption: figure caption if present
                - surrounding_text: nearby text for context
                - bbox: bounding box dict {l, t, r, b, width, height, area}
                - resolution: "WxH" string
                - format: "PNG"
                - file_size_kb: size of image data
        """
        doc_path = Path(document_path)
        doc_filename = doc_path.name

        # Convert document with image extraction if no result provided
        if converter_result is None:
            converter_result = self._convert_with_images(doc_path)

        document = converter_result.document

        # Determine the image directory to use.
        #
        # When the parser already ran export_to_markdown(image_mode="referenced",
        # image_dir=...) the images are on disk in a persistent directory AND the
        # in-memory PIL images are still attached to each PictureItem element.
        # We can skip the export step entirely and read from that directory.
        #
        # When no pre-populated directory is provided we fall back to the old
        # behaviour: create a temp directory, export images there, then clean up.
        if image_dir is not None:
            pre_populated_dir = Path(image_dir)
            return self._extract_from_dir(document, doc_path, doc_filename, pre_populated_dir)

        # Fallback: export to a temp dir (no pre-populated dir available)
        with tempfile.TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir) / "images"
            export_dir.mkdir(parents=True, exist_ok=True)

            # Export with referenced mode so Docling saves images to export_dir
            try:
                document.export_to_markdown(
                    image_mode="referenced",
                    image_dir=export_dir,
                )
            except TypeError:
                document.export_to_markdown(image_mode="referenced")

            return self._extract_from_dir(document, doc_path, doc_filename, export_dir)

    def _extract_from_dir(
        self,
        document,
        doc_path: Path,
        doc_filename: str,
        image_dir: Path,
    ) -> List[Dict[str, Any]]:
        """
        Iterate document.pictures, apply area/ratio filters, and collect image
        bytes from *image_dir* (which must already contain the exported files).
        """
        extracted = []
        img_counter = 0
        pictures = list(document.pictures)
        total_pictures = len(pictures)
        skipped_area = 0
        skipped_ratio = 0
        skipped_no_prov = 0

        print(f"   [IMAGE]  Found {total_pictures} picture(s) in document")

        # DOCX can contain images without page-level provenance in Docling.
        # In that case fall back to reading raster images directly from the package.
        has_any_prov = any(getattr(el, "prov", None) for el in pictures)
        if total_pictures > 0 and not has_any_prov and doc_path.suffix.lower() == ".docx":
            print("   WARNING  No picture provenance in DOCX parse, using package-media fallback")
            extracted = self._extract_docx_raster_images(doc_path, doc_filename)
            print(
                f"   OK Kept {len(extracted)}/{total_pictures} images "
                "(DOCX fallback mode)"
            )
            return extracted

        for i, element in enumerate(pictures):
            if not element.prov or len(element.prov) == 0:
                skipped_no_prov += 1
                continue

            # Get bounding box and calculate area.
            # In PDF coordinate space the origin is bottom-left, so bbox.b < bbox.t
            # (y increases upward). Use abs() to get positive dimensions.
            bbox_obj = element.prov[0].bbox
            page_no = element.prov[0].page_no

            width = abs(bbox_obj.r - bbox_obj.l)
            height = abs(bbox_obj.b - bbox_obj.t)
            area = width * height
            aspect_ratio = (width / height) if height > 0 else 0

            # Filter 1: skip small images (logos, icons)
            if area < self.area_threshold:
                skipped_area += 1
                print(
                    f"      SKIP image {i} (p.{page_no}): "
                    f"area={area:.0f} < {self.area_threshold} (too small)"
                )
                continue

            # Filter 2: skip extreme aspect ratios (banners, sidebars)
            if not (self.ASPECT_RATIO_MIN < aspect_ratio < self.ASPECT_RATIO_MAX):
                skipped_ratio += 1
                print(
                    f"      SKIP image {i} (p.{page_no}): "
                    f"aspect_ratio={aspect_ratio:.2f} outside "
                    f"({self.ASPECT_RATIO_MIN}–{self.ASPECT_RATIO_MAX})"
                )
                continue

            img_counter += 1
            print(
                f"      KEEP image {i} (p.{page_no}): "
                f"area={area:.0f}, ratio={aspect_ratio:.2f}"
            )

            image_bytes = self._get_image_bytes_from_export(element, image_dir, img_counter)
            if image_bytes is None:
                continue

            content_hash = hashlib.md5(image_bytes).hexdigest()[:8]
            image_id = f"img_{img_counter:03d}_{content_hash}"

            section = self._get_enclosing_section(element, document)
            caption = self._get_caption(element)
            surrounding = self._get_surrounding_text(element, document)
            resolution = self._get_resolution(image_bytes)
            file_size_kb = round(len(image_bytes) / 1024, 2)

            bbox_meta = {
                "l": bbox_obj.l,
                "t": bbox_obj.t,
                "r": bbox_obj.r,
                "b": bbox_obj.b,
                "width": width,
                "height": height,
                "area": area,
                "aspect_ratio": round(aspect_ratio, 3),
            }

            extracted.append({
                "image_id": image_id,
                "source_document": doc_filename,
                "image_bytes": image_bytes,
                "source_page": page_no,
                "source_section": section,
                "caption": caption,
                "surrounding_text": surrounding,
                "bbox": bbox_meta,
                "resolution": resolution,
                "format": "PNG",
                "file_size_kb": file_size_kb,
                # Absolute path on disk so callers can reference the file directly.
                "file_path": str(image_dir / f"img_{img_counter:03d}_{content_hash}.png"),
            })

        if not extracted and doc_path.suffix.lower() == ".docx":
            print(
                "   WARNING  No images kept from Docling extraction, "
                "using DOCX package-media fallback"
            )
            fallback_images = self._extract_docx_raster_images(doc_path, doc_filename)
            if fallback_images:
                print(
                    f"   OK Recovered {len(fallback_images)} image(s) "
                    "from DOCX package-media fallback"
                )
                return fallback_images

        print(
            f"   OK Kept {len(extracted)}/{total_pictures} images "
            f"(skipped {skipped_area} small, {skipped_ratio} bad ratio, "
            f"{skipped_no_prov} missing provenance)"
        )
        return extracted

    def _convert_with_images(self, doc_path: Path):
        """Run Docling conversion with image extraction enabled."""
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = self.images_scale

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                ),
            }
        )
        return converter.convert(str(doc_path))

    def _get_image_bytes_from_export(
        self, element: "PictureItem", image_dir: Path, counter: int
    ) -> Optional[bytes]:
        """
        Get image bytes from Docling's exported files.

        Docling exports images with internal naming. We try to match by:
        1. Looking for the PIL image object in the element
        2. Falling back to reading files from the export directory
        """
        # Try to get the PIL image directly from the element
        image = getattr(element, "image", None)
        if image is not None:
            pil_image = getattr(image, "pil_image", None) or image
            try:
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                pass

        # Fallback: try to find the exported file
        # Docling typically names them sequentially
        png_files = sorted(image_dir.glob("*.png"))
        if png_files:
            index = min(max(counter - 1, 0), len(png_files) - 1)
            try:
                return png_files[index].read_bytes()
            except Exception:
                pass

        return None

    def _extract_docx_raster_images(self, doc_path: Path, doc_filename: str) -> List[Dict[str, Any]]:
        """
        Fallback extractor for DOCX files with missing picture provenance.

        Reads `/word/media/*` entries and keeps only raster image formats.
        Vector formats like EMF/WMF are skipped because they are not reliably
        decodable by Pillow in this pipeline.
        """
        extension_to_format = {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".bmp": "BMP",
            ".gif": "GIF",
            ".tif": "TIFF",
            ".tiff": "TIFF",
            ".webp": "WEBP",
        }
        extracted: List[Dict[str, Any]] = []
        skipped_unsupported = 0
        counter = 0

        try:
            with zipfile.ZipFile(doc_path, "r") as zf:
                media_entries = sorted(
                    name for name in zf.namelist() if name.startswith("word/media/")
                )

                for entry in media_entries:
                    ext = Path(entry).suffix.lower()
                    img_format = extension_to_format.get(ext)
                    if not img_format:
                        skipped_unsupported += 1
                        continue

                    image_bytes = zf.read(entry)
                    if not image_bytes:
                        continue

                    counter += 1
                    content_hash = hashlib.md5(image_bytes).hexdigest()[:8]
                    image_id = f"img_{counter:03d}_{content_hash}"
                    resolution = self._get_resolution(image_bytes)
                    file_size_kb = round(len(image_bytes) / 1024, 2)

                    extracted.append({
                        "image_id": image_id,
                        "source_document": doc_filename,
                        "image_bytes": image_bytes,
                        "source_page": None,
                        "source_section": None,
                        "caption": None,
                        "surrounding_text": None,
                        "bbox": None,
                        "resolution": resolution,
                        "format": img_format,
                        "file_size_kb": file_size_kb,
                    })
        except Exception:
            return []

        if skipped_unsupported > 0:
            print(f"      Skipped {skipped_unsupported} unsupported DOCX media objects")

        return extracted

    @staticmethod
    def _get_enclosing_section(element, document) -> Optional[str]:
        """Find the nearest heading above this element."""
        try:
            parent = getattr(element, "parent", None)
            while parent is not None:
                label = getattr(parent, "label", "")
                if "heading" in str(label).lower() or "section" in str(label).lower():
                    text = getattr(parent, "text", None)
                    if text:
                        return text[:200]
                parent = getattr(parent, "parent", None)
        except Exception:
            pass
        return None

    @staticmethod
    def _get_caption(element) -> Optional[str]:
        """Extract caption from a PictureItem."""
        caption = getattr(element, "caption", None)
        if caption:
            text = getattr(caption, "text", None) or str(caption)
            return text[:500] if text else None

        # caption_text is a METHOD on FloatingItem, must call it
        caption_text_method = getattr(element, "caption_text", None)
        if caption_text_method and callable(caption_text_method):
            try:
                text = caption_text_method()
                if text:
                    return str(text)[:500]
            except Exception:
                pass  # Method call failed, continue to fallback

        return None

    @staticmethod
    def _get_surrounding_text(element, document, chars: int = 300) -> Optional[str]:
        """Get text before and after this element for context."""
        try:
            all_items = list(document.iterate_items())
            for idx, (item, _level) in enumerate(all_items):
                if item is element:
                    texts = []
                    # Look at 2 items before
                    for j in range(max(0, idx - 2), idx):
                        prev_item = all_items[j][0]
                        prev_text = getattr(prev_item, "text", "")
                        if prev_text and not isinstance(prev_item, PictureItem):
                            texts.append(prev_text[:chars // 2])
                    # Look at 2 items after
                    for j in range(idx + 1, min(len(all_items), idx + 3)):
                        next_item = all_items[j][0]
                        next_text = getattr(next_item, "text", "")
                        if next_text and not isinstance(next_item, PictureItem):
                            texts.append(next_text[:chars // 2])
                    return " [...] ".join(texts) if texts else None
        except Exception:
            pass
        return None

    @staticmethod
    def _get_resolution(image_bytes: bytes) -> Optional[str]:
        """Get image resolution as 'WxH' string."""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            return f"{img.width}x{img.height}"
        except Exception:
            return None
