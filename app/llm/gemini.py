"""Google Gemini implementation of `LLMProvider`, using the official google-genai SDK."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import (
    ANALYTIC_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    AnalyticChoice,
    AnalyticRequest,
    CallBudget,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMSuggestion,
    build_analytic_prompt,
    build_user_prompt,
)

T = TypeVar("T", bound=BaseModel)


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


def analytic_schema(allowed_codes: list[str]) -> dict[str, Any]:
    """JSON schema for the analytic choice; the enum contains only the offered analytic accounts."""
    return {
        "type": "object",
        "properties": {
            "konto": {"type": "string", "enum": allowed_codes, "description": "Analitički konto iz ponuđenog spiska"},
            "sigurnost": {"type": "number", "minimum": 0, "maximum": 1, "description": "Sigurnost 0-1"},
            "obrazlozenje": {"type": "string", "description": "Kratko obrazloženje na srpskom"},
        },
        "required": ["konto", "sigurnost", "obrazlozenje"],
        "propertyOrdering": ["konto", "sigurnost", "obrazlozenje"],
    }


log = logging.getLogger(__name__)

_RETRY_IN = re.compile(r"retry in\s+([\d.]+)\s*s", re.IGNORECASE)
_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?([\d.]+)s")
_TRANSIENT_CODES = {500, 502, 503, 504}


def _retry_after(exc: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying `exc`, or None if it is not worth retrying.

    429 (quota) uses the delay suggested by the server; transient 5xx errors
    ("model is experiencing high demand") use exponential backoff: 2, 4, 8 s...
    """
    code = getattr(exc, "code", None)
    if code == 429:
        text = str(exc)
        if "PerDay" in text:
            return None  # daily quota exhausted: retrying within seconds cannot succeed
        match = _RETRY_IN.search(text) or _RETRY_DELAY.search(text)
        return float(match.group(1)) if match else 10.0
    if code in _TRANSIENT_CODES:
        return 2.0 ** (attempt + 1)
    return None


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: Any = None,
        timeout_ms: int = 90_000,  # thinking models can need well over 30 s; shorter values cause 504s
        max_retries: int = 3,
        max_retry_wait: float = 65.0,
        sleep: Callable[[float], None] = time.sleep,
        budget: CallBudget | None = None,
    ):
        self.model = model
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self.budget = budget
        self._sleep = sleep
        # Token usage summed over all successful responses (for cost reporting).
        self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        if client is None:
            from google import genai
            from google.genai import types

            # SDK-level retries are disabled explicitly: the only retries are the ones below,
            # so every real HTTP request is counted against `budget`.
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)),
            )
        self._client = client

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        return self._generate(
            SYSTEM_PROMPT,
            build_user_prompt(request),
            response_schema([a.konto for a in request.accounts]),
            LLMSuggestion,
        )

    def choose_analytic(self, request: AnalyticRequest) -> AnalyticChoice:
        return self._generate(
            ANALYTIC_SYSTEM_PROMPT,
            build_analytic_prompt(request),
            analytic_schema([o.konto for o in request.options]),
            AnalyticChoice,
        )

    def _generate(self, system: str, prompt: str, schema: dict[str, Any], model_cls: type[T]) -> T:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.0,
        )
        attempt = 0
        while True:
            if self.budget is not None:
                self.budget.consume()  # raises CallBudgetExceeded before anything is sent
            try:
                response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
                break
            except Exception as exc:  # SDK raises several error types (network, quota, auth)
                wait = _retry_after(exc, attempt)
                if wait is not None and attempt < self.max_retries and wait <= self.max_retry_wait:
                    attempt += 1
                    log.info("Gemini error %s, retry %d/%d in %.0fs",
                             getattr(exc, "code", "?"), attempt, self.max_retries, wait + 1)
                    self._sleep(wait + 1)
                    continue
                summary = str(exc).splitlines()[0][:200]
                raise LLMError(f"Gemini poziv nije uspeo: {type(exc).__name__}: {summary}") from exc

        self._record_usage(response)
        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini je vratio prazan odgovor.")
        try:
            return model_cls.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"Gemini odgovor ne odgovara šemi: {exc.error_count()} grešaka") from exc

    def _record_usage(self, response: Any) -> None:
        meta = getattr(response, "usage_metadata", None)
        self.usage["calls"] += 1
        if meta is None:
            return
        self.usage["prompt_tokens"] += getattr(meta, "prompt_token_count", None) or 0
        self.usage["output_tokens"] += getattr(meta, "candidates_token_count", None) or 0
        self.usage["thinking_tokens"] += getattr(meta, "thoughts_token_count", None) or 0
