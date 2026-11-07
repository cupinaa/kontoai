"""Safe mode: KONTOAI_DISABLE_LLM must win over any key (environment or .env)."""

import pytest

from app import config


@pytest.mark.parametrize("value", ["1", "true", "YES", "da"])
def test_disable_llm_ignores_key(monkeypatch, value):
    monkeypatch.setenv("GEMINI_API_KEY", "a-key-that-must-not-be-used")
    monkeypatch.setenv("KONTOAI_DISABLE_LLM", value)
    assert config.get_settings().gemini_api_key is None


def test_disable_llm_ignores_key_from_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("KONTOAI_DISABLE_LLM", "1")
    assert config.get_settings().gemini_api_key is None
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # load_dotenv put it into os.environ


def test_server_call_cap_is_enforced_and_reported(monkeypatch, settings):
    """KONTOAI_MAX_LLM_CALLS caps real requests for the whole server; /health reports usage."""
    from dataclasses import replace
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.llm import gemini
    from app.main import create_app

    sent = []

    class Models:
        def generate_content(self, **kwargs):
            sent.append(kwargs)
            meta = SimpleNamespace(prompt_token_count=100, candidates_token_count=10, thoughts_token_count=5)
            return SimpleNamespace(text='{"konto":"539","naziv_konta":"x","sigurnost":0.9,"obrazlozenje":"ok"}',
                                   usage_metadata=meta)

    original = gemini.GeminiProvider

    def fake_provider(*args, **kwargs):
        return original(*args, client=SimpleNamespace(models=Models()), **kwargs)

    monkeypatch.setattr(gemini, "GeminiProvider", fake_provider)
    app = create_app(replace(settings, gemini_api_key="fake", max_llm_calls=2))
    client = TestClient(app)
    payload = {"client_id": "c", "client_activity": "IT", "items": [{"name": f"Nejasna stavka {i}"} for i in range(4)]}
    items = client.post("/invoices", json=payload).json()["items"]

    assert len(sent) == 2  # the cap stopped the 3rd and 4th request before sending
    assert [i["suggestion"]["konto"] for i in items] == ["539", "539", None, None]
    assert "dostignut limit" in items[2]["suggestion"]["explanation"]
    llm = client.get("/health").json()["llm"]
    assert llm["calls_sent"] == 2 and llm["max_calls"] == 2
    assert llm["usage"] == {"calls": 2, "prompt_tokens": 200, "output_tokens": 20, "thinking_tokens": 10}
    assert llm["cache_hits"] == 0

    # The same request again is answered from the in-memory cache: no new API call.
    client.post("/invoices", json={**payload, "items": payload["items"][:1]})
    llm = client.get("/health").json()["llm"]
    assert len(sent) == 2 and llm["calls_sent"] == 2 and llm["cache_hits"] == 1


def test_max_llm_calls_from_environment(monkeypatch):
    monkeypatch.setenv("KONTOAI_MAX_LLM_CALLS", "20")
    assert config.get_settings().max_llm_calls == 20
    monkeypatch.delenv("KONTOAI_MAX_LLM_CALLS")
    assert config.get_settings().max_llm_calls is None


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_key_is_used_when_not_disabled(monkeypatch, value):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("KONTOAI_DISABLE_LLM", value)
    assert config.get_settings().gemini_api_key == "k"
