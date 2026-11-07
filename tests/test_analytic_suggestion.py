"""Fourth-digit (analytic) suggestion: history -> only option -> LLM -> accountant. Gemini is always mocked."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analytic import AnalyticAccount, AnalyticPlan
from app.classifier import Classifier, ItemContext
from app.history import HistoryStore
from app.llm.base import AnalyticOption, AnalyticRequest, LLMError
from app.llm.gemini import GeminiProvider
from app.main import create_app
from app.models import AnalyticSource, InvoiceItem, Source
from tests.conftest import FakeLLM

CLIENT = "K001"
PLAN = AnalyticPlan({CLIENT: [
    AnalyticAccount(konto="5330", naziv="Zakup poslovnog prostora", probni=True),
    AnalyticAccount(konto="5331", naziv="Zakup magacinskog prostora", probni=True),
    AnalyticAccount(konto="5340", naziv="Zakup sajamskog prostora", probni=True),
    AnalyticAccount(konto="5501", naziv="Pravne usluge", probni=True),
]})


def make(chart, history, rules, llm, plan=PLAN) -> Classifier:
    return Classifier(chart=chart, history=history, rules=rules, llm=llm, review_threshold=0.75, analytic_plan=plan)


def ctx(name, client=CLIENT, supplier_pib=None, given_konto=None, **kw) -> ItemContext:
    return ItemContext(client_id=client, client_activity="proizvodnja dijetetskih proizvoda",
                       item=InvoiceItem(name=name, supplier_pib=supplier_pib, given_konto=given_konto, **kw))


def test_no_plan_for_client_means_no_analytic(chart, history, rules, fake_llm):
    s = make(chart, history, rules, fake_llm).classify(ctx("Zakup poslovnog prostora", client="other"))
    assert s.konto == "533" and s.analytic is None
    assert fake_llm.analytic_requests == []


def test_llm_chooses_only_among_options_below_the_synthetic_account(chart, history, rules):
    llm = FakeLLM(analytic="5331")
    s = make(chart, history, rules, llm).classify(ctx("Zakup magacina za gotove proizvode"))
    assert s.konto == "533" and s.source is Source.RULE
    a = s.analytic
    assert a.konto == "5331" and a.naziv == "Zakup magacinskog prostora"
    assert a.source is AnalyticSource.LLM and a.needs_review is False
    assert [o.konto for o in a.options] == ["5330", "5331"]  # 5340 and 5501 are not offered
    request = llm.analytic_requests[0]
    assert [o.konto for o in request.options] == ["5330", "5331"]
    assert request.konto == "533"


def test_llm_analytic_outside_options_is_rejected(chart, history, rules):
    llm = FakeLLM(analytic="5340")  # in the client's plan, but below 534, so not among the options for 533
    s = make(chart, history, rules, llm).classify(ctx("Zakup poslovnog prostora"))
    assert s.analytic.konto is None
    assert s.analytic.needs_review is True
    assert "odbačen" in s.analytic.explanation
    llm2 = FakeLLM(analytic="9999")
    s2 = make(chart, history, rules, llm2).classify(ctx("Zakup poslovnog prostora"))
    assert s2.analytic.konto is None and "9999" in s2.analytic.explanation


def test_low_confidence_leaves_the_choice_to_the_accountant(chart, history, rules):
    llm = FakeLLM(analytic="5330", analytic_sigurnost=0.5)
    a = make(chart, history, rules, llm).classify(ctx("Zakup")).analytic
    assert a.konto is None  # nothing preselected
    assert a.needs_review is True
    assert "5330" in a.explanation and "knjigovođi" in a.explanation
    assert len(a.options) == 2


def test_llm_error_leaves_choice_to_accountant(chart, history, rules):
    llm = FakeLLM(analytic_error=LLMError("timeout"))
    a = make(chart, history, rules, llm).classify(ctx("Zakup prostora")).analytic
    assert a.konto is None and a.needs_review and "timeout" in a.explanation


def test_single_option_needs_no_llm_call(chart, history, rules):
    llm = FakeLLM()
    s = make(chart, history, rules, llm).classify(ctx("Advokatske usluge", given_konto="550"))
    assert s.source is Source.INPUT and s.konto == "550"
    assert s.analytic.konto == "5501"
    assert s.analytic.source is AnalyticSource.ONLY_OPTION
    assert llm.analytic_requests == [] and llm.requests == []


def test_no_analytic_below_synthetic_is_flagged(chart, history, rules, fake_llm):
    s = make(chart, history, rules, fake_llm).classify(ctx("Evrodizel"))
    assert s.konto == "513"
    assert s.analytic.konto is None and s.analytic.options == [] and s.analytic.needs_review


def test_without_llm_the_accountant_chooses(chart, history, rules):
    a = make(chart, history, rules, None).classify(ctx("Zakup prostora")).analytic
    assert a.konto is None and a.source is AnalyticSource.NONE and len(a.options) == 2


def test_given_synthetic_account_skips_the_synthetic_pipeline(chart, history, rules):
    llm = FakeLLM()
    s = make(chart, history, rules, llm).classify(ctx("Nešto nejasno", given_konto="533"))
    assert s.source is Source.INPUT and s.confidence == 1.0 and not s.needs_review
    assert llm.requests == []  # no synthetic LLM call
    assert len(llm.analytic_requests) == 1


def test_given_account_outside_chart_is_ignored(chart, history, rules):
    s = make(chart, history, rules, FakeLLM()).classify(ctx("Zakup prostora", given_konto="999"))
    assert s.source is Source.RULE and s.konto == "533"


def test_history_item_then_supplier_for_analytic(chart, history: HistoryStore, rules):
    llm = FakeLLM(analytic="5330")
    history.add(client_id=CLIENT, item_name="Zakup magacina", konto="533", analytic_konto="5331",
                supplier_pib="400000001")
    clf = make(chart, history, rules, llm)

    same_item = clf.classify(ctx("Zakup magacina")).analytic
    assert same_item.konto == "5331" and same_item.source is AnalyticSource.HISTORY

    same_supplier = clf.classify(ctx("Zakup - novembar", supplier_pib="400000001")).analytic
    assert same_supplier.konto == "5331" and same_supplier.source is AnalyticSource.HISTORY
    assert "dobavljača" in same_supplier.explanation
    assert llm.analytic_requests == []


def test_analytic_history_is_per_synthetic_account(chart, history: HistoryStore, rules):
    history.add(client_id=CLIENT, item_name="Zakup", konto="534", analytic_konto="5340")
    # Synthetic 533 is given (e.g. by Iris), so the item's 534/5340 confirmation must not be reused.
    a = make(chart, history, rules, FakeLLM(analytic="5330")).classify(ctx("Zakup", given_konto="533")).analytic
    assert a.source is AnalyticSource.LLM
    assert a.konto == "5330"


def test_analytic_request_is_masked(chart, history, rules):
    llm = FakeLLM(analytic="5330")
    item = dict(supplier_name="Poslovni Centar Vračar DOO")
    make(chart, history, rules, llm).classify(ctx("Zakup kancelarije - Poslovni Centar Vračar, PIB 203000033",
                                                   supplier_pib="203000033", **item))
    sent = llm.analytic_requests[0].model_dump_json()
    assert "Vračar" not in sent and "203000033" not in sent
    assert "[DOBAVLJAC_1]" in sent


def test_history_migrates_an_old_database(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""CREATE TABLE confirmations (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL,
        item_key TEXT NOT NULL, item_name TEXT NOT NULL, supplier_key TEXT, supplier_name TEXT, supplier_pib TEXT,
        konto TEXT NOT NULL, konto_name TEXT, suggested_konto TEXT, suggested_source TEXT,
        corrected INTEGER NOT NULL DEFAULT 0, confirmed_at TEXT NOT NULL);
        INSERT INTO confirmations (client_id, item_key, item_name, konto, confirmed_at)
        VALUES ('c', 'x', 'X', '533', '2026-01-01T00:00:00+00:00');""")
    conn.commit()
    conn.close()
    store = HistoryStore(db)
    assert store.list("c")[0].analytic_konto is None
    store.add(client_id="c", item_name="Y", konto="533", analytic_konto="5330")
    assert store.list("c")[0].analytic_konto == "5330"


# ------------------------------------------------------------------ Gemini provider (fake SDK client)


def test_gemini_analytic_schema_lists_only_offered_accounts():
    calls = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text='{"konto":"5331","sigurnost":0.9,"obrazlozenje":"Magacin."}')

    provider = GeminiProvider(api_key="x", model="m", client=SimpleNamespace(models=Models()))
    request = AnalyticRequest(item_text="Zakup magacina", client_activity="proizvodnja", konto="533",
                              konto_naziv="Troškovi zakupnina",
                              options=[AnalyticOption(konto="5330", naziv="Poslovni prostor"),
                                       AnalyticOption(konto="5331", naziv="Magacin")])
    choice = provider.choose_analytic(request)
    assert choice.konto == "5331"
    schema = calls[0]["config"].response_json_schema
    assert schema["properties"]["konto"]["enum"] == ["5330", "5331"]
    assert "5331 Magacin" in calls[0]["contents"] and "533 Troškovi zakupnina" in calls[0]["contents"]


# ------------------------------------------------------------------ API


@pytest.fixture
def plan_client(settings, tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"status": "probni", "clients": {CLIENT: {"konta": [
        {"konto": "5330", "naziv": "Zakup poslovnog prostora", "probni": True},
        {"konto": "5331", "naziv": "Zakup magacinskog prostora", "probni": True},
    ]}}}), encoding="utf-8")
    from dataclasses import replace

    llm = FakeLLM(analytic="5330")
    app = create_app(replace(settings, analytic_plan_path=plan_path), llm=llm)
    return TestClient(app), llm


def test_api_analytic_plan_endpoint(plan_client):
    client, _ = plan_client
    body = client.get(f"/analytic-plan/{CLIENT}").json()
    assert body["status"] == "probni"
    assert [a["konto"] for a in body["accounts"]] == ["5330", "5331"]
    assert body["accounts"][0]["sintetika"] == "533"
    assert client.get("/analytic-plan/nobody").json()["accounts"] == []
    assert client.get("/health").json()["analytic_plan_status"] == "probni"


def test_api_confirm_analytic_and_learn(plan_client):
    client, llm = plan_client
    payload = {"client_id": CLIENT, "client_activity": "proizvodnja dijetetskih proizvoda",
               "items": [{"name": "Zakup prostora za skladištenje", "supplier_pib": "400000009"}]}
    first = client.post("/invoices", json=payload).json()["items"][0]["suggestion"]
    assert first["analytic"]["konto"] == "5330" and first["analytic"]["source"] == "llm"

    response = client.post("/confirm", json={
        "client_id": CLIENT, "item_name": "Zakup prostora za skladištenje", "konto": "533",
        "supplier_pib": "400000009", "suggested_konto": "533", "suggested_source": "rule",
        "analytic_konto": "5331", "suggested_analytic": "5330", "suggested_analytic_source": "llm",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "corrected"
    assert body["record"]["analytic_konto"] == "5331"
    assert body["record"]["analytic_name"] == "Zakup magacinskog prostora"
    assert body["record"]["analytic_corrected"] is True

    calls = len(llm.analytic_requests)
    second = client.post("/invoices", json=payload).json()["items"][0]["suggestion"]["analytic"]
    assert second["konto"] == "5331" and second["source"] == "history"
    assert len(llm.analytic_requests) == calls  # learned: no LLM call

    other_item = {**payload, "items": [{"name": "Zakup - decembar", "supplier_pib": "400000009"}]}
    third = client.post("/invoices", json=other_item).json()["items"][0]["suggestion"]["analytic"]
    assert third["konto"] == "5331" and third["source"] == "history"  # same supplier


def test_api_confirm_rejects_analytic_not_in_plan_or_wrong_synthetic(plan_client):
    client, _ = plan_client
    base = {"client_id": CLIENT, "item_name": "X", "konto": "533"}
    assert client.post("/confirm", json={**base, "analytic_konto": "5340"}).status_code == 422
    assert client.post("/confirm", json={**base, "konto": "531", "analytic_konto": "5330"}).status_code == 422
    assert client.post("/confirm", json={**base, "client_id": "nobody", "analytic_konto": "5330"}).status_code == 422
    assert client.post("/confirm", json=base).status_code == 200  # analytic stays optional


def test_api_given_konto(plan_client):
    client, llm = plan_client
    body = client.post("/invoices", json={
        "client_id": CLIENT, "client_activity": "proizvodnja",
        "items": [{"name": "Neki opis", "given_konto": "533"}],
    }).json()
    s = body["items"][0]["suggestion"]
    assert s["source"] == "input" and s["konto"] == "533"
    assert s["analytic"]["konto"] == "5330"
    assert llm.requests == []
