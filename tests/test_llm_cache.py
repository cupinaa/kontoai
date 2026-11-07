from app.llm.base import AnalyticOption, AnalyticRequest, LLMError, LLMRequest
from app.llm.cache import MemoryCachedProvider
from tests.conftest import FakeLLM


def request(text: str, chart) -> LLMRequest:
    return LLMRequest(item_text=text, client_activity="x", accounts=chart.accounts)


def test_identical_requests_are_answered_once(chart):
    inner = FakeLLM()
    cached = MemoryCachedProvider(inner)
    cached.suggest(request("A", chart))
    cached.suggest(request("A", chart))
    cached.suggest(request("B", chart))
    assert len(inner.requests) == 2 and cached.hits == 1


def test_analytic_and_synthetic_are_cached_separately(chart):
    inner = FakeLLM()
    cached = MemoryCachedProvider(inner)
    a = AnalyticRequest(item_text="A", client_activity="x", konto="533", konto_naziv="z",
                        options=[AnalyticOption(konto="5330", naziv="p"), AnalyticOption(konto="5331", naziv="m")])
    cached.choose_analytic(a)
    cached.choose_analytic(a)
    cached.suggest(request("A", chart))
    assert len(inner.analytic_requests) == 1 and len(inner.requests) == 1 and cached.hits == 1


def test_errors_are_not_cached(chart):
    inner = FakeLLM(error=LLMError("down"))
    cached = MemoryCachedProvider(inner)
    for _ in range(2):
        try:
            cached.suggest(request("A", chart))
        except LLMError:
            pass
    assert len(inner.requests) == 2 and cached.hits == 0


def test_oldest_entries_are_evicted(chart):
    inner = FakeLLM()
    cached = MemoryCachedProvider(inner, max_entries=2)
    for text in ("A", "B", "C", "A"):
        cached.suggest(request(text, chart))
    assert len(inner.requests) == 4  # "A" was evicted before it was asked again
