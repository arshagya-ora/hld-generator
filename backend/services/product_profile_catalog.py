"""Resolve the local product profile directory for API routes."""

from pathlib import Path

from agents.blueprint.tools.product_profile_loader import ProductProfileLoader
from config import settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_profile_loader() -> ProductProfileLoader:
    directory = Path(settings.PRODUCT_PROFILE_DIR).expanduser()
    if not directory.is_absolute():
        directory = _PROJECT_ROOT / directory
    return ProductProfileLoader(profile_dir=directory)
