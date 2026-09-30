"""
Product Schemas
Response models for product listing
"""
from pydantic import BaseModel, Field
from typing import List


class ProductResponse(BaseModel):
    """Response schema for a single product"""
    id: str = Field(..., description="Product ID (e.g., '5G_SBA')")
    name: str = Field(..., description="Human-readable product name")
    description: str = Field(..., description="Product description")
    profile_file: str = Field(..., description="Product profile JSON filename")


class ProductListResponse(BaseModel):
    """Response schema for product list"""
    products: List[ProductResponse] = Field(..., description="List of available products")
    count: int = Field(..., description="Total number of products")
