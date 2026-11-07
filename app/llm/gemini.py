"""Google Gemini implementation of `LLMProvider`, using the official google-genai SDK."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.llm.base import SYSTEM_PROMPT, LLMError, LLMProvider, LLMRequest, LLMSuggestion, build_user_prompt


def response_schema(allowed_codes: list[str]) -> dict[str, Any]:
    """JSON schema for structured output. The enum restricts decoding to our accounts."""
    return {
        "type": "object",
        "properties": {
            "konto": {"type": "string", "enum": allowed_codes, "description": "Trocifreni konto iz spiska"},
            "naziv_konta": {"type": "string", "description": "Naziv izabranog konta"},
            "sigurnost": {"type": "number", "minimum": 0, "maximum": 1, "description": "Sigurnost 0-1"},
            "obrazlozenje": {"type": "string", "description": "Kratko obrazloženje na srpskom"},
        },
        "required": ["konto", "naziv_konta", "sigurnost", "obrazlozenje"],
        "propertyOrdering": ["konto", "naziv_konta", "sigurnost", "obrazlozenje"],
    }


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, *, client: Any = None, timeout_ms: int = 30_000):
        self.model = model
        if client is None:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))
        self._client = client

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=response_schema([a.konto for a in request.accounts]),
            temperature=0.0,
        )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=build_user_prompt(request), config=config
            )
        except Exception as exc:  # SDK raises several error types (network, quota, auth)
            raise LLMError(f"Gemini poziv nije uspeo: {type(exc).__name__}: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini je vratio prazan odgovor.")
        try:
            return LLMSuggestion.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"Gemini odgovor ne odgovara šemi: {exc.error_count()} grešaka") from exc
