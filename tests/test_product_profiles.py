"""Product profile discovery and validation without external services."""

import json
import tempfile
import unittest
from pathlib import Path

from agents.blueprint.tools.product_profile_loader import ProductProfileLoader, validate_profile
from shared.product_registry import ProductRegistry


class ProductProfileTests(unittest.TestCase):
    def test_private_profile_is_discovered_and_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = {
                "product": "ExampleGateway",
                "metadata": {"aliases": ["gateway"]},
                "global": {"planning_instructions": {"special_notes": "Use source documents"}},
                "sections": [
                    {"section_id": "overview", "section_number": "1", "title": "Overview"},
                    {"section_id": "deployment", "section_number": "2", "title": "Deployment"},
                ],
            }
            (root / "ExampleGateway.json").write_text(json.dumps(profile), encoding="utf-8")
            (root / "WrongName.json").write_text(json.dumps(profile), encoding="utf-8")

            loader = ProductProfileLoader(root)
            self.assertEqual(loader.list_products(), ["ExampleGateway"])
            self.assertEqual(loader.load_product_profile("ExampleGateway").to_dict()["sections"], profile["sections"])
            self.assertEqual(loader.find_product_for_keywords(["gateway"]), "ExampleGateway")
            self.assertTrue(ProductRegistry.validate_product_id("ExampleGateway", root))
            self.assertFalse(ProductRegistry.validate_product_id("WrongName", root))

    def test_invalid_sections_and_product_id_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "sections must be a non-empty array"):
            validate_profile({"product": "ExampleGateway", "sections": []})
        with self.assertRaisesRegex(ValueError, "duplicate section_id"):
            validate_profile({"product": "ExampleGateway", "sections": [
                {"section_id": "same", "section_number": "1", "title": "One"},
                {"section_id": "same", "section_number": "2", "title": "Two"},
            ]})
        with self.assertRaisesRegex(ValueError, "Invalid product ID"):
            ProductProfileLoader(Path("unused")).load_product_profile("../outside")


if __name__ == "__main__":
    unittest.main()
