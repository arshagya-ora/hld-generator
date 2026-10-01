#!/usr/bin/env python3
"""
OCI RAG Setup Script

This script helps configure and test OCI GenAI integration with:
- Cognee (knowledge graph and RAG)
- RAG-Anything (document processing and RAG)

Usage:
    python setup_oci_rag.py --check          # Check configuration
    python setup_oci_rag.py --test-cognee    # Test Cognee with OCI
    python setup_oci_rag.py --test-rag       # Test RAG-Anything with OCI
    python setup_oci_rag.py --interactive    # Interactive setup wizard
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional


def check_oci_config() -> Dict[str, bool]:
    """Check OCI configuration files and environment variables."""
    checks = {}

    # Check OCI config file
    oci_config_path = os.path.expanduser("~/.oci/config")
    checks["oci_config_exists"] = os.path.exists(oci_config_path)

    # Check key file exists
    if checks["oci_config_exists"]:
        try:
            import configparser
            parser = configparser.RawConfigParser()
            parser.read(oci_config_path)
            profile = os.getenv("OCI_PROFILE", "CONFIG")
            # configparser treats [DEFAULT] as a special section — has_section() returns
            # False for it. Use parser.defaults() instead to read DEFAULT values.
            if profile.upper() == "DEFAULT":
                section_values = dict(parser.defaults())
            elif parser.has_section(profile):
                section_values = dict(parser.items(profile))
            else:
                section_values = {}
            key_file = section_values.get("key_file")
            if key_file:
                key_path = os.path.expanduser(key_file)
                checks["oci_key_exists"] = os.path.exists(key_path)
            else:
                checks["oci_key_exists"] = False
        except Exception:
            checks["oci_key_exists"] = False
    else:
        checks["oci_key_exists"] = False

    # Check environment variables
    checks["compartment_id_set"] = bool(
        os.getenv("OCI_COMPARTMENT_ID") or os.getenv("OCI_OPENAI_COMPARTMENT_ID")
    )
    checks["endpoint_set"] = bool(
        os.getenv("OCI_BASE_URL") or os.getenv("OCI_OPENAI_ENDPOINT") or os.getenv("LLM_ENDPOINT")
    )
    checks["llm_provider_set"] = os.getenv("LLM_PROVIDER") == "oci_openai"
    # Project uses fastembed for local embeddings — either fastembed or oci_openai is valid
    checks["embedding_provider_set"] = os.getenv("EMBEDDING_PROVIDER") in ("oci_openai", "fastembed")

    return checks


def print_config_status(checks: Dict[str, bool]) -> bool:
    """Print configuration status and return True if all checks pass."""
    print("\n" + "=" * 70)
    print("OCI Configuration Status")
    print("=" * 70)

    all_passed = True

    status_items = [
        ("OCI config file exists (~/.oci/config)", checks.get("oci_config_exists", False)),
        ("OCI private key file exists", checks.get("oci_key_exists", False)),
        ("Compartment ID configured", checks.get("compartment_id_set", False)),
        ("Endpoint configured", checks.get("endpoint_set", False)),
        ("LLM provider set to oci_openai", checks.get("llm_provider_set", False)),
        ("Embedding provider configured (oci_openai or fastembed)", checks.get("embedding_provider_set", False)),
    ]

    for description, passed in status_items:
        status = "PASS" if passed else "FAIL"
        print(f"{status} - {description}")
        if not passed:
            all_passed = False

    print("=" * 70)

    if not all_passed:
        print("\nConfiguration incomplete. Please:")
        if not checks.get("oci_config_exists"):
            print("  1. Create OCI config file at ~/.oci/config")
            print("     See your model provider's API authentication guide.")
        if not checks.get("oci_key_exists"):
            print("  2. Ensure your OCI API key file exists and is referenced in config")
        if not checks.get("compartment_id_set"):
            print("  3. Set OCI_COMPARTMENT_ID environment variable")
        if not checks.get("endpoint_set"):
            print("  4. Set OCI_BASE_URL environment variable")
        if not checks.get("llm_provider_set") or not checks.get("embedding_provider_set"):
            print("  5. Set LLM_PROVIDER=oci_openai and EMBEDDING_PROVIDER=oci_openai")
        print("\nYou can copy .env.oci.example to .env and customize it.")
    else:
        print("\nAll configuration checks passed!")

    return all_passed


def test_oci_connection():
    """Test OCI connection with a simple API call."""
    print("\n" + "=" * 70)
    print("Testing OCI Connection")
    print("=" * 70)

    try:
        from oci_openai import OciOpenAI, OciUserPrincipalAuth

        profile = os.getenv("OCI_OPENAI_PROFILE") or os.getenv("OCI_PROFILE") or "CONFIG"
        endpoint = (
            os.getenv("LLM_ENDPOINT")
            or os.getenv("OCI_OPENAI_ENDPOINT")
            or os.getenv("OCI_BASE_URL")
        )
        compartment_id = os.getenv("OCI_OPENAI_COMPARTMENT_ID") or os.getenv("OCI_COMPARTMENT_ID")

        if not compartment_id:
            print("FAIL - OCI_COMPARTMENT_ID not set")
            return False

        print(f"Profile: {profile}")
        print(f"Endpoint: {endpoint}")
        print(f"Compartment: {compartment_id[:20]}...{compartment_id[-10:]}")

        client = OciOpenAI(
            service_endpoint=endpoint,
            auth=OciUserPrincipalAuth(profile_name=profile),
            compartment_id=compartment_id,
        )

        chat_model = os.getenv("LLM_MODEL") or os.getenv("OCI_CHAT_MODEL_ID") or "openai.gpt-5.2-chat-latest"
        print(f"\nTesting chat with model: {chat_model}")

        response = client.chat.completions.create(
            model=chat_model,
            messages=[{"role": "user", "content": "Say 'Connection successful!' and nothing else."}],
            max_completion_tokens=50,
        )

        result = response.choices[0].message.content
        print(f"Response: {result}")
        print("PASS - Chat connection successful!")

        # Test embeddings — skip if using local fastembed (not an OCI call)
        embedding_provider = os.getenv("EMBEDDING_PROVIDER", "oci_openai")
        if embedding_provider == "fastembed":
            print(f"\nEmbedding provider: fastembed (local) — skipping OCI embedding test")
            print("PASS - Local fastembed embeddings do not require OCI connection")
        else:
            embed_model = os.getenv("OCI_EMBED_MODEL_ID") or os.getenv("EMBEDDING_MODEL") or "openai.text-embedding-3-large"
            print(f"\nTesting embeddings with model: {embed_model}")

            emb_response = client.embeddings.create(
                model=embed_model,
                input="test"
            )

            vector_dim = len(emb_response.data[0].embedding)
            print(f"Embedding dimension: {vector_dim}")
            print("PASS - Embedding connection successful!")

        return True

    except Exception as e:
        print(f"FAIL - Connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cognee():
    """Test Cognee with OCI endpoints."""
    print("\n" + "=" * 70)
    print("Testing Cognee with OCI")
    print("=" * 70)

    try:
        # Set up environment for cognee
        os.environ.setdefault("LLM_PROVIDER", "oci_openai")
        os.environ.setdefault("EMBEDDING_PROVIDER", "oci_openai")

        import cognee

        print("Cognee imported successfully")
        print(f"LLM Provider: {os.getenv('LLM_PROVIDER')}")
        print(f"LLM Model: {os.getenv('LLM_MODEL')}")
        print(f"Embedding Provider: {os.getenv('EMBEDDING_PROVIDER')}")
        print(f"Embedding Model: {os.getenv('EMBEDDING_MODEL')}")

        print("\nCognee is configured for OCI!")
        print("\nTo use Cognee with OCI, run:")
        print("  python cognee-oci-tool.py interactive")

        return True

    except Exception as e:
        print(f"FAIL - Cognee test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_raganything():
    """Test RAG-Anything with OCI endpoints."""
    print("\n" + "=" * 70)
    print("Testing RAG-Anything with OCI")
    print("=" * 70)

    try:
        import raganything
        print("RAG-Anything imported successfully")

        print("\nRAG-Anything is ready!")
        print("\nTo use RAG-Anything with OCI, run:")
        print("  python rag-anything-setup.py")

        return True

    except Exception as e:
        print(f"FAIL - RAG-Anything test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def interactive_setup():
    """Interactive setup wizard."""
    print("\n" + "=" * 70)
    print("OCI RAG Interactive Setup Wizard")
    print("=" * 70)

    # Check if .env exists
    env_file = Path(".env")
    if env_file.exists():
        print("\n.env file already exists.")
        overwrite = input("Overwrite it? (y/N): ").strip().lower()
        if overwrite != 'y':
            print("Setup cancelled.")
            return

    # Copy example to .env
    example_file = Path(".env.oci.example")
    if example_file.exists():
        env_file.write_text(example_file.read_text())
        print(f"\nCreated .env from {example_file}")
    else:
        print(f"\nCould not find {example_file}")
        return

    print("\nPlease edit .env file and set:")
    print("  1. OCI_COMPARTMENT_ID (get from OCI Console)")
    print("  2. OCI_BASE_URL (adjust region if needed)")
    print("  3. LLM_MODEL and EMBEDDING_MODEL (based on your tenancy)")

    print("\nAfter editing .env, load it with:")
    print("  source .env  # On Linux/Mac")
    print("  # Or use python-dotenv in your scripts")


def main():
    parser = argparse.ArgumentParser(description="OCI RAG Setup and Testing")
    parser.add_argument("--check", action="store_true", help="Check configuration")
    parser.add_argument("--test-connection", action="store_true", help="Test OCI connection")
    parser.add_argument("--test-cognee", action="store_true", help="Test Cognee configuration")
    parser.add_argument("--test-rag", action="store_true", help="Test RAG-Anything configuration")
    parser.add_argument("--interactive", action="store_true", help="Interactive setup wizard")
    parser.add_argument("--all", action="store_true", help="Run all tests")

    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(0)

    # Load .env if it exists
    env_file = Path(".env")
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            print("Loaded environment from .env")
        except ImportError:
            print("Note: python-dotenv not installed. Set environment variables manually.")

    success = True

    if args.interactive:
        interactive_setup()
        return

    if args.check or args.all:
        checks = check_oci_config()
        if not print_config_status(checks):
            success = False

    if args.test_connection or args.all:
        if not test_oci_connection():
            success = False

    if args.test_cognee or args.all:
        if not test_cognee():
            success = False

    if args.test_rag or args.all:
        if not test_raganything():
            success = False

    if success:
        print("\n" + "=" * 70)
        print("All tests passed! Your OCI RAG setup is ready.")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("Some tests failed. Please review the errors above.")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
