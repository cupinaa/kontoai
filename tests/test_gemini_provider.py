"""GeminiProvider against a fake SDK client — no network, no API key."""

from types import SimpleNamespace

import pytest

from app.llm.base import LLMError, LLMRequest
from app.llm.gemini import GeminiProvider


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def provider(models: FakeModels, sleeps: list | None = None) -> GeminiProvider:
    return GeminiProvider(
        api_key="unused",
        model="gemini-test",
        client=SimpleNamespace(models=models),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
    )


class RateLimited(Exception):
    code = 429

    def __str__(self):
        return "429 RESOURCE_EXHAUSTED. Quota exceeded. Please retry in 12.5s."


class FlakyModels(FakeModels):
    """Fails with 429 a number of times, then answers."""

    def __init__(self, failures, text):
        super().__init__(text=text)
        self.failures = failures

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise RateLimited()
        return SimpleNamespace(text=self.text)


ANSWER = '{"konto":"101","naziv_konta":"Materijal","sigurnost":0.9,"obrazlozenje":"Sirovina."}'


def test_retries_after_rate_limit_using_server_delay(request_):
    sleeps = []
    models = FlakyModels(failures=2, text=ANSWER)
    answer = provider(models, sleeps).suggest(request_)
    assert answer.konto == "101"
    assert len(models.calls) == 3
    assert sleeps == [13.5, 13.5]  # server-suggested 12.5 s + 1 s margin


def test_gives_up_after_max_retries(request_):
    sleeps = []
    with pytest.raises(LLMError, match="RateLimited"):
        provider(FlakyModels(failures=10, text=ANSWER), sleeps).suggest(request_)
    assert len(sleeps) == 3


def test_daily_quota_is_not_retried(request_):
    class DailyQuota(Exception):
        code = 429

        def __str__(self):
            return "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"

    sleeps = []
    with pytest.raises(LLMError):
        provider(FakeModels(error=DailyQuota()), sleeps).suggest(request_)
    assert sleeps == []


class Overloaded(Exception):
    code = 503


def test_transient_server_errors_use_exponential_backoff(request_):
    class OverloadedModels(FlakyModels):
        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            if self.failures:
                self.failures -= 1
                raise Overloaded("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return SimpleNamespace(text=self.text)

    sleeps = []
    answer = provider(OverloadedModels(failures=2, text=ANSWER), sleeps).suggest(request_)
    assert answer.konto == "101"
    assert sleeps == [3.0, 5.0]  # 2 s, 4 s backoff + 1 s margin


def test_call_budget_counts_every_attempt_including_retries(request_):
    from app.llm.base import CallBudget, CallBudgetExceeded

    budget = CallBudget(2)
    models = FlakyModels(failures=5, text=ANSWER)
    p = GeminiProvider(api_key="unused", model="m", client=SimpleNamespace(models=models),
                       sleep=lambda s: None, budget=budget)
    with pytest.raises(CallBudgetExceeded):
        p.suggest(request_)
    assert len(models.calls) == 2  # third attempt was blocked before sending
    assert budget.used == 2 and budget.exhausted


def test_call_budget_blocks_before_sending(request_):
    from app.llm.base import CallBudget, CallBudgetExceeded

    models = FakeModels(text=ANSWER)
    p = GeminiProvider(api_key="unused", model="m", client=SimpleNamespace(models=models), budget=CallBudget(0))
    with pytest.raises(CallBudgetExceeded):
        p.suggest(request_)
    assert models.calls == []


def test_usage_is_recorded(request_):
    class WithUsage(FakeModels):
        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            meta = SimpleNamespace(prompt_token_count=1000, candidates_token_count=50, thoughts_token_count=200)
            return SimpleNamespace(text=ANSWER, usage_metadata=meta)

    p = provider(WithUsage())
    p.suggest(request_)
    p.suggest(request_)
    assert p.usage == {"calls": 2, "prompt_tokens": 2000, "output_tokens": 100, "thinking_tokens": 400}


def test_non_rate_limit_errors_are_not_retried(request_):
    sleeps = []
    models = FakeModels(error=ValueError("bad request"))
    with pytest.raises(LLMError):
        provider(models, sleeps).suggest(request_)
    assert sleeps == [] and len(models.calls) == 1


@pytest.fixture
def request_(chart) -> LLMRequest:
    return LLMRequest(item_text="Kvasac 1kg", client_activity="Pekara", quantity=3, unit="KGM",
                      amount=660.0, accounts=chart.accounts)


def test_sends_structured_output_request(request_, chart):
    models = FakeModels(text='{"konto":"101","naziv_konta":"Materijal","sigurnost":0.9,"obrazlozenje":"Sirovina."}')

    answer = provider(models).suggest(request_)

    assert answer.konto == "101" and answer.sigurnost == 0.9
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema["properties"]["konto"]["enum"] == chart.codes
    assert set(config.response_json_schema["required"]) == {"konto", "naziv_konta", "sigurnost", "obrazlozenje"}
    assert "Kvasac 1kg" in call["contents"] and "Pekara" in call["contents"]
    assert "101 Materijal" in call["contents"]


def test_sdk_errors_become_llm_errors(request_):
    with pytest.raises(LLMError, match="RuntimeError"):
        provider(FakeModels(error=RuntimeError("quota"))).suggest(request_)


@pytest.mark.parametrize("text", [None, "", "not json", '{"konto": "101"}'])
def test_invalid_responses_become_llm_errors(request_, text):
    with pytest.raises(LLMError):
        provider(FakeModels(text=text)).suggest(request_)
