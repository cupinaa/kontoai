"""In-memory cache for identical (already masked) LLM requests.

Re-uploading the same invoice, or several invoices with the same line text for the same client,
sends the same masked request again. At temperature 0 the answer is the same, so it is reused
instead of paid for again. Only successful answers are cached; the cache lives only as long as
the server process.
"""

from __future__ import annotations

from collections import OrderedDict

from app.llm.base import AnalyticChoice, AnalyticRequest, LLMProvider, LLMRequest, LLMSuggestion


class MemoryCachedProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, max_entries: int = 2000):
        self.inner = inner
        self.name, self.model = inner.name, inner.model
        self.max_entries = max_entries
        self.hits = 0
        self._cache: OrderedDict[str, LLMSuggestion | AnalyticChoice] = OrderedDict()

    # Budget and token usage belong to the real provider; expose them for /health.
    @property
    def budget(self):
        return getattr(self.inner, "budget", None)

    @property
    def usage(self):
        return getattr(self.inner, "usage", None)

    def _get_or_call(self, key: str, call):
        if key in self._cache:
            self.hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        answer = call()
        self._cache[key] = answer
        if len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return answer

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        return self._get_or_call("s:" + request.model_dump_json(), lambda: self.inner.suggest(request))

    def choose_analytic(self, request: AnalyticRequest) -> AnalyticChoice:
        return self._get_or_call("a:" + request.model_dump_json(), lambda: self.inner.choose_analytic(request))
