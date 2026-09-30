"""
Unified Debugger CLI.
Convenience wrapper to run individual debuggers.
"""

import sys
import argparse
import subprocess
import os


def prompt(label, default=None, required=False):
    """Prompt the user for input, showing default if provided."""
    suffix = f" [{default}]" if default is not None else ""
    suffix += " (required)" if required and default is None else ""
    while True:
        value = input(f"  {label}{suffix}: ").strip()
        # Strip surrounding quotes users may paste from Windows Explorer / shell
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1].strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("  This field is required.")


def prompt_yes_no(label, default=False):
    """Prompt for a yes/no answer."""
    hint = "[Y/n]" if default else "[y/N]"
    answer = input(f"  {label} {hint}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def prompt_analyzer_args():
    """Interactively collect arguments for the Document Analyzer debugger."""
    print()
    print("=" * 50)
    print("  Document Analyzer Debugger")
    print("=" * 50)

    file_path = prompt("Document file path (.docx / .pdf)", required=True)
    product   = prompt("Product name to focus on", required=True)
    dataset   = prompt("Cognee dataset name", default="debug_dataset")

    # New optional parameters
    doc_type  = prompt("Document type (leave blank to auto-detect)")
    product_hint = prompt("Product hint for extraction (leave blank to skip)")

    # Multi-document support
    has_additional = prompt_yes_no("Add additional documents to analyze together?", default=False)
    additional_docs = []
    if has_additional:
        print("  Enter additional document paths (one per line, blank line to finish):")
        while True:
            doc = prompt("    Additional document path", required=False)
            if not doc:
                break
            additional_docs.append(doc)

    show_images = prompt_yes_no("Show detailed image inventory in output?", default=False)
    debug     = prompt_yes_no("Enable debug logging?", default=False)
    output    = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = [
        "--file", file_path,
        "--product", product,
        "--dataset", dataset,
    ]

    if doc_type:
        extra_args.extend(["--document-type", doc_type])
    if product_hint:
        extra_args.extend(["--product-hint", product_hint])
    if additional_docs:
        extra_args.extend(["--additional-docs"] + additional_docs)
    if show_images:
        extra_args.append("--show-images")
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


def prompt_blueprint_args():
    """Interactively collect arguments for the Blueprint Agent debugger."""
    print()
    print("=" * 50)
    print("  Blueprint Agent Debugger")
    print("=" * 50)

    kb      = prompt("Knowledge Base JSON file path (or full Analyzer output JSON)", required=True)
    images  = prompt("Image Inventory JSON file path (leave blank — auto-extracted from KB if present)")
    dataset = prompt("Cognee dataset name", default="debug_dataset")
    debug   = prompt_yes_no("Enable debug logging?", default=False)
    output  = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = ["--kb", kb, "--dataset", dataset]
    if images:
        extra_args.extend(["--images", images])
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


def prompt_analyzer_blueprint_args():
    """Interactively collect arguments for the combined Analyzer + Blueprint debugger."""
    print()
    print("=" * 50)
    print("  Document Analyzer + Blueprint Agent (Chained)")
    print("=" * 50)

    file_path = prompt("Document file path (.docx / .pdf)", required=True)
    product   = prompt("Product name to focus on", required=True)
    dataset   = prompt("Cognee dataset name", default="debug_dataset")

    # Analyzer optional parameters
    doc_type  = prompt("Document type (leave blank to auto-detect)")
    product_hint = prompt("Product hint for extraction (leave blank to skip)")

    # Multi-document support
    has_additional = prompt_yes_no("Add additional documents to analyze together?", default=False)
    additional_docs = []
    if has_additional:
        print("  Enter additional document paths (one per line, blank line to finish):")
        while True:
            doc = prompt("    Additional document path", required=False)
            if not doc:
                break
            additional_docs.append(doc)

    save_analyzer = prompt("Save Analyzer output JSON file path (leave blank to skip)")
    debug     = prompt_yes_no("Enable debug logging?", default=False)
    output    = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = [
        "--file", file_path,
        "--product", product,
        "--dataset", dataset,
    ]

    if doc_type:
        extra_args.extend(["--document-type", doc_type])
    if product_hint:
        extra_args.extend(["--product-hint", product_hint])
    if additional_docs:
        extra_args.extend(["--additional-docs"] + additional_docs)
    if save_analyzer:
        extra_args.extend(["--save-analyzer-output", save_analyzer])
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


def prompt_content_assembly_args():
    """Interactively collect arguments for the combined Content + Assembly debugger."""
    print()
    print("=" * 50)
    print("  Content Generation + Assembly Debugger")
    print("=" * 50)

    blueprint  = prompt("Blueprint JSON file path", required=True)
    rag        = prompt("RAG Results JSON file path (leave blank to skip)")
    images     = prompt("Image Library JSON file path (leave blank to skip)")
    context    = prompt("Project Context (KB) JSON file path (leave blank to skip)")
    parsed     = prompt("Parsed document text file path .txt (leave blank to skip)")
    dataset    = prompt("Cognee dataset name", default="debug_dataset")
    output_dir = prompt("Output directory for assembled docs", default="./outputs/assembly")
    debug      = prompt_yes_no("Enable debug logging?", default=False)
    output     = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = ["--blueprint", blueprint, "--dataset", dataset, "--output-dir", output_dir]
    if rag:
        extra_args.extend(["--rag", rag])
    if images:
        extra_args.extend(["--images", images])
    if context:
        extra_args.extend(["--context", context])
    if parsed:
        extra_args.extend(["--parsed", parsed])
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


def prompt_retrieval_args():
    """Interactively collect arguments for the Retrieval Agent debugger."""
    print()
    print("=" * 50)
    print("  Retrieval Agent Debugger")
    print("=" * 50)

    blueprint = prompt("Blueprint JSON file path", required=True)
    kb        = prompt("Knowledge Base JSON file path (leave blank to skip)")
    dataset   = prompt("Cognee dataset name", default="debug_dataset")
    rag_dir   = prompt("RAG storage dir override (leave blank to use $RAG_WORKING_DIR)")
    debug     = prompt_yes_no("Enable debug logging?", default=False)
    output    = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = ["--blueprint", blueprint, "--dataset", dataset]
    if kb:
        extra_args.extend(["--kb", kb])
    if rag_dir:
        extra_args.extend(["--rag-dir", rag_dir])
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


def prompt_retrieval_content_assembly_args():
    """Interactively collect arguments for the combined Retrieval + Content + Assembly debugger."""
    print()
    print("=" * 50)
    print("  Retrieval + Content Generation + Assembly (Chained)")
    print("=" * 50)

    blueprint  = prompt("Blueprint JSON file path", required=True)
    kb         = prompt("Knowledge Base JSON file path (leave blank to skip)")
    images     = prompt("Image Library JSON file path (leave blank to skip)")
    parsed     = prompt("Parsed document text file path .txt (leave blank to skip)")
    dataset    = prompt("Cognee dataset name", default="debug_dataset")
    rag_dir    = prompt("RAG storage dir override (leave blank to use $RAG_WORKING_DIR)")
    output_dir = prompt("Output directory for assembled docs", default="./outputs/assembly")
    save_retrieval = prompt("Save Retrieval output JSON file path (leave blank to skip)")
    save_content   = prompt("Save Content output JSON file path (leave blank to skip)")
    debug      = prompt_yes_no("Enable debug logging?", default=False)
    output     = prompt("Output JSON file path (leave blank to print to console)")

    extra_args = ["--blueprint", blueprint, "--dataset", dataset, "--output-dir", output_dir]
    if kb:
        extra_args.extend(["--kb", kb])
    if images:
        extra_args.extend(["--images", images])
    if parsed:
        extra_args.extend(["--parsed", parsed])
    if rag_dir:
        extra_args.extend(["--rag-dir", rag_dir])
    if save_retrieval:
        extra_args.extend(["--save-retrieval-output", save_retrieval])
    if save_content:
        extra_args.extend(["--save-content-output", save_content])
    if debug:
        extra_args.append("--debug")
    if output:
        extra_args.extend(["--output", output])

    print()
    return extra_args


INTERACTIVE_PROMPTS = {
    "analyzer": prompt_analyzer_args,
    "blueprint": prompt_blueprint_args,
    "analyzer-blueprint": prompt_analyzer_blueprint_args,
    "retrieval": prompt_retrieval_args,
    "retrieval-content-assembly": prompt_retrieval_content_assembly_args,
    "content": prompt_content_assembly_args,
}


def main():
    parser = argparse.ArgumentParser(description="HLD Generator Unified Debugger CLI")
    subparsers = parser.add_subparsers(dest="agent", help="Agent to debug")

    # Just defining commands to show help, actual execution uses subprocess to isolate
    subparsers.add_parser("analyzer", help="Debug Document Analyzer", add_help=False)
    subparsers.add_parser("blueprint", help="Debug Blueprint Agent", add_help=False)
    subparsers.add_parser("analyzer-blueprint", help="Debug Analyzer + Blueprint (chained pipeline)", add_help=False)
    subparsers.add_parser("retrieval", help="Debug Retrieval Agent", add_help=False)
    subparsers.add_parser("retrieval-content-assembly", help="Debug Retrieval + Content + Assembly (chained pipeline)", add_help=False)
    subparsers.add_parser("image", help="Debug Image Generation Agent", add_help=False)
    subparsers.add_parser("content", help="Debug Content Generation + Assembly (runs both together)", add_help=False)

    args, unknown = parser.parse_known_args()

    if not args.agent:
        parser.print_help()
        sys.exit(1)

    script_map = {
        "analyzer": "debug_analyzer.py",
        "blueprint": "debug_blueprint.py",
        "analyzer-blueprint": "debug_analyzer_blueprint.py",
        "retrieval": "debug_retrieval.py",
        "retrieval-content-assembly": "debug_retrieval_content_assembly.py",
        "image": "debug_image_gen.py",
        "content": "debug_content_assembly.py",
    }

    # If no flags were passed and an interactive prompter exists, use it
    if not unknown and args.agent in INTERACTIVE_PROMPTS:
        try:
            unknown = INTERACTIVE_PROMPTS[args.agent]()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(130)

    debugger_dir = os.path.dirname(os.path.abspath(__file__))
    project_root  = os.path.dirname(debugger_dir)

    script_name = script_map.get(args.agent)
    script_path = os.path.join(debugger_dir, script_name)

    # Construct command
    cmd = [sys.executable, script_path] + unknown

    print(f"Running: {' '.join(cmd)}")
    print()
    try:
        # Run from project root so relative paths (.env, OCI config, etc.) resolve correctly
        subprocess.run(cmd, check=True, cwd=project_root)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
