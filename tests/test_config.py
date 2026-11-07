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


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_key_is_used_when_not_disabled(monkeypatch, value):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("KONTOAI_DISABLE_LLM", value)
    assert config.get_settings().gemini_api_key == "k"
