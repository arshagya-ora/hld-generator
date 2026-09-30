"""
Product Registry — Canonical product IDs and dataset types for HLD Generator.

The product ID is the filename stem of a local product profile JSON.
This is the single source of truth for product identification across all agents.

Two dataset types exist per product in RAG-Anything:
  - product_docs   : Technical product documentation (specs, architecture guides)
  - reference_hlds : Past completed HLDs for this product (reference material)

Storage layout:
  rag_storage/
    5G_SBA/
      product_docs/        ← RAG-Anything store for 5G_SBA technical docs
      reference_hlds/      ← RAG-Anything store for past 5G_SBA HLDs
    DSR/
      product_docs/
      reference_hlds/

Adding a new product:
  1. Create product_profiles/NewProduct.json outside version control
  2. Run ingestion CLI to seed product_docs and reference_hlds
  3. No code changes required
"""

import logging
import os
import re
from enum import Enum
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRODUCT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _profile_dir() -> Path:
    configured = Path(os.getenv("PRODUCT_PROFILE_DIR", "product_profiles")).expanduser()
    return configured if configured.is_absolute() else _PROJECT_ROOT / configured


class DatasetType(str, Enum):
    """
    RAG-Anything dataset types available per product.

    Used to select the correct isolated store when querying or ingesting.
    """
    PRODUCT_DOCS = "product_docs"
    REFERENCE_HLDS = "reference_hlds"


class ProductRegistry:
    """
    Central registry for product IDs and their RAG-Anything dataset paths.

    Product IDs are derived dynamically from local product profile filenames.

    Usage:
        # Get working dir for a product dataset
        wd = ProductRegistry.get_working_dir("./rag_storage", "5G_SBA", DatasetType.PRODUCT_DOCS)
        # → "./rag_storage/5G_SBA/product_docs"

        # List all registered products
        products = ProductRegistry.list_products()
        # → ["5G_SBA", "DSR"]

        # Validate before use
        if not ProductRegistry.validate_product_id("5G_SBA"):
            raise ValueError("Unknown product")
    """

    @staticmethod
    def get_working_dir(
        base_dir: str,
        product_id: str,
        dataset_type: "str | DatasetType",
    ) -> str:
        """
        Return the RAG-Anything working directory for a product/dataset combination.

        Args:
            base_dir:     Base RAG storage directory (e.g. "./rag_storage")
            product_id:   Canonical product ID (e.g. "5G_SBA", "DSR")
            dataset_type: Dataset type — DatasetType enum or raw string

        Returns:
            Path string: "{base_dir}/{product_id}/{dataset_type}"
        """
        dt = dataset_type.value if isinstance(dataset_type, DatasetType) else dataset_type
        return str(Path(base_dir) / product_id / dt)

    @staticmethod
    def list_products(profile_dir: Optional[Path] = None) -> List[str]:
        """
        Discover registered products by scanning profile JSON files.

        Args:
            profile_dir: Override profile directory. Defaults to PRODUCT_PROFILE_DIR.

        Returns:
            Sorted list of product IDs (e.g. ["5G_SBA", "DSR"])
        """
        from agents.blueprint.tools.product_profile_loader import ProductProfileLoader

        root = Path(profile_dir) if profile_dir is not None else _profile_dir()
        products = ProductProfileLoader(profile_dir=root).list_products()
        logger.debug(f"ProductRegistry: discovered products: {products}")
        return products

    @staticmethod
    def validate_product_id(
        product_id: str,
        profile_dir: Optional[Path] = None,
    ) -> bool:
        """
        Validate that a product ID has a corresponding profile JSON file.

        Args:
            product_id: Product ID to validate (e.g. "5G_SBA")
            profile_dir: Override profile directory

        Returns:
            True if <product_id>.json exists, False otherwise
        """
        if not _PRODUCT_ID.fullmatch(product_id):
            return False
        root = Path(profile_dir) if profile_dir is not None else _profile_dir()
        profile_file = root / f"{product_id}.json"
        exists = product_id in ProductRegistry.list_products(root)
        if not exists:
            logger.warning(
                f"ProductRegistry: no profile file found for product '{product_id}' "
                f"(expected {profile_file})"
            )
        return exists

    @staticmethod
    def list_datasets(product_id: str, base_dir: str) -> List[str]:
        """
        List dataset directories that exist on disk for a product.

        Args:
            product_id: Product ID
            base_dir:   Base RAG storage directory

        Returns:
            List of DatasetType values that have been initialized on disk
        """
        product_dir = Path(base_dir) / product_id
        if not product_dir.exists():
            return []

        found = []
        for dt in DatasetType:
            if (product_dir / dt.value).exists():
                found.append(dt.value)
        return found
