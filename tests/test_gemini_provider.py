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


def provider(models: FakeModels) -> GeminiProvider:
    return GeminiProvider(api_key="unused", model="gemini-test", client=SimpleNamespace(models=models))


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
