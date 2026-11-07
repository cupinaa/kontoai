"""scripts/evaluate.py with a fake Gemini client: the --max-calls guard and --dry-run. No network."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import DATA_DIR

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "evaluate.py"
ANSWER = '{"konto":"539","naziv_konta":"x","sigurnost":0.9,"obrazlozenje":"ok"}'


@pytest.fixture
def evaluate(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("evaluate_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "evaluate_script", module)  # dataclasses need the module registered
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    return module


@pytest.fixture
def fake_gemini(evaluate, monkeypatch):
    """Replace the real SDK client inside GeminiProvider with a counter."""
    calls = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=ANSWER, usage_metadata=None)

    original = evaluate.GeminiProvider

    def make(*args, **kwargs):
        return original(*args, client=SimpleNamespace(models=Models()), **kwargs)

    monkeypatch.setattr(evaluate, "GeminiProvider", make)
    return calls


def llm_items() -> int:
    data = json.loads((DATA_DIR / "eval" / "dataset.json").read_text(encoding="utf-8"))
    return sum(1 for i in data["items"] if i["expected_source"] == "llm")


def test_max_calls_stops_sending_and_flags_the_rest(evaluate, fake_gemini, capsys):
    rows, info = evaluate.run(DATA_DIR / "eval" / "dataset.json", use_llm=True, rpm=None,
                              use_cache=False, max_calls=3)

    assert len(fake_gemini) == 3
    assert info.budget.used == 3
    skipped = evaluate.budget_skipped(rows)
    assert len(skipped) == llm_items() - 3
    assert all(r.needs_review and r.predicted is None for r in skipped)
    assert "Reached --max-calls 3" in capsys.readouterr().err

    report = evaluate.render(rows, info, 0.75)
    assert "Stopped at the call limit" in report
    assert "| API requests sent (incl. retries) | 3 of max 3 |" in report


def test_default_limit_is_40(evaluate):
    assert evaluate.DEFAULT_MAX_CALLS == 40


def test_agreement_with_given_konto(evaluate, tmp_path, capsys):
    dataset = tmp_path / "iris.json"
    dataset.write_text(json.dumps({
        "clients": {"c": "Razvoj softvera"}, "history_seed": [],
        "items": [
            {"id": 1, "client_id": "c", "name": "Zakup poslovnog prostora", "given_konto": "533", "expected_konto": "533"},
            {"id": 2, "client_id": "c", "name": "Evrodizel", "given_konto": "513", "expected_konto": "513"},
            {"id": 3, "client_id": "c", "name": "Zakup parking mesta", "given_konto": "539", "expected_konto": "533"},
            {"id": 4, "client_id": "c", "name": "Nešto nejasno", "given_konto": "539", "expected_konto": "539"},
            {"id": 5, "client_id": "c", "name": "Toner HP 85A", "expected_konto": "512"},
        ],
    }), encoding="utf-8")
    rows, info = evaluate.run(dataset, use_llm=False, rpm=None, use_cache=False)
    agreement = evaluate.given_agreement(rows)
    assert agreement["total"] == 4
    assert agreement["counts"] == {"match": 2, "mismatch": 1, "unverified": 1, "not_in_chart": 0}
    assert agreement["match_pct"] == "50.0%"
    report = evaluate.render(rows, info, 0.75)
    assert "## Agreement with the given account (Iris)" in report
    assert "matches it on **50.0%** (2/4)" in report


def test_no_agreement_section_without_given_konto(evaluate):
    rows, info = evaluate.run(DATA_DIR / "eval" / "dataset.json", use_llm=False, rpm=None, use_cache=False)
    assert evaluate.given_agreement(rows) is None
    assert "Agreement with the given account" not in evaluate.render(rows, info, 0.75)


def test_estimated_cost(evaluate):
    usage = {"prompt_tokens": 42_202, "output_tokens": 2_741, "thinking_tokens": 21_558}
    assert round(evaluate.estimated_cost("gemini-3.6-flash", usage), 3) == 0.123
    assert evaluate.estimated_cost("unknown-model", usage) is None


def test_cache_prevents_repeat_calls(evaluate, fake_gemini):
    dataset = DATA_DIR / "eval" / "dataset.json"
    evaluate.run(dataset, use_llm=True, rpm=None, use_cache=True, max_calls=100)
    first = len(fake_gemini)
    _, info = evaluate.run(dataset, use_llm=True, rpm=None, use_cache=True, max_calls=100)
    assert len(fake_gemini) == first  # second run served entirely from cache
    assert info.cache_hits == first


def test_dry_run_sends_nothing(evaluate, fake_gemini):
    rows, info = evaluate.run(DATA_DIR / "eval" / "dataset.json", use_llm=True, rpm=None,
                              use_cache=True, dry_run=True)
    assert fake_gemini == []
    assert len(info.dry_run.requests) == llm_items()
    assert info.dry_run.estimated_prompt_tokens() > 0
