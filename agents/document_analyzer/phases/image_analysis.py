"""
Image Analysis Phase for the Document Analyzer Agent.

Orchestrates the full image pipeline:
    extract (Docling) → store (local) → analyze (OCI Vision) → index (Cognee)

Produces an ImageInventory with facts-only metadata for each image.
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from hld_generator.agents.document_analyzer.state.image_models import (
    VisionAnalysis,
    ImageMetadata,
    ImageInventory,
)
from hld_generator.agents.document_analyzer.tools.image_extractor import ImageExtractor
from hld_generator.shared.vision_wrapper import OCIVisionWrapper


class ImageAnalysisPhase:
    """
    Orchestrates image extraction → storage → vision analysis → indexing.

    This phase runs after document parsing and before Cognee indexing so that
    image metadata can be indexed alongside the document text.
    """

    def __init__(
        self,
        vision_wrapper: Optional[OCIVisionWrapper] = None,
        cognee_wrapper=None,
        image_extractor: Optional[ImageExtractor] = None,
    ):
        self.vision = vision_wrapper
        self.cognee = cognee_wrapper
        self.extractor = image_extractor or ImageExtractor()

    async def execute(
        self,
        document_path: str,
        project_id: str,
        dataset_name: str,
        converter_result=None,
        image_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the full image analysis pipeline.

        Args:
            document_path: Path to the source document
            project_id: Unique project/dataset identifier (used for storage paths)
            dataset_name: Cognee dataset name for indexing
            converter_result: Optional pre-existing Docling ConversionResult
            image_dir: Optional path to a directory already populated with
                       extracted images (from the parse node).  When provided
                       the extractor skips its own export step.

        Returns:
            Dict with:
                - image_inventory: ImageInventory model as dict
                - extracted_images: raw extraction data (for state)
        """
        print("\n[IMAGE]  Image Analysis Phase...")

        # 1. Extract images from document
        print("   Extracting images from document...")
        raw_images = self.extractor.extract_images(
            document_path, converter_result, image_dir=image_dir
        )
        total_extracted = len(raw_images)
        print(f"   OK Extracted {total_extracted} images")

        if total_extracted == 0:
            empty_inventory = ImageInventory(total_images_extracted=0)
            return {
                "image_inventory": empty_inventory.model_dump(),
                "extracted_images": [],
            }

        # 2. Process each image: store → analyze → build metadata
        # OPTIMIZATION: Parallelize Vision API calls (saves 15-25s for 10 images)
        print(f"   Processing {total_extracted} images (Vision API in parallel)...")

        async def process_single_image(idx, img_data):
            """Process one image: store locally + Vision API analysis"""
            image_id = img_data["image_id"]
            image_bytes = img_data.get("image_bytes")

            storage_path = None
            vision_analysis = None

            # 2a. Store locally
            if image_bytes:
                try:
                    from pathlib import Path
                    output_dir = Path("./images/source-docs") / project_id
                    output_dir.mkdir(parents=True, exist_ok=True)

                    image_format = img_data.get("format", "png").lower()
                    storage_path_obj = output_dir / f"{image_id}.{image_format}"
                    storage_path_obj.write_bytes(image_bytes)
                    storage_path = str(storage_path_obj)

                    print(f"      OK Stored {image_id} ({len(image_bytes) // 1024} KB)")
                except Exception as exc:
                    print(f"      WARNING  Storage failed for {image_id}: {exc}")

            # 2b. Vision analysis via OCI GenAI (parallel execution)
            if image_bytes and self.vision:
                try:
                    analysis_dict = await self.vision.analyze_image(
                        image_bytes, mime_type=f"image/{img_data.get('format', 'png').lower()}"
                    )
                    vision_analysis = VisionAnalysis(**analysis_dict)
                    print(f"      OK Vision analysis complete: {image_id} ({vision_analysis.type})")
                except Exception as exc:
                    print(f"      WARNING  Vision analysis failed for {image_id}: {exc}")

            # 2c. Build metadata entry
            metadata = ImageMetadata(
                image_id=image_id,
                source_document=img_data["source_document"],
                source_page=img_data.get("source_page"),
                source_section=img_data.get("source_section"),
                caption=img_data.get("caption"),
                surrounding_text=img_data.get("surrounding_text"),
                storage_path=storage_path,
                resolution=img_data.get("resolution"),
                format=img_data.get("format", "PNG"),
                file_size_kb=img_data.get("file_size_kb"),
                vision_analysis=vision_analysis,
            )
            return metadata

        # Execute all image processing in parallel
        import asyncio
        tasks = [process_single_image(idx, img_data) for idx, img_data in enumerate(raw_images, 1)]
        image_metadata_list = await asyncio.gather(*tasks)

        stored_count = len([m for m in image_metadata_list if m.storage_path])
        analyzed_count = len([m for m in image_metadata_list if m.vision_analysis])

        # 3. Index image metadata in Cognee
        indexed_count = 0
        if self.cognee and image_metadata_list:
            indexed_count = await self._index_in_cognee(
                image_metadata_list, dataset_name
            )

        # 4. Build inventory
        inventory = ImageInventory(
            images=image_metadata_list,
            total_images_extracted=total_extracted,
            images_analyzed_by_vision=analyzed_count,
            images_stored=stored_count,
            images_indexed_in_cognee=indexed_count,
        )

        print(f"\n   Image Analysis complete:")
        print(f"      Extracted: {total_extracted}")
        print(f"      Stored:    {stored_count}")
        print(f"      Analyzed:  {analyzed_count}")
        print(f"      Indexed:   {indexed_count}")

        return {
            "image_inventory": inventory.model_dump(),
            "extracted_images": [
                {k: v for k, v in img.items() if k != "image_bytes"}
                for img in raw_images
            ],
        }

    async def _index_in_cognee(
        self, images: list, dataset_name: str
    ) -> int:
        """
        Index image metadata as text documents in Cognee.

        OPTIMIZATION: Parallelize Cognee add_text calls (saves 0.5-1s for 10 images).
        """
        import asyncio

        async def index_single_image(metadata):
            try:
                text_repr = self._image_to_text(metadata)
                if text_repr and self.cognee:
                    await self.cognee.add_text(
                        text_repr,
                        dataset_name=dataset_name,
                        metadata={"type": "image_metadata", "image_id": metadata.image_id},
                    )
                    return 1
            except Exception:
                pass  # Non-fatal; image metadata indexing is best-effort
            return 0

        # Execute all Cognee indexing in parallel
        tasks = [index_single_image(metadata) for metadata in images]
        results = await asyncio.gather(*tasks)
        indexed = sum(results)

        return indexed

    @staticmethod
    def _image_to_text(metadata: ImageMetadata) -> str:
        """Convert image metadata into searchable text for Cognee."""
        parts = [f"[Image: {metadata.image_id}]"]

        if metadata.caption:
            parts.append(f"Caption: {metadata.caption}")
        if metadata.source_section:
            parts.append(f"Section: {metadata.source_section}")
        if metadata.surrounding_text:
            parts.append(f"Context: {metadata.surrounding_text}")

        if metadata.vision_analysis:
            va = metadata.vision_analysis
            parts.append(f"Diagram type: {va.type}")
            parts.append(f"Purpose: {va.purpose}")
            if va.components_shown:
                parts.append(f"Components: {', '.join(va.components_shown)}")
            if va.relationships_shown:
                parts.append(f"Relationships: {', '.join(va.relationships_shown)}")
            text_elements = va.text_elements
            for key, values in text_elements.items():
                if values:
                    parts.append(f"{key}: {', '.join(values)}")

        return "\n".join(parts)
