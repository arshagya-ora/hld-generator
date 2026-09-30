"""
RAG-Anything Client Wrapper

Provides interface to query product documentation from RAG-Anything.
Similar to CogneeWrapper, this wraps RAG-Anything functionality for HLD Generator.

RAG-Anything is the single source of truth for ALL product documentation:
- 5G_SBA technical specs and architecture
- DSR product documentation
- Future products as they're added
- Past HLD documents for reference
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

logger = logging.getLogger(__name__)


class RAGAnythingWrapper:
    """Wrapper for RAG-Anything product documentation queries"""

    def __init__(
        self,
        oci_client,  # OciOpenAI client
        working_dir: str = "./rag_storage",
        embedding_model: str = "openai.text-embedding-3-large",
        chat_model: str = "openai.gpt-5.2-chat-latest",
    ):
        """
        Initialize RAG-Anything wrapper.

        Args:
            oci_client: OciOpenAI client for LLM and embeddings
            working_dir: Directory for RAG-Anything storage
            embedding_model: OCI embedding model ID
            chat_model: OCI chat model ID
        """
        self.oci_client = oci_client
        self.working_dir = working_dir
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.rag_anything = None

    async def initialize(self):
        """
        Initialize RAG-Anything instance with OCI endpoints.

        Sets up:
        1. LLM function (async) using OCI chat completions
        2. Embedding function (async) using OCI embeddings
        3. RAGAnything instance with Docling parser
        """
        logger.info("Initializing RAG-Anything client...")

        # ============================
        # Setup LLM function
        # ============================
        async def llm_func(
            prompt: str,
            system_prompt: Optional[str] = None,
            history_messages: List = None,
            **kwargs,
        ) -> str:
            """LLM function for RAG-Anything using OCI Generative AI"""
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            if history_messages:
                messages.extend(history_messages)
            messages.append({"role": "user", "content": prompt})

            request_params = {
                "model": self.chat_model,
                "messages": messages,
                "max_completion_tokens": kwargs.get("max_completion_tokens") or kwargs.get("max_tokens", 2048),
            }
            # OCI only supports the default temperature (1); omit the parameter
            # entirely so the model uses its default. LightRAG passes temperature=0.7
            # which causes a 400 BadRequestError with OCI models.
            completion = await asyncio.to_thread(
                self.oci_client.chat.completions.create,
                **request_params,
            )
            return completion.choices[0].message.content

        # ============================
        # Setup embedding function
        # ============================

        # Probe embedding dimension
        probe = self.oci_client.embeddings.create(
            model=self.embedding_model, input="dimension probe"
        )
        embedding_dim = len(probe.data[0].embedding)
        logger.info(f"Embedding dimension: {embedding_dim}")

        async def embed_func(texts: List[str], **kwargs) -> np.ndarray:
            """Embedding function for RAG-Anything using OCI embeddings.
            **kwargs absorbs LightRAG internals like _priority that must not
            be forwarded to the OCI embeddings API."""
            if isinstance(texts, str):
                texts = [texts]

            def _embed_batch(batch: List[str]) -> List[List[float]]:
                resp = self.oci_client.embeddings.create(
                    model=self.embedding_model, input=batch
                )
                return [item.embedding for item in resp.data]

            embeddings = await asyncio.to_thread(_embed_batch, texts)
            return np.array(embeddings, dtype=np.float32)

        embedding_func = EmbeddingFunc(
            embedding_dim=embedding_dim,
            model_name=self.embedding_model,
            func=embed_func,
        )

        # ============================
        # Configure RAG-Anything
        # ============================
        config = RAGAnythingConfig(
            working_dir=self.working_dir,
            parser="docling",
            enable_image_processing=True,
            enable_table_processing=True,
            context_window=2,
            context_mode="page",
        )

        # ============================
        # Initialize RAG-Anything
        # ============================
        self.rag_anything = RAGAnything(
            config=config,
            llm_model_func=llm_func,
            embedding_func=embedding_func,
            lightrag_kwargs={
                "embedding_func_max_async": 2,
                "default_embedding_timeout": 180,
                "embedding_batch_num": 2,
                "enable_llm_cache": False,
                "enable_llm_cache_for_entity_extract": False,
            },
        )

        logger.info("RAG-Anything client initialized successfully")

    async def query(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        only_need_context: bool = False,
    ) -> Any:
        """
        Query RAG-Anything for product documentation.

        Args:
            query: Natural language query
            mode: Query mode - "hybrid" (recommended), "local", "global", "naive", "mix"
                - hybrid: Combines vector + keyword + graph (best for most queries)
                - local: Graph-based retrieval for specific entities
                - global: Comprehensive knowledge graph search
                - naive: Basic vector similarity
                - mix: Integrates knowledge graph and vector retrieval
            top_k: Number of results to return
            only_need_context: If True, return only context without reasoning

        Returns:
            Query results (format depends on only_need_context)
        """
        if not self.rag_anything:
            await self.initialize()

        try:
            # lightrag is None until _ensure_lightrag_initialized() is called;
            # RAGAnything.aquery() does not call it internally (unlike process_document_complete).
            await self.rag_anything._ensure_lightrag_initialized()
            result = await self.rag_anything.aquery(
                query=query,
                mode=mode,
                top_k=top_k,
                only_need_context=only_need_context,
            )
            return result

        except Exception as e:
            logger.error(f"RAG-Anything query failed: {e}")
            raise

    async def aquery(self, query: str, param: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        Compatibility wrapper for callers expecting RAGAnything.aquery(query, param=...).
        """
        query_param = param or {}
        mode = query_param.get("mode", kwargs.get("mode", "hybrid"))
        top_k = query_param.get("top_k", kwargs.get("top_k", 10))
        only_need_context = query_param.get(
            "only_need_context",
            kwargs.get("only_need_context", False),
        )
        return await self.query(
            query=query,
            mode=mode,
            top_k=top_k,
            only_need_context=only_need_context,
        )

    # File extensions handled by reading raw text and inserting via LightRAG directly.
    # Docling (the default parser) does NOT support these formats.
    _TEXT_FORMATS = {".md", ".txt", ".rst", ".csv", ".log", ".json", ".yaml", ".yml"}

    async def ingest_document(self, file_path: str):
        """
        Ingest a product documentation file into RAG-Anything.

        Supports ALL file types:
        - PDF, DOCX, PPTX, XLSX, HTML: processed via Docling (process_document_complete)
        - MD, TXT, RST, CSV, JSON, YAML: read directly and inserted via LightRAG.ainsert()
          (Docling does not support plain-text formats)

        Args:
            file_path: Path to document file
        """
        if not self.rag_anything:
            await self.initialize()

        p = Path(file_path)
        ext = p.suffix.lower()

        try:
            if ext in self._TEXT_FORMATS:
                # Plain-text path: read content and insert via insert_content_list().
                # This bypasses the Docling parser, which only supports PDF/Office/HTML.
                logger.info(f"Text format detected ({ext}), inserting via insert_content_list: {file_path}")
                text = p.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    logger.warning(f"File is empty, skipping: {file_path}")
                    return

                content_list = [{"type": "text", "text": text, "page_idx": 0}]
                await self.rag_anything.insert_content_list(
                    content_list=content_list,
                    file_path=str(p),
                    split_by_character="\n\n",    # paragraph-level splits for markdown
                    split_by_character_only=False, # still honour token-length limits
                    doc_id=p.stem,
                )
                logger.info(f"Successfully ingested text file: {file_path}")

            else:
                # Binary/structured path: Docling parser handles PDF, DOCX, PPTX, HTML, etc.
                await self.rag_anything.process_document_complete(file_path)
                logger.info(f"Successfully ingested document: {file_path}")

        except Exception as e:
            logger.error(f"Failed to ingest document {file_path}: {e}")
            raise
