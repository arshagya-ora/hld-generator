"""Load local product profile JSON files for HLD planning.

A product profile describes document sections and generation guidance. It is not
the document-derived knowledge model or a retrieval index.
"""

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PRODUCT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def profile_root() -> Path:
    """Return the configured profile directory, relative to the project root."""
    configured = os.getenv("PRODUCT_PROFILE_DIR", "product_profiles")
    root = Path(configured).expanduser()
    return root if root.is_absolute() else _PROJECT_ROOT / root


def validate_profile(data: Any, expected_product: Optional[str] = None) -> None:
    """Raise ValueError for a profile the blueprint planner cannot use."""
    if not isinstance(data, dict):
        raise ValueError("A product profile must be a JSON object")
    product = data.get("product")
    if not isinstance(product, str) or not _PRODUCT_ID.fullmatch(product):
        raise ValueError("product must be an ID using letters, digits, and underscores")
    if expected_product is not None and product != expected_product:
        raise ValueError(f"product must match the filename: {expected_product}")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections must be a non-empty array")
    seen = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError(f"sections[{index}] must be an object")
        for key in ("section_id", "section_number", "title"):
            if not isinstance(section.get(key), str) or not section[key].strip():
                raise ValueError(f"sections[{index}].{key} must be a non-empty string")
        if section["section_id"] in seen:
            raise ValueError(f"duplicate section_id: {section['section_id']}")
        seen.add(section["section_id"])
    for key in ("metadata", "global"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"{key} must be an object")
    if "past_tocs" in data and not isinstance(data["past_tocs"], list):
        raise ValueError("past_tocs must be an array")
    for key in ("document_type", "version"):
        if key in data and not isinstance(data[key], (str, int, float)):
            raise ValueError(f"{key} must be a string or number")


@dataclass
class ProductProfile:
    product: str
    document_type: str = "HLD"
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)
    global_config: Dict[str, Any] = field(default_factory=dict)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    past_tocs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product": self.product,
            "document_type": self.document_type,
            "version": self.version,
            "metadata": self.metadata,
            "global": self.global_config,
            "sections": self.sections,
            "past_tocs": self.past_tocs,
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "product": self.product,
            "version": self.version,
            "total_sections": len(self.sections),
            "mandatory_sections": sum(not s.get("conditional", False) for s in self.sections),
            "conditional_sections": sum(bool(s.get("conditional", False)) for s in self.sections),
        }


class ProductProfileLoader:
    """Discover and load ``<product_id>.json`` files without caching."""

    def __init__(self, profile_dir: Optional[Path] = None):
        self.profile_dir = Path(profile_dir) if profile_dir is not None else profile_root()

    def list_products(self) -> List[str]:
        if not self.profile_dir.is_dir():
            return []
        products = []
        for path in sorted(self.profile_dir.glob("*.json")):
            if not _PRODUCT_ID.fullmatch(path.stem):
                continue
            try:
                self.load_product_profile(path.stem)
                products.append(path.stem)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring invalid product profile %s: %s", path, exc)
        return products

    def load_product_profile(self, product: str) -> ProductProfile:
        if not _PRODUCT_ID.fullmatch(product):
            raise ValueError("Invalid product ID")
        path = self.profile_dir / f"{product}.json"
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        validate_profile(data, expected_product=product)
        return ProductProfile(
            product=product,
            document_type=data.get("document_type", "HLD"),
            version=str(data.get("version", "1.0")),
            metadata=data.get("metadata", {}),
            global_config=data.get("global", {}),
            sections=data["sections"],
            past_tocs=data.get("past_tocs", []),
        )

    def find_product_for_keywords(self, keywords: List[str]) -> Optional[str]:
        products = self.list_products()
        keywords_lower = [keyword.lower() for keyword in keywords]
        for product in products:
            if product.lower() in keywords_lower:
                return product
        for product in products:
            for part in product.lower().replace("_", " ").split():
                if len(part) >= 3 and any(part in keyword for keyword in keywords_lower):
                    return product
        for product in products:
            aliases = self.load_product_profile(product).metadata.get("aliases", [])
            if isinstance(aliases, list) and any(
                isinstance(alias, str) and alias.lower() in keywords_lower for alias in aliases
            ):
                return product
        return None


def main(argv: List[str]) -> int:
    """Validate one product profile JSON from the command line."""
    if len(argv) != 2:
        print("Usage: python -m agents.blueprint.tools.product_profile_loader <profile.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        with path.open("r", encoding="utf-8") as handle:
            validate_profile(json.load(handle), expected_product=path.stem)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Invalid product profile: {exc}", file=sys.stderr)
        return 1
    print(f"Valid product profile: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
