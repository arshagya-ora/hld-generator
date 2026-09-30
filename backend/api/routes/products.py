"""List products that have a valid local product profile JSON."""

from fastapi import APIRouter, Depends, HTTPException, status

from schemas.product import ProductResponse, ProductListResponse
from auth.dependencies import get_current_active_user
from models.user import User
from services.product_profile_catalog import get_profile_loader

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _response_for(product_id: str) -> ProductResponse:
    profile = get_profile_loader().load_product_profile(product_id)
    name = product_id.replace("_", " ")
    description = profile.metadata.get("description") if isinstance(profile.metadata, dict) else None
    return ProductResponse(
        id=product_id,
        name=name,
        description=description or f"HLD generation for {name}",
        profile_file=f"{product_id}.json",
    )


@router.get("", response_model=ProductListResponse)
async def list_products(current_user: User = Depends(get_current_active_user)):
    loader = get_profile_loader()
    products = [_response_for(product_id) for product_id in loader.list_products()]
    products.sort(key=lambda product: product.name)
    return ProductListResponse(products=products, count=len(products))


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    current_user: User = Depends(get_current_active_user),
):
    loader = get_profile_loader()
    if product_id not in loader.list_products():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_id}' not found",
        )
    return _response_for(product_id)
