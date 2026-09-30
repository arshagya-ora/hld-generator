"""
Knowledge Merger for Document Analyzer Agent.

Merges multiple chunk extraction results into a unified DocumentKnowledgeBase
without losing data or creating conflicts.
"""

from typing import List, Dict, Any, Optional, Union
from collections import defaultdict

from hld_generator.shared.logging_config import setup_logger
from hld_generator.agents.document_analyzer.state.models import (
    DocumentKnowledgeBase,
    DocumentIntelligence,
    ProductInfo,
    SiteInfo,
    CapacityInfo,
)

logger = setup_logger(__name__)


class KnowledgeMerger:
    """
    Merges chunk extraction results into unified knowledge base.

    Handles conflicts intelligently using union strategies, preferring
    inclusion over exclusion to avoid data loss.

    Usage:
        merger = KnowledgeMerger()
        kb = merger.merge_all(chunk_extractions)
    """

    def merge_all(self, chunk_results: List[Dict[str, Any]]) -> DocumentKnowledgeBase:
        """
        Merge all chunk extraction results into single knowledge base.

        Args:
            chunk_results: List of partial DocumentKnowledgeBase dicts from LLM

        Returns:
            Complete merged DocumentKnowledgeBase
        """
        if not chunk_results:
            logger.warning("No chunk results to merge, returning empty knowledge base")
            return DocumentKnowledgeBase(
                document_intelligence=DocumentIntelligence(
                    document_type="Unknown",
                    customer=None,
                    project_name=None,
                    primary_products=[],
                    confidence_score=0.0,
                )
            )

        logger.info(f"Merging {len(chunk_results)} chunk extraction results")

        # Merge each field type using specialized strategies
        merged = {
            "document_intelligence": self._merge_document_intelligence(chunk_results),
            "project_overview": self._merge_project_overview(chunk_results),
            "products": self._merge_products(chunk_results),
            "sites": self._merge_sites(chunk_results),
            "capacity_and_sizing": self._merge_capacity(chunk_results),
            "network_and_integration": self._merge_dict_field(chunk_results, "network_and_integration"),
            "deployment_plan": self._merge_dict_field(chunk_results, "deployment_plan"),
            "infrastructure": self._merge_dict_field(chunk_results, "infrastructure"),
            "timeline": self._merge_dict_field(chunk_results, "timeline"),
            "diagrams": self._merge_list_field(chunk_results, "diagrams"),
            "tables": [],  # Tables injected separately (from Docling)
            "special_notes": self._merge_list_field(chunk_results, "special_notes"),
            "knowledge_graph_stats": self._build_stats(chunk_results),
            "extraction_metadata": self._build_metadata(chunk_results),
        }

        logger.info(
            f"Merged knowledge base: "
            f"{len(merged.get('products', {}))} products, "
            f"{len(merged.get('sites', []))} sites, "
            f"{len(merged.get('special_notes', []))} notes"
        )

        # Post-processing: populate site capacity from capacity_and_sizing if missing
        sites = merged.get("sites", [])
        capacity_sizing = merged.get("capacity_and_sizing")

        # Handle both CapacityInfo (Pydantic model) and dict types
        if capacity_sizing:
            if isinstance(capacity_sizing, CapacityInfo):
                peak_tps = capacity_sizing.peak_tps
                concurrent_sessions = capacity_sizing.concurrent_sessions
            else:
                peak_tps = capacity_sizing.get("peak_tps")
                concurrent_sessions = capacity_sizing.get("concurrent_sessions")
        else:
            peak_tps = None
            concurrent_sessions = None

        for site in sites:
            if isinstance(site, dict) and not site.get("capacity") and (peak_tps or concurrent_sessions):
                # Build capacity string from global capacity_and_sizing
                capacity_parts = []
                if peak_tps:
                    capacity_parts.append(str(peak_tps))
                if concurrent_sessions:
                    capacity_parts.append(str(concurrent_sessions))
                if capacity_parts:
                    site["capacity"] = ", ".join(capacity_parts)
                    logger.debug(f"   Populated capacity for site '{site.get('name', 'unknown')}' from capacity_and_sizing")

        # Convert to Pydantic model
        return DocumentKnowledgeBase(**merged)

    def _merge_document_intelligence(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> DocumentIntelligence:
        """
        Merge document intelligence fields.

        Strategy: Use first non-empty chunk (usually from introduction/first chunk).
        For primary_products, union all mentioned products.
        """
        doc_type = "Unknown"
        customer = None
        project_name = None
        primary_products_set = set()
        confidence_scores = []

        for chunk in chunk_results:
            doc_intel = chunk.get("document_intelligence", {})
            if not doc_intel:
                continue

            # Take first non-empty values
            if doc_type == "Unknown" and doc_intel.get("document_type"):
                doc_type = doc_intel["document_type"]

            if not customer and doc_intel.get("customer"):
                customer = doc_intel["customer"]

            if not project_name and doc_intel.get("project_name"):
                project_name = doc_intel["project_name"]

            # Union all products
            products = doc_intel.get("primary_products", [])
            if isinstance(products, list):
                primary_products_set.update(products)

            # Collect confidence scores
            conf = doc_intel.get("confidence_score") or doc_intel.get("confidence")
            if conf is not None:
                try:
                    confidence_scores.append(float(conf))
                except (ValueError, TypeError):
                    pass

        # Average confidence
        avg_confidence = (
            sum(confidence_scores) / len(confidence_scores)
            if confidence_scores else 0.0
        )

        return DocumentIntelligence(
            document_type=doc_type,
            customer=customer,
            project_name=project_name,
            primary_products=list(primary_products_set),
            confidence_score=round(avg_confidence, 2),
        )

    def _merge_project_overview(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge project overview fields.

        Strategy: Merge all non-null fields, union list fields.
        """
        merged = {}

        for chunk in chunk_results:
            overview = chunk.get("project_overview", {})
            if not overview:
                continue

            # String fields: take first non-empty
            for field in ["scope", "description"]:
                if field in overview and overview[field] and not merged.get(field):
                    merged[field] = overview[field]

            # List fields: union
            for field in ["objectives", "business_drivers", "deliverables"]:
                if field in overview and isinstance(overview[field], list):
                    existing = merged.get(field, [])
                    merged[field] = self._union_lists(existing, overview[field])

        return merged

    def _merge_products(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> Dict[str, ProductInfo]:
        """
        Merge product dictionaries.

        Strategy: Union all products by name, merge attributes for same product.
        """
        merged_products = {}

        for chunk in chunk_results:
            products = chunk.get("products", {})
            if not products or not isinstance(products, dict):
                continue

            for product_name, product_info in products.items():
                if not isinstance(product_info, dict):
                    continue

                if product_name not in merged_products:
                    # New product
                    merged_products[product_name] = ProductInfo(
                        name=product_name,
                        **{
                            k: v for k, v in product_info.items()
                            if k in ProductInfo.__fields__ and k != "name"
                        }
                    )
                else:
                    # Merge with existing
                    existing = merged_products[product_name]

                    # String fields: take non-null
                    for field in ["purpose", "version", "architecture", "deployment_model"]:
                        if not getattr(existing, field) and product_info.get(field):
                            setattr(existing, field, product_info[field])

                    # List fields: union
                    for field in ["components", "interfaces"]:
                        existing_list = getattr(existing, field) or []
                        new_list = product_info.get(field, [])
                        if isinstance(new_list, list):
                            setattr(existing, field, self._union_lists(existing_list, new_list))

        return merged_products

    def _merge_sites(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> List[SiteInfo]:
        """
        Merge site lists.

        Strategy: Deduplicate by normalized site name, merge attributes.
        """
        site_dict = {}

        for chunk in chunk_results:
            sites = chunk.get("sites", [])
            if not sites or not isinstance(sites, list):
                continue

            for site in sites:
                if not isinstance(site, dict):
                    continue

                # Normalize site name as key
                name = site.get("name", "").strip()
                if not name:
                    continue

                key = name.lower()

                if key not in site_dict:
                    # New site
                    site_dict[key] = SiteInfo(
                        name=name,
                        **{
                            k: v for k, v in site.items()
                            if k in SiteInfo.__fields__ and k != "name"
                        }
                    )
                else:
                    # Merge with existing
                    existing = site_dict[key]

                    # String fields: take non-null
                    for field in ["location", "site_type", "role", "capacity"]:
                        if not getattr(existing, field) and site.get(field):
                            setattr(existing, field, site[field])

                    # deployed_components: union
                    existing_components = existing.deployed_components or []
                    new_components = site.get("deployed_components", [])
                    if isinstance(new_components, list):
                        existing.deployed_components = self._union_lists(
                            existing_components, new_components
                        )

        return list(site_dict.values())

    def _merge_capacity(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> Optional[CapacityInfo]:
        """
        Merge capacity and sizing info.

        Strategy: For string/dict fields, prefer dict > string > null.
        For nested dicts, merge recursively.
        """
        merged = None

        for chunk in chunk_results:
            cap = chunk.get("capacity_and_sizing")
            if not cap:
                continue

            if merged is None:
                # First capacity info found
                merged = CapacityInfo(**{
                    k: v for k, v in cap.items()
                    if k in CapacityInfo.__fields__
                })
                continue

            # Merge fields
            for field in ["subscribers", "peak_tps", "concurrent_sessions",
                          "dimensioning_basis", "growth_projections"]:
                current = getattr(merged, field)
                new = cap.get(field)

                if not current:
                    setattr(merged, field, new)
                elif isinstance(new, dict) and isinstance(current, str):
                    # Upgrade from string to dict (site-specific data)
                    setattr(merged, field, new)
                elif isinstance(new, dict) and isinstance(current, dict):
                    # Merge dicts
                    current.update(new)

            # Merge dict fields
            for field in ["vm_requirements", "hardware_specs"]:
                current = getattr(merged, field) or {}
                new = cap.get(field, {})
                if isinstance(new, dict):
                    current.update(new)
                    setattr(merged, field, current)

        return merged

    def _merge_dict_field(
        self,
        chunk_results: List[Dict[str, Any]],
        field_name: str
    ) -> Dict[str, Any]:
        """Generic dict field merger (for network_and_integration, deployment_plan, etc.)."""
        merged = {}

        for chunk in chunk_results:
            field_value = chunk.get(field_name, {})
            if not field_value or not isinstance(field_value, dict):
                continue

            # Recursively merge dicts
            for key, value in field_value.items():
                if key not in merged:
                    merged[key] = value
                elif isinstance(value, dict) and isinstance(merged[key], dict):
                    merged[key].update(value)
                elif isinstance(value, list) and isinstance(merged[key], list):
                    merged[key] = self._union_lists(merged[key], value)
                elif merged[key] is None:
                    merged[key] = value

        return merged

    def _merge_list_field(
        self,
        chunk_results: List[Dict[str, Any]],
        field_name: str
    ) -> List[Any]:
        """Generic list field merger (for special_notes, diagrams, etc.)."""
        merged_list = []
        seen_keys = set()

        for chunk in chunk_results:
            field_value = chunk.get(field_name, [])
            if not field_value or not isinstance(field_value, list):
                continue

            for item in field_value:
                # Create dedup key (first 100 chars for strings, full repr for dicts)
                if isinstance(item, str):
                    key = item[:100].lower().strip()
                elif isinstance(item, dict):
                    # For diagrams/complex items, use a stable key
                    key = str(sorted(item.items()))[:100]
                else:
                    key = str(item)[:100]

                if key not in seen_keys:
                    merged_list.append(item)
                    seen_keys.add(key)

        return merged_list

    def _union_lists(self, list1: List[Any], list2: List[Any]) -> List[Any]:
        """Union two lists, deduplicating by normalized string comparison."""
        if not list2:
            return list1
        if not list1:
            return list2

        # Convert to normalized strings for comparison
        seen = {str(item).lower().strip() for item in list1}
        result = list1.copy()

        for item in list2:
            key = str(item).lower().strip()
            if key and key not in seen:
                result.append(item)
                seen.add(key)

        return result

    def _build_stats(self, chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build knowledge_graph_stats metadata."""
        return {
            "extraction_method": "direct_llm_semantic_chunking",
            "chunk_count": len(chunk_results),
            "llm_calls": len(chunk_results),
            "chunks_with_products": sum(
                1 for c in chunk_results if c.get("products")
            ),
            "chunks_with_sites": sum(
                1 for c in chunk_results if c.get("sites")
            ),
            "chunks_with_capacity": sum(
                1 for c in chunk_results if c.get("capacity_and_sizing")
            ),
        }

    def _build_metadata(self, chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build extraction_metadata."""
        return {
            "extraction_source": "semantic_chunks",
            "chunk_count": len(chunk_results),
            "merge_strategy": "union_with_conflict_resolution",
            "merge_conflicts": 0,  # TODO: Track conflicts during merge
        }


def validate_knowledge_base(kb: DocumentKnowledgeBase) -> Dict[str, Any]:
    """
    Validate merged knowledge base completeness.

    Args:
        kb: Merged DocumentKnowledgeBase

    Returns:
        Dict with completeness_score and missing_items
    """
    checks = {
        "has_product_info": len(kb.products) > 0,
        "has_doc_intelligence": kb.document_intelligence.document_type != "Unknown",
        "has_sites": len(kb.sites) > 0,
        "has_capacity": kb.capacity_and_sizing is not None,
        "has_infrastructure": bool(kb.infrastructure),
        "has_deployment_plan": bool(kb.deployment_plan),
    }

    score = sum(checks.values()) / len(checks)
    missing = [key for key, passed in checks.items() if not passed]

    logger.info(f"Knowledge base completeness: {score:.1%} ({len(missing)} missing items)")

    return {
        "score": round(score, 2),
        "missing_items": missing,
        "checks": checks,
    }
