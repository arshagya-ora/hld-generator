"""
OCI GenAI LLM Wrapper for text-only chat completions.

Mirrors the OCIVisionWrapper pattern but for text-only (no image) calls.
Used by agents that need direct LLM reasoning (e.g., Blueprint Agent)
without going through Cognee. Cognee is reserved for multi-agent shared
context retrieval.

Supports:
  - Synchronous call wrapped in async via run_in_executor
  - System + user message pattern
  - JSON response parsing
"""

import asyncio
import json
import os
import re
import logging
import time
from typing import Dict, Any, Optional, List, Callable

try:
    import oci
    OCI_SDK_AVAILABLE = True
except ImportError:
    OCI_SDK_AVAILABLE = False

from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


def retry_with_exponential_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Retry decorator with exponential backoff for LLM calls.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Multiplier for delay after each retry (default: 2.0)
        max_delay: Maximum delay between retries (default: 60.0)
        retryable_exceptions: Tuple of exceptions to retry on (default: all)

    Returns:
        Decorated function with retry logic

    Retry schedule (default): 0s → 1s → 2s → 4s → fail
    """
    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(f"LLM call failed after {max_retries} retries: {e}")
                        raise

                    # Log retry attempt
                    logger.warning(
                        f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    logger.info(f"Retrying in {delay:.1f}s...")

                    # Wait with exponential backoff
                    await asyncio.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            raise last_exception

        # Return async wrapper (all our LLM calls are async)
        return async_wrapper

    return decorator


class OCILLMWrapper:
    """
    Wrapper around OCI GenAI chat endpoint for text-only completions.

    Uses the same SDK pattern as OCIVisionWrapper but without image content.
    """

    def __init__(
        self,
        compartment_id: Optional[str] = None,
        model_id: Optional[str] = None,
        config_profile: Optional[str] = None,
        config_file: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        if not OCI_SDK_AVAILABLE:
            raise ImportError("OCI SDK is required. Install with: pip install oci")

        self.compartment_id = (
            compartment_id
            or os.getenv("OCI_COMPARTMENT_ID")
            or os.getenv("OCI_OPENAI_COMPARTMENT_ID")
        )
        self.model_id = (
            model_id
            or os.getenv("OCI_GENAI_MODEL_ID")
            or os.getenv("OCI_CHAT_MODEL_ID")
            or os.getenv("LLM_MODEL")
        )
        _profile = config_profile or os.getenv("OCI_PROFILE", "DEFAULT")
        _config_file = config_file or os.getenv(
            "OCI_CONFIG_FILE", os.path.expanduser("~/.oci/config")
        )
        _endpoint = endpoint or os.getenv("OCI_GENAI_ENDPOINT") or os.getenv("OCI_BASE_URL")

        if not self.compartment_id:
            raise ValueError("OCI_COMPARTMENT_ID must be set")
        if not self.model_id:
            raise ValueError("OCI_GENAI_MODEL_ID must be set")
        if not _endpoint:
            raise ValueError("OCI_GENAI_ENDPOINT or OCI_BASE_URL must be set")

        config = oci.config.from_file(_config_file, _profile)
        self.client = oci.generative_ai_inference.GenerativeAiInferenceClient(
            config,
            service_endpoint=_endpoint,
            retry_strategy=oci.retry.NoneRetryStrategy(),
            timeout=(10, 240),
        )

    # ------------------------------------------------------------------
    # Core OCI chat call (synchronous)
    # ------------------------------------------------------------------

    def _call_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send system + user messages to OCI GenAI chat endpoint.

        Returns the raw text response.
        """
        system_message = oci.generative_ai_inference.models.Message()
        system_message.role = "SYSTEM"
        system_content = oci.generative_ai_inference.models.TextContent()
        system_content.text = system_prompt
        system_message.content = [system_content]

        user_message = oci.generative_ai_inference.models.Message()
        user_message.role = "USER"
        user_content = oci.generative_ai_inference.models.TextContent()
        user_content.text = user_prompt
        user_message.content = [user_content]

        chat_request = oci.generative_ai_inference.models.GenericChatRequest()
        chat_request.messages = [system_message, user_message]
        chat_request.api_format = (
            oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
        )
        chat_request.max_completion_tokens = max_tokens
        # Some OCI-hosted reasoning models reject explicit temperature values except default behavior.
        if temperature is not None and float(temperature) == 1.0:
            chat_request.temperature = temperature

        chat_detail = oci.generative_ai_inference.models.ChatDetails()
        chat_detail.serving_mode = (
            oci.generative_ai_inference.models.OnDemandServingMode(
                model_id=self.model_id
            )
        )
        chat_detail.chat_request = chat_request
        chat_detail.compartment_id = self.compartment_id

        response = self.client.chat(chat_detail)

        # Extract text from response
        chat_response = response.data.chat_response
        if hasattr(chat_response, "choices") and chat_response.choices:
            choice = chat_response.choices[0]
            if hasattr(choice, "message") and choice.message:
                content = choice.message.content
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if hasattr(item, "text") and getattr(item, "text"):
                            text_parts.append(getattr(item, "text"))
                            continue
                        if isinstance(item, dict) and item.get("text"):
                            text_parts.append(item["text"])
                            continue
                        try:
                            item_dict = oci.util.to_dict(item)
                            if isinstance(item_dict, dict) and item_dict.get("text"):
                                text_parts.append(item_dict["text"])
                        except Exception:
                            continue
                    return " ".join(text_parts).strip()
                if isinstance(content, str):
                    return content
        return ""

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    @retry_with_exponential_backoff(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        retryable_exceptions=(Exception,)  # Retry on any exception
    )
    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Async wrapper around _call_chat.

        Returns raw text response from the LLM.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._call_chat, system_prompt, user_prompt, max_tokens, temperature
        )

    @retry_with_exponential_backoff(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0,
        retryable_exceptions=(Exception,)
    )
    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
    ) -> Any:
        """
        Call the LLM and parse the response as JSON.

        Handles markdown code fences and other common wrapping.
        Returns parsed JSON (dict or list), or None on parse failure.
        """
        raw = await self.chat(system_prompt, user_prompt, max_tokens, temperature)
        return self.parse_json_response(raw)

    # ------------------------------------------------------------------
    # JSON parsing utilities
    # ------------------------------------------------------------------

    @staticmethod
    def parse_json_response(raw_response: str) -> Any:
        """
        Parse JSON from an LLM response, handling common formatting.

        Handles:
          - Direct JSON
          - ```json ... ``` code fences
          - ``` ... ``` code fences
          - JSON embedded in surrounding text
        """
        if not raw_response:
            return None

        text = raw_response.strip()

        # Strip markdown code fences
        for prefix in ("```json", "```"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code blocks
        patterns = [
            r"```json\s*(.*?)```",
            r"```\s*(.*?)```",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, raw_response, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match.strip())
                except json.JSONDecodeError:
                    continue

        # Try to find a JSON array or object in the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start_idx = text.find(start_char)
            if start_idx == -1:
                continue
            # Find matching end bracket
            depth = 0
            for i in range(start_idx, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start_idx : i + 1])
                        except json.JSONDecodeError:
                            break

        logger.warning(f"Failed to parse JSON from LLM response ({len(raw_response)} chars)")
        return None
