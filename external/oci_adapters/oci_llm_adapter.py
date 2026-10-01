"""
Simple OCI LLM Adapter for direct OCI GenAI usage.

This replaces the deleted oci_cognee_adapter module with a minimal implementation
that directly uses OCI OpenAI for LLM completions.
"""

import os
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class OCIConfig:
    """Configuration for OCI GenAI"""
    model: str = None
    base_url: str = None
    compartment_id: str = None
    profile: str = "CONFIG"
    max_tokens: int = 4096

    def __post_init__(self):
        """Load from environment if not provided"""
        if self.model is None:
            # Try multiple env vars for model ID (prioritize newer naming)
            self.model = (
                os.getenv("LLM_MODEL") or
                os.getenv("OCI_CHAT_MODEL_ID") or
                os.getenv("OCI_GENAI_MODEL_ID") or
                os.getenv("OCI_GENAI_MODEL")
            )
            if not self.model:
                raise ValueError(
                    "No LLM model configured. Set LLM_MODEL, OCI_CHAT_MODEL_ID, or OCI_GENAI_MODEL_ID in .env"
                )
        if self.base_url is None:
            self.base_url = os.getenv("OCI_BASE_URL")
        if not self.base_url:
            raise ValueError("OCI_BASE_URL must be set")
        if self.compartment_id is None:
            self.compartment_id = os.getenv("OCI_COMPARTMENT_ID")


class OCILLMAdapter:
    """
    Minimal OCI LLM adapter for chat completions.

    Provides a simple async interface to OCI GenAI without Cognee dependency.
    """

    def __init__(self, config: Optional[OCIConfig] = None):
        """
        Initialize OCI LLM adapter.

        Args:
            config: Optional OCIConfig. If None, loads from environment.
        """
        self.config = config or OCIConfig()
        self.model = self.config.model
        self._client = None

    def _get_client(self):
        """Lazy initialization of OCI OpenAI client"""
        if self._client is None:
            from oci_openai import OciOpenAI, OciUserPrincipalAuth

            auth = OciUserPrincipalAuth(
                profile_name=self.config.profile,
                config_file=os.path.expanduser("~/.oci/config")
            )

            self._client = OciOpenAI(
                auth=auth,
                service_endpoint=self.config.base_url,
                compartment_id=self.config.compartment_id
            )

        return self._client

    async def create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs
    ) -> str:
        """
        Create a chat completion using OCI GenAI.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0 to 1.0)
            **kwargs: Additional arguments (ignored for compatibility)

        Returns:
            Response text from the LLM
        """
        client = self._get_client()

        # IMPORTANT: OCI GenAI models now only support temperature=1 (default)
        # Do NOT pass temperature parameter - let it use the default
        # Passing any value other than 1 will cause a 400 Bad Request error

        # Prepare API call parameters
        # Note: Newer OCI models use 'max_completion_tokens' instead of 'max_tokens'
        completion_params = {
            "model": self.model,
            "messages": messages,
            # temperature intentionally omitted - OCI only supports default (1.0)
        }

        # Try max_completion_tokens first (newer API), fallback to max_tokens
        token_limit = max_tokens or self.config.max_tokens
        try:
            # Newer OCI OpenAI-compatible models use max_completion_tokens
            completion_params["max_completion_tokens"] = token_limit
            response = client.chat.completions.create(**completion_params)
        except Exception as e:
            # If max_completion_tokens fails, try max_tokens (older API)
            if "max_completion_tokens" in str(e):
                completion_params.pop("max_completion_tokens", None)
                completion_params["max_tokens"] = token_limit
                response = client.chat.completions.create(**completion_params)
            else:
                raise

        return response.choices[0].message.content
