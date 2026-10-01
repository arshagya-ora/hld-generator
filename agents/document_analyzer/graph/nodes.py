"""
LangGraph node functions for Document Analyzer Agent.

New streamlined pipeline (Cognee-free):
parse -> extract_images -> semantic_extract -> merge_and_validate
"""

from typing import Dict, Any, List
import sys
import asyncio
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from hld_generator.agents.document_analyzer.state.schema import AnalyzerState
from hld_generator.agents.document_analyzer.tools.parser_wrapper import ParserWrapper
from hld_generator.agents.document_analyzer.tools.semantic_chunker import SemanticChunker
from hld_generator.agents.document_analyzer.tools.knowledge_merger import KnowledgeMerger, validate_knowledge_base
from hld_generator.agents.document_analyzer.tools.llm_helper import LLMHelper
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


# Initialize shared tools (will be passed from agent)
_parser = None
_image_analysis_phase = None
_llm_helper = None


def initialize_tools(parser, image_analysis_phase=None, llm_helper=None):
    """Initialize shared tools for all nodes"""
    global _parser, _image_analysis_phase, _llm_helper
    _parser = parser
    _image_analysis_phase = image_analysis_phase
    _llm_helper = llm_helper or LLMHelper()


async def parse_document_node(state: AnalyzerState) -> AnalyzerState:
    """
    Node 1: Parse document(s) using Docling.

    Supports both single-document and multi-document modes:
      - Single: read from state["document_path"]
      - Multi : read from state["document_paths"] (list); each document is parsed
                and its text is merged with a [Document: name] header.

    Extracts text, rich tables (with section/page context), and document structure.
    """

    logger.info("Step 1: Parsing document...")

    try:
        # Determine list of paths to parse.
        doc_paths = state.get("document_paths") or []
        if not doc_paths:
            # Single-document mode (backward compatible)
            doc_paths = [state["document_path"]]

        all_texts: list = []
        all_tables: list = []
        all_structures: list = []
        all_metadata: list = []
        primary_converter_result = None
        primary_image_dir = None

        # Parse all documents in parallel (huge speedup for multi-doc jobs)
        async def parse_single_doc(doc_path, idx):
            logger.info(f"   Parsing document {idx + 1}/{len(doc_paths)}: {doc_path}")
            try:
                parsed = await _parser.parse(doc_path, extract_tables=True)
                return (idx, doc_path, parsed, None)
            except Exception as parse_err:
                logger.error(f"   Error parsing {doc_path}: {str(parse_err)}")
                return (idx, doc_path, None, str(parse_err))

        # Execute all parsing tasks in parallel
        tasks = [parse_single_doc(doc_path, i) for i, doc_path in enumerate(doc_paths)]
        parse_results = await asyncio.gather(*tasks)

        # Process results in original order
        for idx, doc_path, parsed, error in sorted(parse_results, key=lambda x: x[0]):
            if error:
                state["errors"].append(f"Parsing failed for {doc_path}: {error}")
                continue

            doc_text = parsed.get("text", "")
            if len(doc_paths) > 1:
                # Prefix each document's text with a clear separator
                from pathlib import Path as _Path
                doc_label = _Path(doc_path).name
                doc_text = f"\n\n{'='*60}\n[Document {idx + 1}: {doc_label}]\n{'='*60}\n\n{doc_text}"

            all_texts.append(doc_text)
            all_tables.extend(parsed.get("tables") or [])
            if parsed.get("structure"):
                all_structures.append(parsed["structure"])
            if parsed.get("metadata"):
                all_metadata.append(parsed["metadata"])

            # Keep the first document's Docling result for image extraction
            if idx == 0:
                primary_converter_result = parsed.get("converter_result")
                primary_image_dir = parsed.get("image_dir")

        # Merge everything into state
        state["parsed_content"] = "\n".join(all_texts)
        state["current_phase"] = "parse"

        # DEBUG: Log parsing to trace document identity
        import hashlib
        content_hash = hashlib.md5(state["parsed_content"][:5000].encode()).hexdigest()
        preview = state["parsed_content"][:300].replace('\n', ' ')[:200]
        logger.info(f"🔍 PARSER DEBUG: Content hash (first 5000 chars): {content_hash}")
        logger.info(f"🔍 PARSER DEBUG: Content preview: {preview}...")

        if primary_converter_result is not None:
            state["converter_result"] = primary_converter_result
        if primary_image_dir:
            state["image_dir"] = primary_image_dir

        if "extraction_metadata" not in state:
            state["extraction_metadata"] = {}
        state["extraction_metadata"]["parsing"] = all_metadata[0] if all_metadata else {}
        state["extraction_metadata"]["parsed_doc_count"] = len(all_texts)

        # Store rich tables (section context, page number, markdown) for synthesis
        if all_tables:
            state["parsed_tables"] = all_tables
            state["extraction_metadata"]["parsed_tables"] = all_tables

        # Merge document structures (sections from all docs)
        if all_structures:
            merged_sections: list = []
            merged_headings: list = []
            for s in all_structures:
                merged_sections.extend(s.get("sections", []))
                merged_headings.extend(s.get("headings", []))
            state["document_structure"] = {
                "sections": merged_sections,
                "headings": merged_headings,
            }

        total_chars = len(state["parsed_content"])
        total_tables = len(all_tables)
        logger.info(f"   Parsed {len(all_texts)} document(s)")
        logger.info(f"   Extracted {total_chars:,} characters, {total_tables} tables")

    except Exception as e:
        state["errors"].append(f"Parsing failed: {str(e)}")
        logger.error(f"   Error: {str(e)}")

    return state


async def extract_images_node(state: AnalyzerState) -> AnalyzerState:
    """
    Node 1.5: Extract and analyze images from parsed document.
    
    Uses Docling image extraction → MinIO storage → OCI Vision analysis.
    Stores image_inventory in state for synthesis phase.
    """

    logger.info("Step 1.5: Extracting and analyzing images...")
    
    if not _image_analysis_phase:
        logger.info("   Image analysis not configured, skipping")
        state["image_inventory"] = None
        return state
    
    try:
        document_path = state["document_path"]
        dataset_name = state["dataset_name"]
        project_id = dataset_name  # Use dataset name as project ID
        
        # Reuse Docling ConversionResult and pre-populated image dir from the
        # parse node so we skip a second full Docling conversion.
        converter_result = state.get("converter_result")
        image_dir = state.get("image_dir")

        result = await _image_analysis_phase.execute(
            document_path=document_path,
            project_id=project_id,
            dataset_name=dataset_name,
            converter_result=converter_result,
            image_dir=image_dir,
        )
        
        state["image_inventory"] = result.get("image_inventory")
        state["extracted_images"] = result.get("extracted_images", [])
        state["current_phase"] = "extract_images"
        
        total = result.get("image_inventory", {}).get("total_images_extracted", 0)
        logger.info(f"   Image inventory built with {total} images")
        
    except Exception as e:
        state["warnings"].append(f"Image extraction failed (non-fatal): {str(e)}")
        state["image_inventory"] = None
        logger.warning(f"   Image extraction failed (non-fatal): {str(e)}")
    
    return state


async def semantic_extract_node(state: AnalyzerState) -> AnalyzerState:
    """
    Node 3: Semantic Extraction - chunk and extract from each chunk in parallel.

    Uses semantic chunking to preserve topic boundaries, then runs direct
    LLM extraction on each chunk in parallel for maximum speed and accuracy.
    """

    logger.info("Step 3: Semantic Extraction...")

    try:
        parsed_content = state.get("parsed_content", "")
        selected_product_name = state.get("selected_product_name", "")

        if not parsed_content or not parsed_content.strip():
            logger.warning("   No parsed content to extract from")
            state["semantic_chunks"] = []
            state["chunk_extractions"] = []
            return state

        # Step 1: Semantic chunking
        logger.info("   Chunking document with semantic boundaries...")
        chunker = SemanticChunker(max_chunk_size=40000, overlap=3000)

        # Handle multi-doc: track document source
        doc_paths = state.get("document_paths") or [state["document_path"]]
        if len(doc_paths) > 1:
            # Parsed content has document separators - chunk normally
            chunks = chunker.chunk(parsed_content, doc_name="multi_document", doc_index=0)
        else:
            chunks = chunker.chunk(parsed_content, doc_name=doc_paths[0], doc_index=0)

        logger.info(f"   Created {len(chunks)} semantic chunks")

        # Step 2: Extract from each chunk in parallel
        logger.info(f"   Extracting knowledge from {len(chunks)} chunks in parallel...")

        async def extract_single_chunk(chunk, chunk_idx):
            try:
                result = await _llm_helper.extract_full_knowledge_base(
                    document_text=chunk.text,
                    selected_product_name=selected_product_name,
                    doc_intelligence_hint=None,  # Will be filled from first chunk
                )
                logger.info(f"   ✓ Chunk {chunk_idx + 1}/{len(chunks)} extracted")
                return result
            except Exception as e:
                logger.warning(f"   ✗ Chunk {chunk_idx + 1} extraction failed: {e}")
                return {}  # Return empty dict to continue

        # Execute all chunk extractions in parallel
        chunk_extractions = await asyncio.gather(*[
            extract_single_chunk(chunk, idx)
            for idx, chunk in enumerate(chunks)
        ])

        # Store in state
        state["semantic_chunks"] = chunks
        state["chunk_extractions"] = chunk_extractions
        state["current_phase"] = "semantic_extract"

        logger.info(f"   Semantic extraction complete: {len(chunk_extractions)} chunks processed")

    except Exception as e:
        state["errors"].append(f"Semantic extraction failed: {str(e)}")
        logger.error(f"   Error: {str(e)}")
        state["semantic_chunks"] = []
        state["chunk_extractions"] = []

    return state


async def merge_and_validate_node(state: AnalyzerState) -> AnalyzerState:
    """
    Node 4: Merge and Validate - combine chunk results into unified knowledge base.

    Merges all chunk extractions using intelligent conflict resolution,
    injects tables and images, validates completeness.
    """

    logger.info("Step 4: Merging and Validating...")

    try:
        chunk_extractions = state.get("chunk_extractions", [])

        if not chunk_extractions:
            logger.warning("   No chunk extractions to merge")
            state["knowledge_base"] = {}
            state["completeness_score"] = 0.0
            state["missing_items"] = ["all_data"]
            return state

        # Step 1: Merge chunk results
        logger.info(f"   Merging {len(chunk_extractions)} chunk results...")
        merger = KnowledgeMerger()
        kb = merger.merge_all(chunk_extractions)

        # Step 2: Inject verbatim tables from Docling (filter empty tables)
        parsed_tables = state.get("parsed_tables", [])
        if parsed_tables:
            # Filter out empty tables (num_rows = 0 or empty markdown)
            non_empty_tables = [
                t for t in parsed_tables
                if t.get("num_rows", 0) > 0 and t.get("markdown", "").strip()
            ]
            logger.info(f"   Injecting {len(non_empty_tables)} verbatim Docling tables (filtered {len(parsed_tables) - len(non_empty_tables)} empty)...")
            kb.tables = non_empty_tables

            # Step 3: Enrich table descriptions using chunk context
            try:
                semantic_chunks = state.get("semantic_chunks", [])
                logger.info("   Enriching table descriptions...")
                descriptions = await _llm_helper.batch_generate_table_descriptions(
                    kb.tables, semantic_chunks
                )

                # Apply descriptions
                for i, description in enumerate(descriptions):
                    if i < len(kb.tables) and description:
                        kb.tables[i]["description"] = description

                logger.info(f"   ✓ Generated {len(descriptions)} table descriptions")
            except Exception as e:
                logger.warning(f"   Table description generation failed: {e}")

        # Step 4: Inject image inventory diagrams
        image_inventory = state.get("image_inventory")
        if image_inventory and image_inventory.get("images"):
            logger.info("   Merging image inventory diagrams...")
            # Convert image inventory images to diagrams format
            images = image_inventory.get("images", [])
            for img in images:
                vision = img.get("vision_analysis", {})
                if vision.get("type") in ["architecture_diagram", "network_topology", "component_diagram"]:
                    diagram = {
                        "image_id": img.get("image_id"),
                        "caption": img.get("caption", ""),
                        "type": vision.get("type"),
                        "components": vision.get("components_shown", []),
                        "relationships": vision.get("relationships_shown", []),
                        "source_page": img.get("source_page"),
                        "source_section": img.get("source_section"),
                    }
                    kb.diagrams.append(diagram)

            logger.info(f"   ✓ Added {len(kb.diagrams)} diagrams from image analysis")

        # Step 5: Validate completeness
        logger.info("   Validating knowledge base completeness...")
        validation = validate_knowledge_base(kb)

        state["knowledge_base"] = kb.model_dump()
        state["completeness_score"] = validation["score"]
        state["missing_items"] = validation["missing_items"]
        state["current_phase"] = "merge_and_validate"

        # Update extraction metadata
        if "extraction_metadata" not in state:
            state["extraction_metadata"] = {}
        state["extraction_metadata"].update({
            "chunk_count": len(chunk_extractions),
            "merge_strategy": "union_with_conflict_resolution",
            "validation": validation,
        })

        logger.info("   Merge and validation complete!")
        logger.info(f"   ✓ Knowledge Base Stats:")
        logger.info(f"      - Products: {len(kb.products)}")
        logger.info(f"      - Sites: {len(kb.sites)}")
        logger.info(f"      - Tables: {len(kb.tables)}")
        logger.info(f"      - Diagrams: {len(kb.diagrams)}")
        logger.info(f"      - Special Notes: {len(kb.special_notes)}")
        logger.info(f"      - Completeness: {validation['score']:.1%}")

        if validation["missing_items"]:
            logger.warning(f"      - Missing: {', '.join(validation['missing_items'])}")

    except Exception as e:
        state["errors"].append(f"Merge and validation failed: {str(e)}")
        logger.error(f"   Error: {str(e)}")
        state["knowledge_base"] = {}
        state["completeness_score"] = 0.0
        state["missing_items"] = ["merge_failed"]

    return state
