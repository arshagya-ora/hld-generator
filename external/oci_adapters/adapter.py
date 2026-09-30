import base64
import mimetypes
from typing import Type, Optional

import instructor
from pydantic import BaseModel
from openai import ContentFilterFinishReasonError
from instructor.core import InstructorRetryException

from cognee.infrastructure.llm.structured_output_framework.litellm_instructor.llm.llm_interface import (
    LLMInterface,
)
from cognee.infrastructure.llm.exceptions import ContentPolicyFilterError
from cognee.infrastructure.files.utils.open_data_file import open_data_file
from cognee.infrastructure.llm.structured_output_framework.litellm_instructor.llm.types import (
    TranscriptionReturnType,
)
from cognee.shared.rate_limiting import llm_rate_limiter_context_manager
from cognee.modules.observability.get_observe import get_observe
from cognee.shared.logging_utils import get_logger
from cognee.infrastructure.llm.oci_openai_utils import (
    build_oci_openai_auth,
    resolve_oci_openai_connection_params,
)

from oci_openai import AsyncOciOpenAI, OciOpenAI

logger = get_logger()
observe = get_observe()


class OCIOpenAIAdapter(LLMInterface):
    """
    Adapter for OCI OpenAI-compatible endpoints via oci-openai.

    Public methods:
    - acreate_structured_output
    - create_transcript
    - transcribe_image
    """

    default_instructor_mode = "json_mode"
    MAX_RETRIES = 5

    def __init__(
        self,
        api_key: Optional[str],
        model: str,
        max_completion_tokens: int,
        endpoint: str = None,
        api_version: str = None,
        transcription_model: str = None,
        image_transcribe_model: str = None,
        instructor_mode: str = None,
        streaming: bool = False,
        fallback_model: str = None,
        fallback_api_key: str = None,
        fallback_endpoint: str = None,
    ):
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.transcription_model = transcription_model or model
        self.image_transcribe_model = image_transcribe_model or model
        self.streaming = streaming

        # OCI authentication + connection params are resolved from environment variables
        # and optional endpoint argument (LLM_ENDPOINT).
        self._auth = build_oci_openai_auth()
        self._conn_params = resolve_oci_openai_connection_params(endpoint)

        self._raw_async_client = AsyncOciOpenAI(auth=self._auth, **self._conn_params)
        self._raw_client = OciOpenAI(auth=self._auth, **self._conn_params)

        self.instructor_mode = (
            instructor_mode if instructor_mode else self.default_instructor_mode
        )
        if str(self.instructor_mode).lower() == "json_schema_mode":
            # instructor.from_openai does not allow JSON_SCHEMA for OpenAI provider
            self.instructor_mode = "json_mode"
        self.aclient = instructor.from_openai(
            self._raw_async_client, mode=instructor.Mode(self.instructor_mode)
        )
        self.client = instructor.from_openai(
            self._raw_client, mode=instructor.Mode(self.instructor_mode)
        )

        self.fallback_model = fallback_model
        self.fallback_endpoint = fallback_endpoint
        self.fallback_api_key = fallback_api_key

        self._fallback_aclient = None
        if self.fallback_model:
            fallback_params = resolve_oci_openai_connection_params(self.fallback_endpoint)
            self._fallback_raw_async_client = AsyncOciOpenAI(
                auth=self._auth, **fallback_params
            )
            self._fallback_aclient = instructor.from_openai(
                self._fallback_raw_async_client, mode=instructor.Mode(self.instructor_mode)
            )

    @observe(as_type="generation")
    async def acreate_structured_output(
        self, text_input: str, system_prompt: str, response_model: Type[BaseModel], **kwargs
    ) -> BaseModel:
        try:
            async with llm_rate_limiter_context_manager():
                return await self.aclient.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": f"""{text_input}""",
                        },
                    ],
                    max_completion_tokens=self.max_completion_tokens,
                    response_model=response_model,
                    max_retries=self.MAX_RETRIES,
                    **kwargs,
                )
        except (ContentFilterFinishReasonError, InstructorRetryException) as e:
            if not self._fallback_aclient:
                raise e
            try:
                async with llm_rate_limiter_context_manager():
                    return await self._fallback_aclient.chat.completions.create(
                        model=self.fallback_model,
                        messages=[
                            {
                                "role": "system",
                                "content": system_prompt,
                            },
                            {
                                "role": "user",
                                "content": f"""{text_input}""",
                            },
                        ],
                        max_completion_tokens=self.max_completion_tokens,
                        response_model=response_model,
                        max_retries=self.MAX_RETRIES,
                        **kwargs,
                    )
            except (ContentFilterFinishReasonError, InstructorRetryException) as error:
                if (
                    isinstance(error, InstructorRetryException)
                    and "content management policy" not in str(error).lower()
                ):
                    raise error
                raise ContentPolicyFilterError(
                    f"The provided input contains content that is not aligned with our content policy: {text_input}"
                ) from error

    @observe(as_type="transcription")
    async def create_transcript(self, input) -> TranscriptionReturnType:
        async with open_data_file(input, mode="rb") as audio_file:
            transcription = await self._raw_async_client.audio.transcriptions.create(
                model=self.transcription_model,
                file=audio_file,
            )
            return TranscriptionReturnType(transcription.text, transcription)

    @observe(as_type="transcribe_image")
    async def transcribe_image(self, input) -> BaseModel:
        async with open_data_file(input, mode="rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
        mime_type, _ = mimetypes.guess_type(input)
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(
                f"Could not determine MIME type for image file: {input}. Is the extension correct?"
            )
        response = await self._raw_async_client.chat.completions.create(
            model=self.image_transcribe_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded_image}",
                            },
                        },
                    ],
                }
            ],
            max_tokens=300,
        )
        return response
