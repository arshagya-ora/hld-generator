"""
Multi-Product RAG-Anything Wrapper

Routes RAG queries and document ingestion to product-specific, isolated
RAG-Anything stores. Each product has two datasets:

  rag_storage/{product_id}/product_docs/    ← technical documentation
  rag_storage/{product_id}/reference_hlds/  ← past completed HLDs

This wrapper is the single entry point for all RAG-Anything interactions
in the pipeline. It lazy-initializes per-product RAG-Anything instances
and caches them for reuse across queries.

Usage (pipeline):
    wrapper = MultiProductRAGWrapper(oci_client=oci_client, base_working_dir="./rag_storage")
    results = await wrapper.aquery_for_product(query, "5G_SBA", "product_docs", param={...})

Usage (ingestion CLI):
    wrapper = MultiProductRAGWrapper(oci_client=oci_client, base_working_dir="./rag_storage")
    await wrapper.ingest_document("path/to/doc.pdf", "5G_SBA", DatasetType.PRODUCT_DOCS)
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from hld_generator.shared.product_registry import DatasetType, ProductRegistry
from hld_generator.shared.rag_anything_wrapper import RAGAnythingWrapper

logger = logging.getLogger(__name__)


class MultiProductRAGWrapper:
    """
    Manages per-product, per-dataset RAG-Anything stores.

    Architecture:
      - Each (product_id, dataset_type) pair maps to one RAGAnythingWrapper
      - Wrappers are lazy-initialized on first use
      - Cached for the lifetime of this object

    Thread safety:
      - Uses asyncio.Lock per (product_id, dataset_type) key during initialization
      - Safe for concurrent queries once initialized

    Backward compatibility:
      - `aquery(query, param)` fallback for callers that don't know the product
    """

    def __init__(
        self,
        oci_client,
        base_working_dir: str = "./rag_storage",
        embedding_model: str = "openai.text-embedding-3-large",
        chat_model: str = "openai.gpt-5.2-chat-latest",
    ):
        """
        Initialize the multi-product wrapper.

        Args:
            oci_client:        OCI OpenAI-compatible client
            base_working_dir:  Root directory for all RAG-Anything stores
            embedding_model:   OCI embedding model ID
            chat_model:        OCI chat model ID
        """
        self.oci_client = oci_client
        self.base_working_dir = base_working_dir
        self.embedding_model = embedding_model
        self.chat_model = chat_model

        # Cache: {product_id: {dataset_type_value: RAGAnythingWrapper}}
        self._wrappers: Dict[str, Dict[str, RAGAnythingWrapper]] = {}
        # Per-key init locks to prevent double-initialization under concurrent load
        self._init_locks: Dict[str, asyncio.Lock] = {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def aquery_for_product(
        self,
        query: str,
        product_id: str,
        dataset_type: "str | DatasetType" = DatasetType.PRODUCT_DOCS,
        param: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Query the RAG-Anything store for a specific product and dataset.

        Args:
            query:        Natural language query
            product_id:   Canonical product ID (e.g. "5G_SBA", "DSR")
            dataset_type: Which dataset to query (product_docs | reference_hlds)
            param:        RAG-Anything query parameters (mode, top_k, etc.)

        Returns:
            Query results from RAG-Anything
        """
        wrapper = await self._get_or_init_wrapper(product_id, dataset_type)
        result = await wrapper.aquery(query=query, param=param)
        logger.debug(
            f"aquery_for_product: product={product_id} dataset={_dt_str(dataset_type)} "
            f"query='{query[:60]}...'"
        )
        return result

    async def ingest_document(
        self,
        file_path: str,
        product_id: str,
        dataset_type: "str | DatasetType",
    ) -> None:
        """
        Ingest a document into the specified product/dataset store.

        Args:
            file_path:    Path to document (PDF, DOCX, TXT, etc.)
            product_id:   Canonical product ID (e.g. "5G_SBA")
            dataset_type: Target dataset (product_docs | reference_hlds)
        """
        wrapper = await self._get_or_init_wrapper(product_id, dataset_type)
        logger.info(
            f"Ingesting into {product_id}/{_dt_str(dataset_type)}: {file_path}"
        )
        await wrapper.ingest_document(file_path)
        logger.info(f"Ingestion complete: {file_path}")

    async def initialize_product(
        self,
        product_id: str,
        dataset_type: "str | DatasetType",
    ) -> None:
        """
        Pre-warm the RAG-Anything instance for a product/dataset.

        Useful at startup to avoid cold-start latency during first query.

        Args:
            product_id:   Product ID to initialize
            dataset_type: Dataset type to initialize
        """
        await self._get_or_init_wrapper(product_id, dataset_type)
        logger.info(
            f"Pre-warmed RAG-Anything for {product_id}/{_dt_str(dataset_type)}"
        )

    async def aquery(
        self,
        query: str,
        param: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """
        Legacy fallback query — DEPRECATED.

        CRITICAL: This method is deprecated and will raise an error.
        Use aquery_for_product() with explicit product_id instead.

        Failing fast prevents silent cross-product contamination
        (e.g., Sessions job accidentally querying DSR data).
        """
        products = ProductRegistry.list_products()

        # CRITICAL FIX: Fail fast instead of silent fallback
        # Silent fallback to first product (alphabetically DSR) causes cross-contamination
        raise ValueError(
            "MultiProductRAGWrapper.aquery() called without product_id. "
            "This is NOT allowed - use aquery_for_product(query, product_id, dataset_type) instead. "
            f"Available products: {products}. "
            "Failing fast to prevent cross-product data contamination."
        )

    def list_initialized_stores(self) -> List[str]:
        """
        Return list of currently initialized (product_id, dataset_type) pairs.

        Returns:
            List of strings like ["5G_SBA/product_docs", "DSR/reference_hlds"]
        """
        result = []
        for product_id, datasets in self._wrappers.items():
            for dt in datasets:
                result.append(f"{product_id}/{dt}")
        return result

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _get_or_init_wrapper(
        self,
        product_id: str,
        dataset_type: "str | DatasetType",
    ) -> RAGAnythingWrapper:
        """
        Return the RAGAnythingWrapper for (product_id, dataset_type).
        Lazy-initializes on first call; uses per-key lock to prevent races.
        """
        dt = _dt_str(dataset_type)
        cache_key = f"{product_id}::{dt}"

        # Fast path — already initialized
        if product_id in self._wrappers and dt in self._wrappers[product_id]:
            return self._wrappers[product_id][dt]

        # Ensure a lock exists for this key
        if cache_key not in self._init_locks:
            self._init_locks[cache_key] = asyncio.Lock()

        async with self._init_locks[cache_key]:
            # Double-check after acquiring lock
            if product_id in self._wrappers and dt in self._wrappers[product_id]:
                return self._wrappers[product_id][dt]

            # Guard against a common mistake: passing .../rag_storage/DSR instead of
            # .../rag_storage as base_working_dir.  get_working_dir() always appends
            # /{product_id}/{dataset_type}, so passing the product folder produces
            # .../rag_storage/DSR/DSR/product_docs — an empty wrong directory.
            if Path(self.base_working_dir).name == product_id:
                raise ValueError(
                    f"base_working_dir '{self.base_working_dir}' ends with the product_id "
                    f"'{product_id}'. Pass the RAG storage ROOT directory "
                    f"(e.g. './rag_storage'), not the product-specific subfolder "
                    f"(e.g. './rag_storage/{product_id}')."
                )

            working_dir = ProductRegistry.get_working_dir(
                self.base_working_dir, product_id, dt
            )
            logger.info(
                f"Initializing RAG-Anything for {product_id}/{dt} "
                f"at '{working_dir}'"
            )

            wrapper = RAGAnythingWrapper(
                oci_client=self.oci_client,
                working_dir=working_dir,
                embedding_model=self.embedding_model,
                chat_model=self.chat_model,
            )
            # RAGAnythingWrapper initializes lazily on first query/ingest,
            # but we call initialize() here to fail early if config is broken.
            await wrapper.initialize()

            if product_id not in self._wrappers:
                self._wrappers[product_id] = {}
            self._wrappers[product_id][dt] = wrapper

            logger.info(
                f"RAG-Anything initialized: {product_id}/{dt} → '{working_dir}'"
            )
            return wrapper


# -------------------------------------------------------------------------
# Module-level helpers
# -------------------------------------------------------------------------

def _dt_str(dataset_type: "str | DatasetType") -> str:
    """Normalize DatasetType to its string value."""
    return dataset_type.value if isinstance(dataset_type, DatasetType) else str(dataset_type)
