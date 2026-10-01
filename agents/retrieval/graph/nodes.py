"""
Pipeline nodes for Retrieval Agent LangGraph.

3-node sequential pipeline:
1. initialize - Validate inputs and prepare state
2. execute_queries - Query RAG-Anything, get LLM-synthesised answers, store them (PARALLELIZED)
3. finalize - Compute metrics, write summary to Cognee

All ranking/filtering/deduplication is handled internally by RAG-Anything.

PERFORMANCE OPTIMIZATION:
- execute_queries_node now executes ALL RAG queries in parallel using asyncio.gather()
- Flattens double nested loops (sections × queries) into single task list
- Expected speedup: 4-10x (80-400s → 10-40s for typical workloads)
"""

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from hld_generator.agents.retrieval.state.schema import RetrievalState
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


# ============================
# Node 1: Initialize
# ============================


async def initialize_node(state: RetrievalState) -> RetrievalState:
    """
    Validate inputs and prepare for retrieval.

    Checks:
    - Blueprint is present
    - Sections and RAG queries are defined

    Initializes:
    - query_execution_log
    - rag_results
    """
    logger.info("Node: initialize - Validating inputs")

    blueprint = state.get("blueprint")
    if not blueprint:
        error_msg = "Missing blueprint in state"
        logger.error(error_msg)
        state["errors"].append(error_msg)
        state["retrieval_complete"] = False
        return state

    sections = blueprint.get("sections", [])
    total_queries = sum(len(sec.get("rag_queries", [])) for sec in sections)

    logger.info(
        f"Retrieval initialized: {len(sections)} sections, {total_queries} queries"
    )

    state["query_execution_log"] = []
    state["rag_results"] = {}

    return state


# ============================
# Node 2: Execute Queries
# ============================


async def execute_queries_node(
    state: RetrievalState, rag_anything_client
) -> RetrievalState:
    """
    Execute RAG queries for every section in the Blueprint IN PARALLEL.

    PERFORMANCE OPTIMIZATION:
    - Flattens double nested loops into single task list
    - Executes ALL queries concurrently using asyncio.gather()
    - Expected speedup: 4-10x compared to sequential execution

    Per-section logic (two independent passes):

    Pass 1 — Reference HLD (always, every section):
        Query the ``reference_hlds`` dataset: "What does the '{section_title}'
        section typically include in an HLD document?"
        Returns LLM-synthesised plain-text answer (only_need_context=False).
        Provides structure/style guidance to the Content Generation Agent.

    Pass 2 — Product Documentation (Blueprint queries only):
        Execute only the queries explicitly provided by the Blueprint Agent
        against the ``product_docs`` dataset.  The Retriever Agent never
        generates its own product-doc queries.
        Returns LLM-synthesised plain-text answer (only_need_context=False).
        Multiple queries joined with "\n\n" separator.
        Skipped entirely if Blueprint provides no rag_queries for a section.

    Output per section (four fields only):
        - section_id, section_title
        - reference_from_past_HLDs (plain text answer from Pass 1)
        - rag_questions_answer_from_blueprint (plain text answer from Pass 2, or "")

    All Blueprint sections appear in the output regardless of whether
    they have Blueprint queries.

    Args:
        state: Current retrieval state
        rag_anything_client: RAGAnything instance

    Returns:
        Updated state with rag_results populated for all Blueprint sections
    """
    logger.info("Node: execute_queries - Processing all Blueprint sections IN PARALLEL")

    blueprint = state["blueprint"]
    sections = blueprint.get("sections", [])

    # Product ID for dataset-scoped queries (set by Blueprint Agent)
    product_id = state.get("product_id", "")
    if product_id:
        logger.info(f"Product-scoped retrieval: product_id='{product_id}'")
    else:
        logger.warning(
            "No product_id in retrieval state — falling back to unscoped RAG-Anything query. "
            "Ensure BlueprintAgent writes selected_product_id to HLDGeneratorState."
        )

    # Check once whether the client supports product-scoped queries
    supports_product_query = product_id and hasattr(rag_anything_client, "aquery_for_product")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: Collect ALL tasks upfront (no awaits - build coroutine list)
    # ═══════════════════════════════════════════════════════════════════════

    all_tasks = []
    task_metadata = []  # Track which section/query each task belongs to

    for section in sections:
        section_id = section["section_id"]
        section_title = section.get("title", section_id)
        rag_queries = section.get("rag_queries", [])

        # ── Pass 1: Reference HLD query (always, every section) ──────────────
        ref_query_text = (
            f"What does the '{section_title}' section typically include in an HLD document? "
            f"Describe the typical content, subsections, and key technical points covered."
        )
        ref_query_param = {"mode": "hybrid", "top_k": 3, "only_need_context": False}

        if supports_product_query:
            ref_task = rag_anything_client.aquery_for_product(
                query=ref_query_text,
                product_id=product_id,
                dataset_type="reference_hlds",
                param=ref_query_param,
            )
        else:
            ref_task = rag_anything_client.aquery(
                query=ref_query_text,
                param=ref_query_param,
            )

        all_tasks.append(ref_task)
        task_metadata.append({
            "section_id": section_id,
            "section_title": section_title,
            "query_type": "reference",
        })

        # ── Pass 2: Product Documentation queries (Blueprint only) ───────────
        for query_idx, rag_query in enumerate(rag_queries):
            query_text = rag_query["query"]
            top_k = rag_query.get("top_k", 5)
            dataset_type = "product_docs"

            query_param = {
                "mode": "hybrid",
                "top_k": top_k,
                "only_need_context": False,  # LLM-synthesised plain-text answer
            }

            if supports_product_query:
                prod_task = rag_anything_client.aquery_for_product(
                    query=query_text,
                    product_id=product_id,
                    dataset_type=dataset_type,
                    param=query_param,
                )
            else:
                prod_task = rag_anything_client.aquery(
                    query=query_text,
                    param=query_param,
                )

            all_tasks.append(prod_task)
            task_metadata.append({
                "section_id": section_id,
                "section_title": section_title,
                "query_type": "product",
                "query_idx": query_idx,
                "query_text": query_text[:80],  # For logging
            })

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: Execute ALL queries in parallel using asyncio.gather()
    # ═══════════════════════════════════════════════════════════════════════

    logger.info(f"Executing {len(all_tasks)} RAG queries IN PARALLEL...")
    start_time = asyncio.get_event_loop().time()

    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    elapsed = asyncio.get_event_loop().time() - start_time
    logger.info(f"Parallel execution completed in {elapsed:.2f}s")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: Map results back to sections
    # ═══════════════════════════════════════════════════════════════════════

    # Build section_results dict keyed by section_id
    section_results = {}

    for i, result in enumerate(results):
        meta = task_metadata[i]
        section_id = meta["section_id"]

        # Initialize section entry if not exists
        if section_id not in section_results:
            section_results[section_id] = {
                "section_id": section_id,
                "section_title": meta["section_title"],
                "reference_from_past_HLDs": "",
                "blueprint_answer_parts": [],
            }

        # Handle exceptions
        if isinstance(result, Exception):
            logger.warning(
                f"Query failed for {section_id} ({meta['query_type']}): {result}"
            )
            error_msg = f"Section {section_id}, {meta['query_type']} query: {str(result)}"
            state["errors"].append(error_msg)
            continue

        # Process successful result
        answer_text = str(result).strip() if result else ""

        if not answer_text or "[no-context]" in answer_text:
            logger.debug(
                f"Section {section_id}: No answer for {meta['query_type']} query"
            )
            continue

        if meta["query_type"] == "reference":
            section_results[section_id]["reference_from_past_HLDs"] = answer_text
            logger.info(
                f"Section {section_id}: Reference HLD answer retrieved "
                f"({len(answer_text)} chars)"
            )
        else:  # product query
            section_results[section_id]["blueprint_answer_parts"].append(answer_text)
            logger.debug(
                f"Section {section_id}: Product query {meta['query_idx']+1} answer "
                f"retrieved ({len(answer_text)} chars)"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: Combine product answers and store final results
    # ═══════════════════════════════════════════════════════════════════════

    for section_id, section_data in section_results.items():
        blueprint_answer = "\n\n".join(section_data["blueprint_answer_parts"])

        state["rag_results"][section_id] = {
            "section_id": section_id,
            "section_title": section_data["section_title"],
            "reference_from_past_HLDs": section_data["reference_from_past_HLDs"],
            "rag_questions_answer_from_blueprint": blueprint_answer,
        }

        logger.info(
            f"Section {section_id}: blueprint_answer={'yes' if blueprint_answer else 'no'}, "
            f"reference_hld={'yes' if section_data['reference_from_past_HLDs'] else 'no'}"
        )

    logger.info(
        f"Retrieval complete: {len(section_results)} sections processed in parallel"
    )

    return state


# ============================
# Node 3: Finalize
# ============================


async def finalize_node(state: RetrievalState) -> RetrievalState:
    """
    Compute metrics and mark retrieval as complete.

    Steps:
    1. Compute overall retrieval metrics
    2. Mark retrieval_complete = True

    Args:
        state: Current retrieval state

    Returns:
        Final state with retrieval_metrics and retrieval_complete
    """
    logger.info("Node: finalize - Computing metrics")

    total_sections = len(state["rag_results"])

    # Count sections with reference HLD answers and Blueprint answers
    sections_with_ref = sum(
        1 for r in state["rag_results"].values()
        if r.get("reference_from_past_HLDs")
    )
    sections_with_blueprint = sum(
        1 for r in state["rag_results"].values()
        if r.get("rag_questions_answer_from_blueprint")
    )

    retrieval_metrics = {
        "total_sections": total_sections,
        "sections_with_reference_hld": sections_with_ref,
        "sections_with_blueprint_answer": sections_with_blueprint,
        "timestamp": datetime.now().isoformat(),
    }

    state["retrieval_metrics"] = retrieval_metrics

    state["retrieval_complete"] = True
    logger.info(
        f"Retrieval complete: {total_sections} sections processed "
        f"({sections_with_ref} with reference HLD, {sections_with_blueprint} with Blueprint answer)"
    )

    return state
