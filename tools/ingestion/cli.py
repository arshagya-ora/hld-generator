"""
Ingestion CLI — Seed RAG-Anything product datasets.

Interactive by default: run with no arguments for a guided session.
Non-interactive mode is also supported for scripting.

Usage:
    # Interactive (guided prompts)
    python -m hld_generator.tools.ingestion.cli

    # Non-interactive (all args provided)
    python -m hld_generator.tools.ingestion.cli \\
        --product 5G_SBA --type product_docs doc1.pdf doc2.pdf

    # List products and exit
    python -m hld_generator.tools.ingestion.cli --list

Environment:
    Reads OCI config from .env (same as the main pipeline).

Exit codes:
    0  All documents ingested successfully (or dry-run)
    1  One or more documents failed to ingest
    2  Configuration or validation error / user cancelled
"""

import argparse
import asyncio
import importlib.util as _ilu
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Register hld_generator_v2 as 'hld_generator' so internal absolute imports
# resolve correctly regardless of folder name (same pattern as debuggers/).
_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent  # hld_generator_v2/
_PROJECT_PARENT = _PROJECT_DIR.parent                          # v2/

for _p in (_PROJECT_PARENT, _PROJECT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_hld_init = _PROJECT_DIR / "__init__.py"
if _hld_init.exists() and "hld_generator" not in sys.modules:
    _spec = _ilu.spec_from_file_location(
        "hld_generator", str(_hld_init),
        submodule_search_locations=[str(_PROJECT_DIR)]
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules["hld_generator"] = _mod
    _spec.loader.exec_module(_mod)

load_dotenv()

from hld_generator.shared.product_registry import DatasetType, ProductRegistry
from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────

_LINE = "─" * 56
_DOUBLE = "═" * 56


def _header() -> None:
    print()
    print(_DOUBLE)
    print("  ArchDraft — RAG-Anything Ingestion Tool")
    print(_DOUBLE)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


def _dataset_description(dt: DatasetType) -> str:
    return {
        DatasetType.PRODUCT_DOCS:   "Technical product documentation (specs, architecture guides)",
        DatasetType.REFERENCE_HLDS: "Past completed HLDs for this product (reference material)",
    }.get(dt, "")


# ─────────────────────────────────────────────────────────────────
# Interactive prompts
# ─────────────────────────────────────────────────────────────────

def _prompt(label: str, default: str = "") -> str:
    """Generic single-line prompt with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return value if value else default


def _prompt_choice(options: list, label: str, default: int = 1) -> int:
    """
    Present a numbered menu and return the 0-based index of the chosen item.
    Keeps re-prompting on invalid input.
    """
    while True:
        try:
            raw = input(f"\n{label} [1-{len(options)}, default: {default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if not raw:
            return default - 1
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        print(f"  Please enter a number between 1 and {len(options)}.")


def _prompt_yes_no(question: str, default_yes: bool = True) -> bool:
    """Yes/No prompt. Returns bool."""
    hint = "[Y/n]" if default_yes else "[y/N]"
    try:
        raw = input(f"{question} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not raw:
        return default_yes
    return raw.startswith("y")


def _prompt_files() -> list:
    """
    Prompt the user to enter file paths one at a time.
    Blank line ends input. Returns list of path strings.
    """
    print("\nEnter document paths to ingest (one per line, blank line when done):")
    paths = []
    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            break
        # Strip surrounding quotes that some terminals/shells add on drag-and-drop
        raw = raw.strip("'\"")
        # Normalize Windows backslashes
        raw = raw.replace("\\", "/")
        paths.append(raw)
    return paths


def _show_products(products: list, rag_dir: str) -> None:
    """Print numbered product list with dataset status."""
    for i, pid in enumerate(products, 1):
        initialized = ProductRegistry.list_datasets(pid, rag_dir)
        status = f"initialized: {', '.join(initialized)}" if initialized else "not yet ingested"
        print(f"  [{i}] {pid:<20} ({status})")


# Formats ingested via LightRAG.ainsert() (raw text) — no Docling parsing
_TEXT_FORMATS = {".md", ".txt", ".rst", ".csv", ".log", ".json", ".yaml", ".yml"}
# Formats ingested via Docling (process_document_complete)
_DOCLING_FORMATS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".html", ".htm", ".xhtml"}


def _show_file_preview(file_paths: list) -> int:
    """
    Display the file list with existence check and ingest method annotation.
    Returns number of missing files.
    """
    missing = 0
    print(f"\nFiles to ingest ({len(file_paths)}):")
    for fp in file_paths:
        p = Path(fp)
        ext = p.suffix.lower()
        if ext in _TEXT_FORMATS:
            method = "text"
        elif ext in _DOCLING_FORMATS:
            method = "docling"
        else:
            method = "unknown"

        if p.exists():
            print(f"  +  {p.name}  [{method}]")
        else:
            print(f"  x  NOT FOUND: {fp}")
            missing += 1
    return missing


# ─────────────────────────────────────────────────────────────────
# OCI client
# ─────────────────────────────────────────────────────────────────

def _init_oci_client():
    try:
        from hld_generator.backend.services.oci_client import (
            initialize_oci_services,
            get_oci_client,
        )
        initialize_oci_services()
        return get_oci_client()
    except Exception as e:
        logger.error(f"Failed to initialize OCI client: {e}")
        print(
            f"\n  Error: Could not initialize OCI client.\n"
            f"  Ensure your .env file is configured correctly.\n"
            f"  Details: {e}"
        )
        raise


# ─────────────────────────────────────────────────────────────────
# Core ingestion
# ─────────────────────────────────────────────────────────────────

async def ingest_files(
    product_id: str,
    dataset_type: str,
    file_paths: list,
    rag_dir: str,
    dry_run: bool = False,
) -> int:
    """
    Ingest files into a product/dataset store.
    Returns number of failures (0 = all succeeded).
    """
    from hld_generator.shared.multi_product_rag_wrapper import MultiProductRAGWrapper

    working_dir = ProductRegistry.get_working_dir(rag_dir, product_id, dataset_type)

    if dry_run:
        print(f"\n[DRY RUN] Target store: {working_dir}")
        _show_file_preview(file_paths)
        return 0

    print(f"\nTarget store: {working_dir}")

    oci_client = _init_oci_client()
    wrapper = MultiProductRAGWrapper(oci_client=oci_client, base_working_dir=rag_dir)

    failed = 0
    for i, file_path in enumerate(file_paths, 1):
        p = Path(file_path)
        print(f"\n[{i}/{len(file_paths)}] {p.name}")

        if not p.exists():
            print(f"  x File not found: {file_path}")
            logger.error(f"File not found: {file_path}")
            failed += 1
            continue

        try:
            print(f"  Ingesting into {product_id}/{dataset_type}...", flush=True)
            await wrapper.ingest_document(
                file_path=str(p.resolve()),
                product_id=product_id,
                dataset_type=dataset_type,
            )
            print(f"  + Ingested successfully")
            logger.info(f"Ingested: {file_path}")
        except Exception as e:
            print(f"  x Failed: {e}")
            logger.error(f"Ingestion failed for {file_path}: {e}")
            failed += 1

    return failed


# ─────────────────────────────────────────────────────────────────
# Interactive session
# ─────────────────────────────────────────────────────────────────

async def run_interactive(rag_dir: str, dry_run: bool, verbose: bool) -> int:
    """
    Fully guided interactive session.
    Loops so the user can ingest multiple batches without restarting.
    Returns exit code.
    """
    _header()
    print(f"\n  RAG storage : {rag_dir}")
    print(f"  Mode        : {'DRY RUN' if dry_run else 'LIVE'}")
    if verbose:
        print(f"  Verbose     : ON")

    overall_failed = 0

    while True:
        # ── Step 1: Choose product ───────────────────────────────
        _section("Step 1 — Select product")
        products = ProductRegistry.list_products()
        if not products:
            print(
                "  No products registered.\n"
                "  Add a <ProductName>.json file to PRODUCT_PROFILE_DIR first."
            )
            return 2

        _show_products(products, rag_dir)

        try:
            product_idx = _prompt_choice(products, "Select product")
        except KeyboardInterrupt:
            print("\n\n  Cancelled.")
            return 2

        product_id = products[product_idx]
        print(f"  → {product_id}")

        # ── Step 2: Choose dataset type ──────────────────────────
        _section("Step 2 — Select dataset type")
        dataset_types = list(DatasetType)
        for i, dt in enumerate(dataset_types, 1):
            print(f"  [{i}] {dt.value:<20} — {_dataset_description(dt)}")

        try:
            dt_idx = _prompt_choice(dataset_types, "Select dataset type")
        except KeyboardInterrupt:
            print("\n\n  Cancelled.")
            return 2

        dataset_type = dataset_types[dt_idx].value
        print(f"  → {dataset_type}")

        # ── Step 3: Enter files ──────────────────────────────────
        _section("Step 3 — Add documents")
        try:
            file_paths = _prompt_files()
        except KeyboardInterrupt:
            print("\n\n  Cancelled.")
            return 2

        if not file_paths:
            print("  No files entered. Skipping ingestion.")
        else:
            # ── Step 4: Preview & confirm ────────────────────────
            _section("Step 4 — Review")
            print(f"  Product:  {product_id}")
            print(f"  Dataset:  {dataset_type}")
            missing = _show_file_preview(file_paths)

            if missing:
                print(f"\n  Warning: {missing} file(s) not found — they will be skipped.")

            print()
            try:
                confirmed = _prompt_yes_no("Proceed with ingestion?", default_yes=True)
            except KeyboardInterrupt:
                print("\n\n  Cancelled.")
                return 2

            if confirmed:
                failed = await ingest_files(
                    product_id=product_id,
                    dataset_type=dataset_type,
                    file_paths=file_paths,
                    rag_dir=rag_dir,
                    dry_run=dry_run,
                )
                overall_failed += failed

                total = len(file_paths)
                succeeded = total - failed
                print(f"\n{_LINE}")
                if failed == 0:
                    print(f"  Ingestion complete: {succeeded}/{total} succeeded")
                else:
                    print(f"  Ingestion complete: {succeeded}/{total} succeeded, {failed} failed")
            else:
                print("  Skipped.")

        # ── Loop: ingest more? ───────────────────────────────────
        print()
        try:
            again = _prompt_yes_no("Ingest more documents?", default_yes=False)
        except KeyboardInterrupt:
            print("\n  Goodbye!")
            break

        if not again:
            print("\n  Goodbye!")
            break

    return 1 if overall_failed else 0


# ─────────────────────────────────────────────────────────────────
# Non-interactive (scripted) flow
# ─────────────────────────────────────────────────────────────────

async def run_non_interactive(
    product_id: str,
    dataset_type: str,
    file_paths: list,
    rag_dir: str,
    dry_run: bool,
) -> int:
    """
    Non-interactive ingestion — all parameters already known.
    Returns exit code.
    """
    if not ProductRegistry.validate_product_id(product_id):
        available = ", ".join(ProductRegistry.list_products()) or "none"
        print(
            f"\nError: Unknown product '{product_id}'.\n"
            f"Available: {available}\n"
            f"Add {product_id}.json to PRODUCT_PROFILE_DIR to register it."
        )
        return 2

    if not file_paths:
        print(
            f"\nError: No files specified.\n"
            f"Example:\n"
            f"  python -m hld_generator.tools.ingestion.cli "
            f"--product {product_id} --type {dataset_type} doc.pdf"
        )
        return 2

    print(f"\nArchDraft — RAG-Anything Ingestion")
    print(f"  Product  : {product_id}")
    print(f"  Dataset  : {dataset_type}")
    print(f"  Files    : {len(file_paths)}")
    print(f"  RAG dir  : {rag_dir}")
    if dry_run:
        print(f"  Mode     : DRY RUN")

    failed = await ingest_files(
        product_id=product_id,
        dataset_type=dataset_type,
        file_paths=file_paths,
        rag_dir=rag_dir,
        dry_run=dry_run,
    )

    total = len(file_paths)
    succeeded = total - failed
    print(f"\n{_LINE}")
    print(f"Ingestion complete: {succeeded}/{total} succeeded", end="")
    print(f", {failed} failed" if failed else "")

    return 1 if failed else 0


# ─────────────────────────────────────────────────────────────────
# List command
# ─────────────────────────────────────────────────────────────────

def run_list(rag_dir: str) -> None:
    products = ProductRegistry.list_products()
    if not products:
        print("\nNo products found. Add <ProductName>.json to PRODUCT_PROFILE_DIR")
        return

    print(f"\nRegistered products ({len(products)}):")
    _show_products(products, rag_dir)

    print(f"\nRAG storage : {rag_dir}")
    print("\nDataset types:")
    for dt in DatasetType:
        print(f"  {dt.value:<20} — {_dataset_description(dt)}")


# ─────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hld_generator.tools.ingestion.cli",
        description=(
            "Seed RAG-Anything product datasets for ArchDraft.\n"
            "Run with no arguments for interactive mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered products and their dataset status, then exit",
    )
    parser.add_argument(
        "--product",
        metavar="PRODUCT_ID",
        help="Product ID matching a local product profile JSON filename. Triggers non-interactive mode.",
    )
    parser.add_argument(
        "--type",
        dest="dataset_type",
        choices=[dt.value for dt in DatasetType],
        default=DatasetType.PRODUCT_DOCS.value,
        help="Dataset: product_docs (default) | reference_hlds",
    )
    parser.add_argument(
        "--rag-dir",
        default=os.getenv("RAG_WORKING_DIR", "./rag_storage"),
        metavar="DIR",
        help="Base RAG storage directory (default: $RAG_WORKING_DIR or ./rag_storage)",
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="Document file(s) to ingest — triggers non-interactive mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show what would be ingested without ingesting",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    return parser


# ─────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────

async def _main_async(args: argparse.Namespace) -> int:
    if args.list:
        run_list(args.rag_dir)
        return 0

    # Non-interactive: product explicitly provided via --product flag
    if args.product:
        return await run_non_interactive(
            product_id=args.product,
            dataset_type=args.dataset_type,
            file_paths=args.files,
            rag_dir=args.rag_dir,
            dry_run=args.dry_run,
        )

    # Interactive: no --product flag → guided session
    return await run_interactive(
        rag_dir=args.rag_dir,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        exit_code = asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Goodbye!")
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
