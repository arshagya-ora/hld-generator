"""
Pydantic models for image extraction and analysis.

Kept separate from the main DocumentKnowledgeBase models to avoid
coupling the image module into the core pipeline until fully integrated.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class VisionAnalysis(BaseModel):
    """AI vision analysis of one image — facts only, no verdicts."""

    type: str = Field(
        "unknown",
        description="Diagram type: network_topology, component_diagram, "
        "deployment_diagram, flow_chart, architecture_diagram, "
        "sequence_diagram, table_screenshot, other",
    )
    components_shown: List[str] = Field(
        default_factory=list,
        description="Products/systems/elements visible in the image",
    )
    text_elements: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Extracted text grouped by category: site_names, ip_addresses, labels",
    )
    purpose: str = Field("", description="What this diagram illustrates")
    technical_depth: str = Field(
        "unknown", description="overview | detailed | reference"
    )
    relationships_shown: List[str] = Field(
        default_factory=list,
        description="Connections/flows/relationships depicted",
    )
    diagram_complexity: str = Field("unknown", description="low | medium | high")
    professional_quality: str = Field("unknown", description="low | medium | high")


class ImageMetadata(BaseModel):
    """Complete metadata + analysis for one extracted image."""

    image_id: str = Field(..., description="Unique image identifier")
    source_document: str = Field(..., description="Source document filename")
    source_page: Optional[int] = Field(None, description="Page number in source")
    source_section: Optional[str] = Field(None, description="Enclosing section heading")
    caption: Optional[str] = Field(None, description="Figure caption if present")
    surrounding_text: Optional[str] = Field(None, description="Context text near the image")
    bbox: Optional[Dict[str, float]] = Field(
        None,
        description="Bounding box: {l, t, r, b, width, height, area} in points",
    )
    storage_path: Optional[str] = Field(None, description="Local filesystem path")
    resolution: Optional[str] = Field(None, description="Width x Height pixels")
    format: str = Field("PNG", description="Image format")
    file_size_kb: Optional[float] = Field(None, description="File size in KB")
    vision_analysis: Optional[VisionAnalysis] = Field(
        None, description="AI analysis results"
    )


class ImageInventory(BaseModel):
    """Complete image inventory — no filtering, no verdicts, just facts."""

    images: List[ImageMetadata] = Field(
        default_factory=list, description="All extracted images with metadata"
    )
    total_images_extracted: int = Field(0)
    images_analyzed_by_vision: int = Field(0)
    images_stored: int = Field(0)
    images_indexed_in_cognee: int = Field(0)
