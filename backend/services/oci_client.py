"""
OCI Client Initialization Service

This module provides singleton instances of OCI clients for use across the application.
Initializes:
- OCI OpenAI client for RAG-Anything
- Shared configuration

Usage:
    from services.oci_client import get_oci_client

    oci_client = get_oci_client()
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
backend_dir = Path(__file__).parent.parent
hld_generator_root = backend_dir.parent
sys.path.insert(0, str(hld_generator_root))

# Load environment variables from .env file
# Check both backend/.env and project root .env
env_file = backend_dir / ".env"
if not env_file.exists():
    env_file = hld_generator_root / ".env"

if env_file.exists():
    load_dotenv(env_file, override=False)
    logger.debug(f"Loaded environment from: {env_file}")
else:
    logger.warning("No .env file found")

# Global instances (singletons)
_oci_client: Optional[object] = None
_initialized: bool = False


def initialize_oci_services():
    """
    Initialize OCI services (OCI client).

    This should be called once on application startup.
    Sets up OCI OpenAI client for RAG-Anything.

    Raises:
        ImportError: If required packages are not installed
        ValueError: If required environment variables are not set
    """
    global _oci_client, _initialized

    if _initialized:
        logger.info("OCI services already initialized")
        return

    try:
        logger.info("Initializing OCI services...")

        # Set local embeddings mode for RAG-Anything
        os.environ["USE_LOCAL_EMBEDDINGS"] = os.getenv("USE_LOCAL_EMBEDDINGS", "true")
        os.environ.setdefault("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

        # Initialize OCI OpenAI client for RAG-Anything
        try:
            from oci_openai import OciOpenAI, OciUserPrincipalAuth

            logger.info("Initializing OCI OpenAI client...")

            # Get configuration from environment
            compartment_id = (
                os.getenv("OCI_COMPARTMENT_ID") or
                os.getenv("OCI_OPENAI_COMPARTMENT_ID")
            )
            profile = os.getenv("OCI_PROFILE", "CONFIG")
            config_file = os.getenv("OCI_CONFIG_FILE", "~/.oci/config")
            base_url = os.getenv("OCI_BASE_URL") or os.getenv("OCI_OPENAI_ENDPOINT")

            if not compartment_id:
                raise ValueError(
                    "OCI_COMPARTMENT_ID must be set in environment variables or .env file"
                )
            if not base_url:
                raise ValueError("OCI_BASE_URL or OCI_OPENAI_ENDPOINT must be set")

            # Initialize OCI authentication
            auth = OciUserPrincipalAuth(
                profile_name=profile,
                config_file=os.path.expanduser(config_file)
            )

            # Create OCI OpenAI client
            _oci_client = OciOpenAI(
                auth=auth,
                service_endpoint=base_url,
                compartment_id=compartment_id
            )

            logger.info(f"OCI OpenAI client initialized successfully")
            logger.info(f"  Profile: {profile}")
            logger.info(f"  Endpoint: {base_url}")
            logger.info(f"  Compartment: {compartment_id[:20]}...")

        except ImportError as e:
            logger.error(f"Failed to import oci-openai package: {e}")
            logger.error("Install with: pip install oci-openai")
            raise

        _initialized = True
        logger.info("OCI services initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize OCI services: {e}")
        logger.error("Please check your .env configuration and ~/.oci/config file")
        raise


def get_oci_client():
    """
    Get the singleton OCI OpenAI client instance.

    Returns:
        OciOpenAI client instance

    Raises:
        RuntimeError: If OCI services have not been initialized
    """
    global _oci_client

    if not _initialized:
        raise RuntimeError(
            "OCI services not initialized. Call initialize_oci_services() first."
        )

    if _oci_client is None:
        raise RuntimeError("OCI client failed to initialize")

    return _oci_client


def is_initialized() -> bool:
    """
    Check if OCI services have been initialized.

    Returns:
        True if initialized, False otherwise
    """
    return _initialized


def reset_oci_services():
    """
    Reset OCI services (for testing purposes).

    This clears the singleton instances and allows re-initialization.
    """
    global _oci_client, _initialized

    _oci_client = None
    _initialized = False

    logger.info("OCI services reset")


# ============================================================================
# Resource Pool Factory Functions
# ============================================================================
# These functions create new instances for the resource pool
# (as opposed to singletons above)


async def _create_oci_client():
    """
    Factory function to create a new OCI OpenAI client instance.
    Used by ResourcePool to create pooled clients.

    Returns:
        OciOpenAI client instance

    Raises:
        ValueError: If required environment variables are not set
    """
    try:
        from oci_openai import OciOpenAI, OciUserPrincipalAuth

        logger.debug("Creating new OCI OpenAI client for resource pool...")

        # Get configuration from environment
        compartment_id = (
            os.getenv("OCI_COMPARTMENT_ID") or
            os.getenv("OCI_OPENAI_COMPARTMENT_ID")
        )
        profile = os.getenv("OCI_PROFILE", "CONFIG")
        config_file = os.getenv("OCI_CONFIG_FILE", "~/.oci/config")
        base_url = os.getenv("OCI_BASE_URL") or os.getenv("OCI_OPENAI_ENDPOINT")

        if not compartment_id:
            raise ValueError(
                "OCI_COMPARTMENT_ID must be set in environment variables or .env file"
            )
        if not base_url:
            raise ValueError("OCI_BASE_URL or OCI_OPENAI_ENDPOINT must be set")

        # Initialize OCI authentication
        auth = OciUserPrincipalAuth(
            profile_name=profile,
            config_file=os.path.expanduser(config_file)
        )

        # Create OCI OpenAI client
        client = OciOpenAI(
            auth=auth,
            service_endpoint=base_url,
            compartment_id=compartment_id
        )

        logger.debug("OCI OpenAI client created successfully for pool")
        return client

    except ImportError as e:
        logger.error(f"Failed to import oci-openai package: {e}")
        logger.error("Install with: pip install oci-openai")
        raise
    except Exception as e:
        logger.error(f"Failed to create OCI client: {e}")
        raise
