"""
Semantic Chunker for Document Analyzer Agent.

Intelligently chunks large documents while preserving semantic boundaries
(sections, headings) for accurate LLM-based extraction.
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


# Try to import LlamaIndex MarkdownNodeParser
try:
    from llama_index.core.node_parser import MarkdownNodeParser
    from llama_index.core import Document as LlamaDocument
    LLAMA_INDEX_AVAILABLE = True
except ImportError:
    LLAMA_INDEX_AVAILABLE = False
    logger.warning(
        "LlamaIndex not available. Falling back to regex-based chunking. "
        "Install with: pip install llama-index-core"
    )


@dataclass
class Chunk:
    """
    A semantic chunk of document text with metadata.

    Attributes:
        text: The chunk content
        metadata: Dict with section_title, doc_name, chunk_index, etc.
        start_char: Starting character position in original document
        end_char: Ending character position in original document
    """
    text: str
    metadata: Dict[str, Any]
    start_char: int = 0
    end_char: int = 0


class SemanticChunker:
    """
    Semantic chunking utility for document analyzer.

    Intelligently splits documents by sections/headings while respecting
    size limits. Uses LlamaIndex MarkdownNodeParser when available,
    falls back to regex-based chunking otherwise.

    Usage:
        chunker = SemanticChunker(max_chunk_size=40000, overlap=3000)
        chunks = chunker.chunk(document_text, doc_name="example.pdf")
    """

    def __init__(self, max_chunk_size: int = 40000, overlap: int = 3000):
        """
        Initialize semantic chunker.

        Args:
            max_chunk_size: Maximum characters per chunk (default 40K for LLM)
            overlap: Overlap between chunks in characters (default 3K for context)
        """
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

        # Initialize LlamaIndex parser if available
        if LLAMA_INDEX_AVAILABLE:
            try:
                self.markdown_parser = MarkdownNodeParser()
                logger.info("LlamaIndex MarkdownNodeParser initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize MarkdownNodeParser: {e}. Using fallback.")
                self.markdown_parser = None
        else:
            self.markdown_parser = None

    def chunk(
        self,
        text: str,
        doc_name: str = "document",
        doc_index: int = 0
    ) -> List[Chunk]:
        """
        Chunk document text using semantic boundaries.

        Args:
            text: Full document text to chunk
            doc_name: Source document name (for metadata)
            doc_index: Document index in multi-doc scenario

        Returns:
            List of Chunk objects with text and metadata
        """
        if not text or not text.strip():
            logger.warning(f"Empty document text for {doc_name}, returning empty chunk list")
            return []

        # Try LlamaIndex first
        if self.markdown_parser:
            try:
                chunks = self._chunk_with_llamaindex(text, doc_name, doc_index)
                if chunks:
                    logger.info(
                        f"Chunked {doc_name} into {len(chunks)} semantic chunks "
                        f"using LlamaIndex ({len(text):,} chars total)"
                    )
                    return chunks
            except Exception as e:
                logger.warning(f"LlamaIndex chunking failed: {e}. Falling back to regex.")

        # Fallback to regex-based chunking
        chunks = self._chunk_with_regex(text, doc_name, doc_index)
        logger.info(
            f"Chunked {doc_name} into {len(chunks)} chunks "
            f"using regex fallback ({len(text):,} chars total)"
        )
        return chunks

    def _chunk_with_llamaindex(
        self,
        text: str,
        doc_name: str,
        doc_index: int
    ) -> List[Chunk]:
        """
        Chunk using LlamaIndex MarkdownNodeParser (preserves markdown structure).

        Args:
            text: Document text
            doc_name: Document name
            doc_index: Document index

        Returns:
            List of Chunk objects
        """
        # Create LlamaIndex document
        llama_doc = LlamaDocument(text=text, metadata={"source": doc_name})

        # Parse into nodes
        nodes = self.markdown_parser.get_nodes_from_documents([llama_doc])

        chunks = []
        current_text = ""
        current_start = 0
        section_title = "Unknown"

        for node_idx, node in enumerate(nodes):
            node_text = node.text
            node_metadata = node.metadata or {}

            # Extract section title from metadata or first heading in node
            section_title = self._extract_section_title(node_text, section_title)

            # If adding this node exceeds max size, create a chunk
            if len(current_text) + len(node_text) > self.max_chunk_size and current_text:
                chunks.append(Chunk(
                    text=current_text,
                    metadata={
                        "document_name": doc_name,
                        "document_index": doc_index,
                        "chunk_index": len(chunks),
                        "section_title": section_title,
                        "total_chars": len(current_text),
                    },
                    start_char=current_start,
                    end_char=current_start + len(current_text),
                ))

                # Start new chunk with overlap
                overlap_text = current_text[-self.overlap:] if len(current_text) > self.overlap else current_text
                current_text = overlap_text + "\n\n" + node_text
                current_start = current_start + len(current_text) - len(overlap_text) - 2  # -2 for \n\n
            else:
                # Add to current chunk
                if current_text:
                    current_text += "\n\n" + node_text
                else:
                    current_text = node_text

        # Add final chunk
        if current_text.strip():
            chunks.append(Chunk(
                text=current_text,
                metadata={
                    "document_name": doc_name,
                    "document_index": doc_index,
                    "chunk_index": len(chunks),
                    "section_title": section_title,
                    "total_chars": len(current_text),
                },
                start_char=current_start,
                end_char=current_start + len(current_text),
            ))

        return chunks

    def _chunk_with_regex(
        self,
        text: str,
        doc_name: str,
        doc_index: int
    ) -> List[Chunk]:
        """
        Fallback chunking using regex-based section detection.

        Detects markdown headings (## Title, ### Title) and splits by sections.
        If no headings found, uses sentence-boundary-aware character splitting.

        Args:
            text: Document text
            doc_name: Document name
            doc_index: Document index

        Returns:
            List of Chunk objects
        """
        # Try to detect markdown headings
        heading_pattern = r'^(#{1,6})\s+(.+)$'
        headings = list(re.finditer(heading_pattern, text, re.MULTILINE))

        if headings and len(headings) >= 3:
            # Split by headings
            chunks = self._split_by_headings(text, headings, doc_name, doc_index)
        else:
            # No clear structure, use character-based splitting with sentence boundaries
            chunks = self._split_by_chars(text, doc_name, doc_index)

        return chunks

    def _split_by_headings(
        self,
        text: str,
        headings: List[re.Match],
        doc_name: str,
        doc_index: int
    ) -> List[Chunk]:
        """Split text by detected headings."""
        chunks = []
        sections = []

        # Build sections from headings
        for i, heading in enumerate(headings):
            start = heading.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            title = heading.group(2).strip()
            section_text = text[start:end]

            sections.append({
                "title": title,
                "text": section_text,
                "start": start,
                "end": end,
            })

        # Chunk sections (split large sections)
        current_chunk = ""
        current_start = 0
        current_title = sections[0]["title"] if sections else "Unknown"

        for section in sections:
            section_text = section["text"]

            # If section alone exceeds max size, split it
            if len(section_text) > self.max_chunk_size:
                # Save current chunk if exists
                if current_chunk.strip():
                    chunks.append(Chunk(
                        text=current_chunk,
                        metadata={
                            "document_name": doc_name,
                            "document_index": doc_index,
                            "chunk_index": len(chunks),
                            "section_title": current_title,
                            "total_chars": len(current_chunk),
                        },
                        start_char=current_start,
                        end_char=current_start + len(current_chunk),
                    ))
                    current_chunk = ""

                # Split large section with overlap
                sub_chunks = self._split_large_section(section_text, section["title"])
                for sub_chunk_text in sub_chunks:
                    chunks.append(Chunk(
                        text=sub_chunk_text,
                        metadata={
                            "document_name": doc_name,
                            "document_index": doc_index,
                            "chunk_index": len(chunks),
                            "section_title": section["title"],
                            "total_chars": len(sub_chunk_text),
                        },
                        start_char=section["start"],
                        end_char=section["start"] + len(sub_chunk_text),
                    ))

                current_start = section["end"]
                current_title = section["title"]

            # If adding section exceeds max, create chunk
            elif len(current_chunk) + len(section_text) > self.max_chunk_size and current_chunk:
                chunks.append(Chunk(
                    text=current_chunk,
                    metadata={
                        "document_name": doc_name,
                        "document_index": doc_index,
                        "chunk_index": len(chunks),
                        "section_title": current_title,
                        "total_chars": len(current_chunk),
                    },
                    start_char=current_start,
                    end_char=current_start + len(current_chunk),
                ))

                # Start new chunk with overlap
                overlap_text = current_chunk[-self.overlap:]
                current_chunk = overlap_text + "\n\n" + section_text
                current_start = section["start"] - len(overlap_text) - 2
                current_title = section["title"]
            else:
                # Add to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + section_text
                else:
                    current_chunk = section_text
                    current_start = section["start"]
                current_title = section["title"]

        # Add final chunk
        if current_chunk.strip():
            chunks.append(Chunk(
                text=current_chunk,
                metadata={
                    "document_name": doc_name,
                    "document_index": doc_index,
                    "chunk_index": len(chunks),
                    "section_title": current_title,
                    "total_chars": len(current_chunk),
                },
                start_char=current_start,
                end_char=current_start + len(current_chunk),
            ))

        return chunks

    def _split_by_chars(
        self,
        text: str,
        doc_name: str,
        doc_index: int
    ) -> List[Chunk]:
        """Character-based splitting with sentence boundary detection."""
        chunks = []
        start = 0

        while start < len(text):
            # Calculate end with overlap
            end = start + self.max_chunk_size

            # If not at document end, try to break at sentence boundary
            if end < len(text):
                # Look for sentence end in last 500 chars of chunk
                search_start = max(end - 500, start)
                sentence_end_pattern = r'[.!?]\s+'
                matches = list(re.finditer(sentence_end_pattern, text[search_start:end]))

                if matches:
                    # Break at last sentence boundary
                    last_match = matches[-1]
                    end = search_start + last_match.end()

            chunk_text = text[start:end]

            chunks.append(Chunk(
                text=chunk_text,
                metadata={
                    "document_name": doc_name,
                    "document_index": doc_index,
                    "chunk_index": len(chunks),
                    "section_title": "Character-based chunk",
                    "total_chars": len(chunk_text),
                },
                start_char=start,
                end_char=end,
            ))

            # Move start with overlap
            start = end - self.overlap

        return chunks

    def _split_large_section(self, section_text: str, title: str) -> List[str]:
        """Split a large section into multiple chunks with overlap."""
        chunks = []
        start = 0

        while start < len(section_text):
            end = start + self.max_chunk_size

            # Try to break at sentence boundary
            if end < len(section_text):
                search_start = max(end - 500, start)
                sentence_end = list(re.finditer(r'[.!?]\s+', section_text[search_start:end]))
                if sentence_end:
                    end = search_start + sentence_end[-1].end()

            chunks.append(section_text[start:end])
            start = end - self.overlap

        return chunks

    def _extract_section_title(self, text: str, default: str = "Unknown") -> str:
        """Extract section title from text (first heading)."""
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', text, re.MULTILINE)
        if heading_match:
            return heading_match.group(2).strip()
        return default
