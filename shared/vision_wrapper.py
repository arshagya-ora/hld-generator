"""
OCI GenAI Vision Wrapper for image analysis.

Uses the OCI GenAI chat endpoint with multimodal support (TextContent + ImageContent)
to analyze technical diagrams and images extracted from documents.

Image format: data URL  →  data:{mime_type};base64,{encoded}
Image model:  ImageContent.image_url = ImageUrl(url=data_url)

This mirrors the pattern from the tested OCI image-input CLI script.
"""

import base64
import mimetypes
import os
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import oci
    OCI_SDK_AVAILABLE = True
except ImportError:
    OCI_SDK_AVAILABLE = False

from hld_generator.shared.logging_config import setup_logger

logger = setup_logger(__name__)


# Default prompt for technical diagram analysis
DEFAULT_ANALYSIS_PROMPT = """Analyze this technical diagram. Provide a JSON response with:
{
  "type": "what kind of diagram is this (e.g., network_topology, component_diagram, deployment_diagram, flow_chart, architecture_diagram, sequence_diagram, table_screenshot, other)",
  "components_shown": ["list of products/systems/elements visible"],
  "text_elements": {
    "site_names": ["any site or location names visible"],
    "ip_addresses": ["any IP addresses or network ranges"],
    "labels": ["other significant text labels"]
  },
  "purpose": "what does this diagram illustrate",
  "technical_depth": "overview or detailed or reference",
  "relationships_shown": ["list of connections/flows/relationships depicted"],
  "diagram_complexity": "low or medium or high",
  "professional_quality": "low or medium or high"
}

Respond ONLY with the JSON object, no other text."""


class OCIVisionWrapper:
    """
    Wrapper around OCI GenAI chat endpoint for multimodal (text + image) queries.

    Uses the exact same SDK pattern as the tested OCI image-input CLI:
        text_content = TextContent(text=prompt)
        image_content = ImageContent()
        image_content.image_url = ImageUrl(url="data:{mime};base64,{b64}")
        message.content = [text_content, image_content]
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
        self.model_id = model_id or os.getenv(
            "VISION_MODEL_ID",
            os.getenv("OCI_GENAI_MODEL_ID", ""),
        )
        _profile = config_profile or os.getenv("OCI_PROFILE", "DEFAULT")
        _config_file = config_file or os.getenv(
            "OCI_CONFIG_FILE", os.path.expanduser("~/.oci/config")
        )
        _endpoint = endpoint or os.getenv("OCI_GENAI_ENDPOINT") or os.getenv("OCI_BASE_URL")

        if not self.compartment_id:
            raise ValueError("OCI_COMPARTMENT_ID must be set")
        if not self.model_id:
            raise ValueError("VISION_MODEL_ID or OCI_GENAI_MODEL_ID must be set")
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
    # Encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def encode_image_to_data_url(
        image_bytes: bytes, mime_type: str = "image/png"
    ) -> str:
        """Encode raw image bytes into a data URL string."""
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def encode_image_file_to_data_url(
        image_path: str, mime_override: Optional[str] = None
    ) -> str:
        """Read an image file and return its data URL."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        mime_type = mime_override
        if not mime_type:
            guessed, _ = mimetypes.guess_type(str(path))
            mime_type = guessed or "image/png"

        with path.open("rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return f"data:{mime_type};base64,{encoded}"

    # ------------------------------------------------------------------
    # Core OCI chat call
    # ------------------------------------------------------------------

    def _call_chat(self, data_url: str, prompt: str, max_tokens: int = 2048) -> str:
        """
        Send text + image to OCI GenAI chat endpoint (synchronous).

        Follows the exact tested OCI SDK pattern:
            TextContent  → prompt
            ImageContent → ImageUrl(url=data_url)
        """
        text_content = oci.generative_ai_inference.models.TextContent()
        text_content.text = prompt

        image_content = oci.generative_ai_inference.models.ImageContent()
        image_content.image_url = oci.generative_ai_inference.models.ImageUrl(
            url=data_url
        )

        message = oci.generative_ai_inference.models.Message()
        message.role = "USER"
        message.content = [text_content, image_content]

        chat_request = oci.generative_ai_inference.models.GenericChatRequest()
        chat_request.messages = [message]
        chat_request.api_format = (
            oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
        )
        chat_request.max_completion_tokens = max_tokens

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
                    return " ".join(
                        item.text for item in content if hasattr(item, "text")
                    )
                if isinstance(content, str):
                    return content
        return ""

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def analyze_image(
        self,
        image_data: bytes,
        prompt: Optional[str] = None,
        mime_type: str = "image/png",
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """
        Analyze an image using OCI GenAI multimodal chat.

        Args:
            image_data: Raw image bytes (PNG, JPEG, etc.)
            prompt: Analysis prompt (defaults to technical diagram prompt)
            mime_type: MIME type of the image
            max_tokens: Max response tokens

        Returns:
            Parsed analysis dict with type, components, purpose, etc.
        """
        prompt = prompt or DEFAULT_ANALYSIS_PROMPT
        data_url = self.encode_image_to_data_url(image_data, mime_type)

        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(
            None, self._call_chat, data_url, prompt, max_tokens
        )
        return self._parse_analysis_response(raw_response)

    async def analyze_image_file(
        self,
        image_path: str,
        prompt: Optional[str] = None,
        mime_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze an image from a file path."""
        data_url = self.encode_image_file_to_data_url(image_path, mime_override)
        prompt = prompt or DEFAULT_ANALYSIS_PROMPT

        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(
            None, self._call_chat, data_url, prompt
        )
        return self._parse_analysis_response(raw_response)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_analysis_response(raw_response: str) -> Dict[str, Any]:
        """Parse the model response into a structured dict."""
        _defaults = {
            "type": "unknown",
            "components_shown": [],
            "text_elements": {},
            "purpose": "",
            "technical_depth": "unknown",
            "relationships_shown": [],
            "diagram_complexity": "unknown",
            "professional_quality": "unknown",
        }

        if not raw_response:
            return {**_defaults, "raw_response": ""}

        # Strip markdown code-fence wrappers if present
        text = raw_response.strip()
        for prefix in ("```json", "```"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            parsed = json.loads(text)
            for key, default in _defaults.items():
                parsed.setdefault(key, default)
            return parsed
        except (json.JSONDecodeError, ValueError):
            return {**_defaults, "purpose": raw_response[:500], "raw_response": raw_response}
