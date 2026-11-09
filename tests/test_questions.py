"""The accountant's questions about one line (POST /ask). The LLM is always mocked."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.llm.base import CallBudget, CallBudgetExceeded, QuestionAnswer, QuestionRequest, build_question_prompt
from app.llm.gemini import GeminiProvider, question_schema
from app.main import create_app
from tests.conftest import FakeLLM

PLAN = {
    "status": "uvezen",
    "clients": {"K1": {"delatnost": "proizvodnja", "konta": [
        {"konto": "5130", "naziv": "Troškovi električne energije", "tg": 12, "pg": 11},
        {"konto": "5133", "naziv": "Troškovi goriva za vozila", "tg": 30, "pg": 31},
        {"konto": "5139", "naziv": "Drugi troškovi goriva i energije", "tg": 0, "pg": 0},
        {"konto": "53301", "naziv": "Zakup skladista-ostalo", "tg": 6, "pg": 7},
    ]}},
}

QUESTION = {
    "client_id": "K1", "client_activity": "proizvodnja dijetetskih proizvoda",
    "item_name": "Električna energija za oktobar", "supplier_name": "Elektro Primer DOO",
    "supplier_pib": "100000001", "konto": "513", "analytic_konto": "5133",
    "question": "Da li je ovo gorivo ili struja kod Elektro Primer DOO?",
}


def make_client(settings, tmp_path, llm):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
    return TestClient(create_app(replace(settings, analytic_plan_path=path), llm=llm))


def test_answer_with_a_recommendation_from_the_plan(settings, tmp_path):
    llm = FakeLLM(question_answer=QuestionAnswer(odgovor="Ovo je struja, ne gorivo.", preporuceni_konto="5130"))
    res = make_client(settings, tmp_path, llm).post("/ask", json=QUESTION)
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "Ovo je struja, ne gorivo."
    assert body["recommended_konto"] == "5130"
    assert body["recommended_naziv"] == "Troškovi električne energije"


def test_model_sees_only_masked_text_and_plan_candidates(settings, tmp_path):
    llm = FakeLLM()
    make_client(settings, tmp_path, llm).post("/ask", json=QUESTION)
    sent = llm.question_requests[0]
    prompt = build_question_prompt(sent)
    assert "Elektro Primer" not in prompt and "100000001" not in prompt
    assert "[DOBAVLJAC_1]" in sent.question
    assert [o.konto for o in sent.options] == ["5133", "5130", "5139"]  # below 513, most used first
    assert "često (61 knjiženja)" in prompt and "nije korišćen" in prompt
    assert sent.analytic_konto == "5133" and sent.analytic_naziv == "Troškovi goriva za vozila"


def test_recommendation_outside_the_plan_is_rejected(settings, tmp_path):
    llm = FakeLLM(question_answer=QuestionAnswer(odgovor="Probajte 5135.", preporuceni_konto="5135"))
    body = make_client(settings, tmp_path, llm).post("/ask", json=QUESTION).json()
    assert body["recommended_konto"] is None
    assert body["rejected_konto"] == "5135"
    assert "nije u planu klijenta" in body["answer"]


def test_off_topic_question_gets_no_recommendation(settings, tmp_path):
    llm = FakeLLM(question_answer=QuestionAnswer(
        odgovor="Odgovaram samo na pitanja o kontiranju ove stavke.", preporuceni_konto="5130", na_temu=False))
    res = make_client(settings, tmp_path, llm).post("/ask", json={**QUESTION, "question": "Kakvo je vreme sutra?"})
    body = res.json()
    assert body["on_topic"] is False
    assert body["recommended_konto"] is None
    assert "samo na pitanja o kontiranju" in body["answer"]


def test_call_limit_reached_returns_429(settings, tmp_path):
    llm = FakeLLM(question_error=CallBudgetExceeded("dostignut limit od 3 API poziva, zahtev nije poslat"))
    res = make_client(settings, tmp_path, llm).post("/ask", json=QUESTION)
    assert res.status_code == 429
    assert "limit" in res.json()["detail"]


def test_without_llm_the_question_is_refused(settings, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    client = TestClient(create_app(replace(settings, analytic_plan_path=path), use_llm=False))
    res = client.post("/ask", json=QUESTION)
    assert res.status_code == 503
    assert "LLM nije uključen" in res.json()["detail"]


@pytest.mark.parametrize("question", ["", "a" * 501])
def test_question_length_is_validated(settings, tmp_path, question):
    res = make_client(settings, tmp_path, FakeLLM()).post("/ask", json={**QUESTION, "question": question})
    assert res.status_code == 422


def test_every_question_is_one_real_call_counted_against_the_budget():
    class Models:
        calls = 0

        def generate_content(self, **kwargs):
            Models.calls += 1
            return SimpleNamespace(text='{"odgovor":"Struja.","preporuceni_konto":"","na_temu":true}')

    budget = CallBudget(2)
    provider = GeminiProvider(api_key="unused", model="m", client=SimpleNamespace(models=Models()), budget=budget)
    request = QuestionRequest(question="Da li je struja?", item_text="Struja", client_activity="x")
    provider.answer_question(request)
    provider.answer_question(request)
    with pytest.raises(CallBudgetExceeded):
        provider.answer_question(request)
    assert Models.calls == 2 and budget.used == 2


def test_cache_does_not_answer_questions_from_memory():
    from app.llm.cache import MemoryCachedProvider

    inner = FakeLLM()
    cached = MemoryCachedProvider(inner)
    request = QuestionRequest(question="Isto pitanje?", item_text="Struja", client_activity="x")
    cached.answer_question(request)
    cached.answer_question(request)
    assert len(inner.question_requests) == 2


def test_question_schema_allows_only_candidates_or_nothing():
    schema = question_schema(["5130", "5133"])
    assert schema["properties"]["preporuceni_konto"]["enum"] == ["", "5130", "5133"]


def test_panel_has_the_question_field():
    from app.main import STATIC_DIR

    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "Pitaj o ovoj stavci" in js and re.search(r'api\("/ask"', js)


def test_check_script_dry_run_sends_nothing(capsys, monkeypatch):
    from scripts.check_questions import QUESTIONS, main

    from app.config import DATA_DIR

    monkeypatch.setenv("KONTOAI_DISABLE_LLM", "1")
    monkeypatch.setenv("KONTOAI_ANALYTIC_PLAN_PATH", str(DATA_DIR / "analiticki_plan.json"))  # never the real plan
    assert main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("Šalje se:") == len(QUESTIONS)
    assert "Poslovni Park Morava" not in out.split("Šalje se:", 1)[1]


def test_question_prompt_hides_place_names_and_the_answer_restores_them(settings, tmp_path):
    plan = {"clients": {"K1": {"konta": [
        {"konto": "5331", "naziv": "Zakup lokala Topolska", "tg": 4, "pg": 4},
        {"konto": "5334", "naziv": "Troškovi zakupa poslovnog prostora", "tg": 9, "pg": 9},
        {"konto": "5339", "naziv": "Drugi troškovi zakupa", "tg": 0, "pg": 0},
    ]}}}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    llm = FakeLLM(question_answer=QuestionAnswer(odgovor="Ide na lokal [LOKACIJA_1].", preporuceni_konto="5331"))
    client = TestClient(create_app(replace(settings, analytic_plan_path=path), llm=llm))
    body = client.post("/ask", json={**QUESTION, "konto": "533", "analytic_konto": "5331",
                                     "item_name": "Zakup lokala", "question": "Koji lokal je ovo?"}).json()
    prompt = build_question_prompt(llm.question_requests[0])
    assert "Topolska" not in prompt and "[LOKACIJA_1]" in prompt
    assert body["answer"] == "Ide na lokal Topolska."
    assert body["recommended_naziv"] == "Zakup lokala Topolska"
