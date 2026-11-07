"""Shared fixtures. No test touches the network, a real API key or the real database."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chart import ChartOfAccounts
from app.classifier import Classifier
from app.config import DATA_DIR, Settings
from app.history import HistoryStore
from app.llm.base import AnalyticChoice, AnalyticRequest, LLMError, LLMProvider, LLMRequest, LLMSuggestion
from app.main import create_app
from app.rules import RuleEngine

SAMPLES = DATA_DIR / "samples"


class FakeLLM(LLMProvider):
    """Records every request and returns a canned answer (or raises)."""

    name = "fake"
    model = "fake-model"

    def __init__(self, konto: str = "539", sigurnost: float = 0.8, obrazlozenje: str = "Test obrazloženje.",
                 error: Exception | None = None, analytic: str | None = None, analytic_sigurnost: float = 0.9,
                 analytic_error: Exception | None = None):
        self.konto, self.sigurnost, self.obrazlozenje, self.error = konto, sigurnost, obrazlozenje, error
        self.analytic, self.analytic_sigurnost, self.analytic_error = analytic, analytic_sigurnost, analytic_error
        self.requests: list[LLMRequest] = []
        self.analytic_requests: list[AnalyticRequest] = []

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        self.requests.append(request)
        if self.error:
            raise self.error
        return LLMSuggestion(konto=self.konto, naziv_konta="x", sigurnost=self.sigurnost,
                             obrazlozenje=self.obrazlozenje)

    def choose_analytic(self, request: AnalyticRequest) -> AnalyticChoice:
        self.analytic_requests.append(request)
        if self.analytic_error:
            raise self.analytic_error
        chosen = self.analytic or request.options[0].konto
        return AnalyticChoice(konto=chosen, sigurnost=self.analytic_sigurnost, obrazlozenje="Analitika test.")


@pytest.fixture(autouse=True)
def _no_real_gemini(monkeypatch):
    """Make sure nothing builds a real Gemini client by accident."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def _boom(*args, **kwargs):
        raise AssertionError("Tests must not create a real Gemini client")

    monkeypatch.setattr("google.genai.Client", _boom)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        gemini_api_key=None,
        gemini_model="fake-model",
        review_threshold=0.75,
        db_path=tmp_path / "test.db",
        chart_path=DATA_DIR / "kontni_okvir.json",
        rules_path=DATA_DIR / "rules.json",
    )


@pytest.fixture
def chart() -> ChartOfAccounts:
    return ChartOfAccounts.load(DATA_DIR / "kontni_okvir.json")


@pytest.fixture
def rules() -> RuleEngine:
    return RuleEngine.load(DATA_DIR / "rules.json")


@pytest.fixture
def history(tmp_path: Path) -> HistoryStore:
    return HistoryStore(tmp_path / "history.db")


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def classifier(chart, history, rules, fake_llm) -> Classifier:
    return Classifier(chart=chart, history=history, rules=rules, llm=fake_llm, review_threshold=0.75)


@pytest.fixture
def client(settings, fake_llm) -> TestClient:
    return TestClient(create_app(settings, llm=fake_llm))


@pytest.fixture
def sample_bytes():
    def _read(name: str) -> bytes:
        return (SAMPLES / name).read_bytes()

    return _read


__all__ = ["FakeLLM", "LLMError"]
