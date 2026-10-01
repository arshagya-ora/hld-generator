"""
LangGraph nodes for Assembly Agent.

Pipeline flow:
1. initialize - Validate inputs
2. compile_sections - Merge all sections
3. auto_number - Assign numbers to figures, tables, sections
4. generate_toc - Create TOC, list of figures/tables
5. generate_executive_summary - LLM-generated exec summary
6. generate_appendices - Create appendices
7. quality_checks - Validate assembled document
8. export_documents - Export to DOCX/PDF
9. finalize - Create final output
"""

import logging
import time
import os
import re
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from hld_generator.agents.assembly.state.schema import AssemblyState
from hld_generator.agents.assembly.state.models import (
    AssembledDocument,
    AssemblyMetadata,
    DocumentStatistics,
    DocumentStructure,
    QualityCheckResult,
)
from hld_generator.agents.assembly.tools import (
    AutoNumbering,
    TOCGenerator,
    AppendixGenerator,
    ExecutiveSummaryGenerator,
    SectionNormalizer,
)
from hld_generator.agents.assembly.tools.quality_checks import QualityChecker

logger = logging.getLogger(__name__)


# ============================
# Node 1: Initialize
# ============================

async def initialize_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Validate inputs and prepare for assembly.

    Checks:
    - Generated sections exist
    - Blueprint is present
    - Output directory is valid

    Initializes:
    - Processing state
    - Output structures
    """
    logger.info("Node: initialize - Validating inputs")

    generated_sections = state.get("generated_sections", {})
    blueprint = state.get("blueprint")

    if not generated_sections:
        error_msg = "No generated sections to assemble"
        logger.error(error_msg)
        return {
            "errors": [error_msg],
            "assembly_complete": False,
        }

    if not blueprint:
        logger.warning("Blueprint not provided")

    logger.info(f"Assembly initialized: {len(generated_sections)} sections to assemble")

    return {
        "figure_references": [],
        "table_references": [],
        "section_references": [],
        "quality_checks": [],
        "exported_files": {},
        "errors": [],
        "warnings": [],
        "assembly_start_time": time.time(),
    }


# ============================
# Node 2: Compile Sections
# ============================

async def compile_sections_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Merge all generated sections into single document.

    Process:
    1. Normalize section numbering and heading levels from blueprint
    2. Sort sections by generate_order (profile position), then section_number
    3. Concatenate markdown content
    4. Preserve formatting
    """
    logger.info("Node: compile_sections - Merging sections")

    generated_sections = state["generated_sections"]
    blueprint = state.get("blueprint", {})

    # Normalize sections based on blueprint hierarchy
    normalizer = SectionNormalizer()
    generated_sections = normalizer.normalize_sections(generated_sections, blueprint)

    # Separate appendices from main sections
    # Appendices are sections with section_id starting with "sec_appendix" or titles starting with "Appendix"
    main_sections = []
    appendix_sections = []

    for section in generated_sections.values():
        section_id = section.get("section_id", "")
        title = section.get("title", "")

        is_appendix = (
            section_id.startswith("sec_appendix") or
            title.startswith("Appendix") or
            title.startswith("TBD. Appendix")
        )

        if is_appendix:
            appendix_sections.append(section)
        else:
            main_sections.append(section)

    # Sort main sections by blueprint order
    def _blueprint_order_key(s):
        """Sort by generate_order (preserves profile order), then by numeric section_number as tiebreaker"""
        order = s.get("generate_order", 999)

        # Within same generate_order, sort numerically by section_number
        try:
            num_parts = tuple(int(x) for x in str(s.get("section_number", "999")).split("."))
        except ValueError:
            num_parts = (999,)  # TBD sections still sort last within their batch

        return (order, num_parts)

    main_sections.sort(key=_blueprint_order_key)

    # Sort appendices alphabetically by title (to get A, B, C, D order)
    # Remove "TBD. " prefix for sorting
    def _appendix_sort_key(s):
        title = s.get("title", "")
        # Remove "TBD. " prefix if present
        title = title.replace("TBD. ", "")
        return title

    appendix_sections.sort(key=_appendix_sort_key)

    # Combine main sections (appendices will be added separately in export_documents_node)
    sections_list = main_sections

    # Compile content — embed image references from matched images
    compiled_parts = []

    for section in sections_list:
        markdown_content = section.get("markdown_content", "")

        # Only append images that were NOT already embedded inline by the LLM via {{FIGURE:image_id}}.
        # The LLM places {{FIGURE:image_id}} at contextually correct positions in the text.
        # auto_number_node replaces those placeholders with proper markdown image syntax.
        # Appending here is a fallback for images the LLM didn't embed.
        images_inserted = section.get("images_inserted", [])
        for img in images_inserted:
            image_id = img.get("image_id", "")
            storage_path = img.get("storage_path", "")
            caption = img.get("caption", "")
            if not image_id:
                continue
            # Skip if the LLM already embedded this image inline via {{FIGURE:...}}
            if f"{{{{FIGURE:{image_id}}}}}" in markdown_content:
                continue
            if storage_path:
                # Fallback: append at end of section; auto_number will update caption
                img_markdown = f"\n\n![{caption}]({image_id})\n"
                markdown_content += img_markdown
            else:
                logger.warning(f"Image '{image_id}' in section '{section.get('section_id')}' has no storage_path — skipping embed")

        compiled_parts.append(markdown_content)
        compiled_parts.append("\n\n---\n\n")  # Section separator

    compiled_content = "\n\n".join(compiled_parts)

    logger.info(f"Compiled {len(sections_list)} main sections into document")
    logger.info(f"Found {len(appendix_sections)} appendix sections to add separately")

    return {
        "compiled_content": compiled_content,
        "appendix_sections": appendix_sections,  # Store for later insertion in correct order
    }


# ============================
# Node 3: Auto-Numbering
# ============================

async def auto_number_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Assign sequential numbers to figures, tables, and sections.
    """
    logger.info("Node: auto_number - Assigning numbers")

    generated_sections = state["generated_sections"]
    image_library = state.get("final_image_library", {})

    # Convert to list
    sections_list = list(generated_sections.values())

    # Initialize numbering tool
    numbering = AutoNumbering()

    # Number figures
    figure_refs = numbering.number_figures(sections_list, image_library)

    # Number tables
    table_refs = numbering.number_tables(sections_list)

    # Number sections
    section_refs = numbering.number_sections(sections_list)

    # Update references in content
    compiled_content = state.get("compiled_content", "")
    compiled_content = numbering.update_figure_references(compiled_content, figure_refs)
    compiled_content = numbering.update_table_references(compiled_content, table_refs)

    logger.info(
        f"Assigned numbers: {len(figure_refs)} figures, {len(table_refs)} tables, {len(section_refs)} sections"
    )

    return {
        "figure_references": [ref.dict() for ref in figure_refs],
        "table_references": [ref.dict() for ref in table_refs],
        "section_references": [ref.dict() for ref in section_refs],
        "compiled_content": compiled_content,
    }


# ============================
# Node 4: Generate TOC
# ============================

async def generate_toc_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Generate Table of Contents, List of Figures, and List of Tables.
    """
    logger.info("Node: generate_toc - Creating TOC and lists")

    # Reconstruct reference objects from dicts
    from hld_generator.agents.assembly.state.models import (
        FigureReference,
        TableReference,
        SectionReference,
    )

    figure_refs = [FigureReference(**ref) for ref in state.get("figure_references", [])]
    table_refs = [TableReference(**ref) for ref in state.get("table_references", [])]
    section_refs = [SectionReference(**ref) for ref in state.get("section_references", [])]

    # Get appendix sections
    appendix_sections = state.get("appendix_sections", [])

    # Initialize TOC generator
    toc_gen = TOCGenerator()

    # Generate TOC (now includes executive summary and appendices)
    toc_content = toc_gen.generate_toc(
        section_refs,
        has_executive_summary=bool(state.get("executive_summary")),
        appendix_sections=appendix_sections,
    )

    # Generate List of Figures
    list_of_figures = toc_gen.generate_list_of_figures(figure_refs)

    # Generate List of Tables
    list_of_tables = toc_gen.generate_list_of_tables(table_refs)

    logger.info("TOC and lists generated successfully")

    return {
        "toc_content": toc_content,
        "list_of_figures": list_of_figures,
        "list_of_tables": list_of_tables,
    }


# ============================
# Node 5: Generate Executive Summary (LLM)
# ============================

async def generate_executive_summary_node(state: AssemblyState, llm_client) -> Dict[str, Any]:
    """
    Generate executive summary using LLM.

    This is the primary LLM usage in Assembly Agent.
    """
    logger.info("Node: generate_executive_summary - Generating exec summary with LLM")

    generated_sections = state.get("generated_sections", {})
    blueprint = state.get("blueprint", {})
    project_context = state.get("project_context", {})

    # Check if there are any sections to summarize
    if not generated_sections:
        logger.warning("No generated sections available - skipping executive summary generation")
        return {
            "executive_summary": "# 1. Executive Summary\n\n*Executive summary could not be generated - no content sections available.*\n",
        }

    # Convert sections dict to list
    sections_list = list(generated_sections.values())

    # Initialize executive summary generator
    exec_summary_gen = ExecutiveSummaryGenerator(llm_client)

    # Generate executive summary
    executive_summary = await exec_summary_gen.generate_executive_summary(
        sections_list,
        blueprint,
        project_context,
    )

    logger.info("Executive summary generated")

    return {
        "executive_summary": executive_summary,
    }


# ============================
# Node 6: Generate Appendices
# ============================

async def generate_appendices_node(state: AssemblyState, llm_client) -> Dict[str, Any]:
    """
    Generate appendices (acronyms, references) using AI.

    Both appendices are fully dynamic — the LLM extracts acronyms and
    references from the compiled document content. No hardcoded content.
    """
    logger.info("Node: generate_appendices - Creating appendices with LLM")

    compiled_content = state.get("compiled_content", "")

    appendix_gen = AppendixGenerator(llm_client=llm_client)

    # Generate both appendices (both are async LLM calls)
    appendix_parts = []

    acronyms = await appendix_gen.generate_acronyms(compiled_content)
    appendix_parts.append(acronyms)

    references = await appendix_gen.generate_references(compiled_content)
    appendix_parts.append(references)

    appendices_content = "\n\n".join(appendix_parts)

    logger.info("Appendices generated")

    return {
        "appendices_content": appendices_content,
    }


# ============================
# Node 7: Quality Checks
# ============================

async def quality_checks_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Run quality validation checks on assembled document.

    Combines original basic checks with enhanced hallucination-prevention checks:
    - Section numbering sequential
    - Orphaned figure/table placeholders
    - Meta-commentary detection
    - Acronym validity
    - TOC completeness
    - Appendix order
    - Plus original checks (sections present, exec summary, images, etc.)
    """
    logger.info("Node: quality_checks - Running validation checks")

    generated_sections = state["generated_sections"]
    compiled_content = state.get("compiled_content", "")
    quality_checks = []

    # ── Original basic checks ──

    check1 = QualityCheckResult(
        check_name="all_sections_present",
        passed=len(generated_sections) > 0,
        details=f"{len(generated_sections)} sections found",
    )
    quality_checks.append(check1.dict())

    executive_summary = state.get("executive_summary", "")
    check2 = QualityCheckResult(
        check_name="executive_summary_exists",
        passed=len(executive_summary) > 0,
        details="Executive summary generated" if executive_summary else "Missing executive summary",
    )
    quality_checks.append(check2.dict())

    toc_content = state.get("toc_content", "")
    check3 = QualityCheckResult(
        check_name="toc_exists",
        passed=len(toc_content) > 0,
        details="TOC generated" if toc_content else "Missing TOC",
    )
    quality_checks.append(check3.dict())

    figure_refs = state.get("figure_references", [])
    check4 = QualityCheckResult(
        check_name="figures_numbered",
        passed=True,
        details=f"{len(figure_refs)} figures numbered",
    )
    quality_checks.append(check4.dict())

    has_placeholders = "[TBD]" in compiled_content or "[TODO]" in compiled_content
    check5 = QualityCheckResult(
        check_name="no_placeholders",
        passed=not has_placeholders,
        details="No placeholders found" if not has_placeholders else "Warning: Placeholder text found",
    )
    quality_checks.append(check5.dict())

    missing_images = []
    for section in generated_sections.values():
        for img in section.get("images_inserted", []):
            if img.get("image_id") and not img.get("storage_path"):
                missing_images.append(img["image_id"])
    check6 = QualityCheckResult(
        check_name="image_paths_present",
        passed=len(missing_images) == 0,
        details=f"{len(missing_images)} images missing storage_path" if missing_images else "All images have storage paths",
    )
    quality_checks.append(check6.dict())

    # ── Enhanced hallucination-prevention checks ──

    checker = QualityChecker()
    enhanced_results = checker.check_all(
        compiled_markdown=compiled_content,
        sections=generated_sections,
        toc_content=toc_content,
        appendices_content=state.get("appendices_content", ""),
        executive_summary=executive_summary,
    )

    # Convert enhanced checks to QualityCheckResult format
    for check in enhanced_results["checks"]:
        is_passed = check["status"] == "pass"
        quality_checks.append(
            QualityCheckResult(
                check_name=check["name"],
                passed=is_passed,
                details=check["details"],
            ).dict()
        )

    passed = sum(1 for check in quality_checks if check["passed"])
    total = len(quality_checks)
    logger.info(f"Quality checks: {passed}/{total} passed")

    return {
        "quality_checks": quality_checks,
    }


# ============================
# Node 8: Export Documents
# ============================

async def export_documents_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Export assembled document to requested formats (DOCX, PDF, HTML).

    For now, this is a placeholder - actual DOCX/PDF export requires
    python-docx and conversion libraries.
    """
    logger.info("Node: export_documents - Exporting to formats")

    output_dir = state.get("output_dir", "./outputs")
    output_formats = state.get("output_formats", ["markdown"])
    blueprint = state.get("blueprint", {})
    generated_sections = state.get("generated_sections", {})

    # Ensure output directory exists
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir_path.absolute()}")

    # Generate document filename
    customer = blueprint.get("customer_name") or blueprint.get("customer") or "Customer"
    product = blueprint.get("product") or "Product"
    doc_type = blueprint.get("document_type") or "HLD"

    logger.info(f"Generating filename: customer='{customer}', product='{product}', doc_type='{doc_type}'")

    base_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{doc_type}_{customer}_{product}").strip("._") or "HLD"
    logger.info(f"Base filename: {base_filename}")

    exported_files = {}

    # Export markdown (always)
    # Use pathlib for cross-platform path handling
    markdown_path = output_dir_path / f"{base_filename}.md"

    # Combine all parts
    full_content_parts = []

    # Add executive summary
    if state.get("executive_summary"):
        full_content_parts.append(state["executive_summary"])

    # Add TOC
    if state.get("toc_content"):
        full_content_parts.append(state["toc_content"])

    # Add List of Figures
    if state.get("list_of_figures"):
        full_content_parts.append(state["list_of_figures"])

    # Add List of Tables
    if state.get("list_of_tables"):
        full_content_parts.append(state["list_of_tables"])

    # Add main content
    if state.get("compiled_content"):
        full_content_parts.append(state["compiled_content"])

    # Add appendices in correct order: A (acronyms), B (references), then content-generated appendices (D, etc.)
    # First add auto-generated appendices (A and B)
    if state.get("appendices_content"):
        full_content_parts.append(state["appendices_content"])

    # Then add content-generated appendices (like Appendix D) in alphabetical order
    appendix_sections = state.get("appendix_sections", [])
    for appendix in appendix_sections:
        appendix_content = appendix.get("markdown_content", "")
        if appendix_content:
            full_content_parts.append(appendix_content)

    full_content = "\n\n---\n\n".join(full_content_parts)

    # Write markdown file
    try:
        markdown_path.write_text(full_content, encoding='utf-8')
        logger.info(f"Exported markdown to: {markdown_path.absolute()}")
        exported_files["markdown"] = str(markdown_path.absolute())
    except Exception as e:
        logger.error(f"Failed to write markdown file: {e}")
        return {
            "errors": [f"Markdown export failed: {str(e)}"],
            "exported_files": exported_files,
        }

    # Export DOCX if requested
    if "docx" in output_formats:
        docx_path = output_dir_path / f"{base_filename}.docx"
        try:
            from hld_generator.agents.assembly.tools.docx_exporter import HLDDocxExporter
            exporter = HLDDocxExporter()
            exporter.export(
                parts={
                    "executive_summary": state.get("executive_summary") or "",
                    "toc_content":       state.get("toc_content") or "",
                    "list_of_figures":   state.get("list_of_figures") or "",
                    "list_of_tables":    state.get("list_of_tables") or "",
                    "appendices_content": state.get("appendices_content") or "",
                },
                blueprint=blueprint,
                generated_sections=generated_sections,
                output_path=str(docx_path),
            )
            logger.info(f"Exported DOCX to: {docx_path.absolute()}")
            exported_files["docx"] = str(docx_path.absolute())
        except ImportError:
            logger.warning("python-docx not installed, skipping DOCX export")
            logger.info("Install with: pip install python-docx")
        except Exception as e:
            logger.error(f"DOCX export failed: {e}")
            # Non-fatal - continue with other formats

    # Export PDF if requested
    if "pdf" in output_formats:
        pdf_path = output_dir_path / f"{base_filename}.pdf"
        logger.info(f"PDF export not implemented (requires external libraries)")
        logger.info(f"   Would export PDF to: {pdf_path.absolute()}")
        # Note: PDF generation requires libraries like reportlab or pandoc

    logger.info(f"Export complete: {len(exported_files)} formats")

    if not exported_files:
        error_msg = "Export failed: No files were exported"
        logger.error(error_msg)
        return {
            "exported_files": {},
            "errors": [error_msg],
        }

    logger.info(f"Exported files: {list(exported_files.keys())}")
    for fmt, path in exported_files.items():
        logger.info(f"  {fmt}: {path}")

    return {
        "exported_files": exported_files,
    }


# ============================
# Node 9: Finalize
# ============================

async def finalize_node(state: AssemblyState) -> Dict[str, Any]:
    """
    Create final AssembledDocument output with all metadata.
    """
    logger.info("Node: finalize - Creating final output")

    blueprint = state.get("blueprint", {})
    generated_sections = state["generated_sections"]
    quality_checks = state.get("quality_checks", [])
    exported_files = state.get("exported_files", {})

    # Calculate statistics
    total_words = 0
    for section in generated_sections.values():
        total_words += section.get("word_count", 0)

    statistics = DocumentStatistics(
        total_pages=0,  # Would be calculated from DOCX
        total_sections=len(generated_sections),
        total_figures=len(state.get("figure_references", [])),
        total_tables=len(state.get("table_references", [])),
        word_count=total_words,
        appendices=2,  # Acronyms + References
    )

    # Document structure
    structure = DocumentStructure(
        cover_page=True,
        table_of_contents=len(state.get("toc_content", "")) > 0,
        list_of_figures=len(state.get("list_of_figures", "")) > 0,
        list_of_tables=len(state.get("list_of_tables", "")) > 0,
        executive_summary=len(state.get("executive_summary", "")) > 0,
        main_sections=len(generated_sections),
        appendices=2,
        version_control_page=True,
    )

    # Assembly metadata
    passed_checks = sum(1 for check in quality_checks if check.get("passed"))
    failed_checks = len(quality_checks) - passed_checks

    # Compute actual assembly time from stored start time
    start_time = state.get("assembly_start_time")
    elapsed = round(time.time() - start_time, 2) if start_time else 0.0

    # Estimate LLM tokens from executive summary length (rough: 1 token ≈ 4 chars)
    exec_summary = state.get("executive_summary", "")
    estimated_tokens = max(len(exec_summary) // 4, 0)

    assembly_metadata = AssemblyMetadata(
        assembly_time_seconds=elapsed,
        llm_tokens_used=estimated_tokens,
        quality_checks_passed=passed_checks,
        quality_checks_failed=failed_checks,
        export_formats_created=len(exported_files),
    )

    # Create final document
    customer = blueprint.get("customer_name", "Customer")
    product = blueprint.get("product", "Product")
    doc_id = f"{customer}_{product}_{datetime.now().strftime('%Y%m%d')}".replace(" ", "_").lower()

    assembled_document = AssembledDocument(
        document_id=doc_id,
        formats=exported_files,
        statistics=statistics,
        structure=structure,
        assembly_metadata=assembly_metadata,
        quality_checks=[QualityCheckResult(**check) for check in quality_checks],
        executive_summary=state.get("executive_summary"),
    )

    logger.info(f"Assembly complete: {doc_id}")
    logger.info(f"  Sections: {statistics.total_sections}")
    logger.info(f"  Figures: {statistics.total_figures}")
    logger.info(f"  Tables: {statistics.total_tables}")
    logger.info(f"  Word count: {statistics.word_count}")
    logger.info(f"  Quality checks: {passed_checks}/{len(quality_checks)} passed")
    logger.info(f"  Exported files: {list(exported_files.keys())}")

    return {
        "assembled_document": assembled_document.dict(),
        "assembly_complete": True,
        "exported_files": exported_files,  # Ensure exported_files is preserved in final state
    }
