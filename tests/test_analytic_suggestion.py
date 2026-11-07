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
from app.models import AnalyticSource, GivenCheck, InvoiceItem, Source
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
    # "Knjigovodstvene usluge" is decided by a rule (550), and the plan has only 5501 below 550.
    s = make(chart, history, rules, llm).classify(ctx("Knjigovodstvene usluge"))
    assert s.source is Source.RULE and s.konto == "550"
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


def test_given_account_matching_the_system(chart, history, rules):
    llm = FakeLLM()
    s = make(chart, history, rules, llm).classify(ctx("Zakup poslovnog prostora", given_konto="533"))
    assert s.source is Source.RULE and s.konto == "533"  # the system's own suggestion is kept
    assert s.given_konto == "533" and s.given_konto_name == "Troškovi zakupnina"
    assert s.given_check is GivenCheck.MATCH
    assert s.needs_review is False


def test_given_account_match_clears_review_of_an_unsure_system(chart, history, rules):
    llm = FakeLLM(konto="539", sigurnost=0.5)  # the system alone would flag this
    s = make(chart, history, rules, llm).classify(ctx("Nešto nejasno", given_konto="539"))
    assert s.source is Source.LLM and s.given_check is GivenCheck.MATCH and s.needs_review is False


def test_given_account_mismatch_goes_to_review(chart, history, rules):
    llm = FakeLLM()
    s = make(chart, history, rules, llm).classify(ctx("Zakup parking mesta", given_konto="539"))
    assert s.konto == "533" and s.source is Source.RULE
    assert s.given_check is GivenCheck.MISMATCH
    assert s.needs_review is True
    # Iris is authoritative for the analytic level: options are below 539, not below 533.
    assert s.analytic is not None
    assert all(o.konto.startswith("539") for o in s.analytic.options)


def test_given_account_still_runs_the_synthetic_pipeline_with_llm(chart, history, rules):
    llm = FakeLLM(konto="539")
    s = make(chart, history, rules, llm).classify(ctx("Nešto nejasno", given_konto="533"))
    assert len(llm.requests) == 1  # the synthetic step is NOT skipped
    assert s.konto == "539" and s.given_check is GivenCheck.MISMATCH
    assert len(llm.analytic_requests) == 1
    assert {o.konto for o in llm.analytic_requests[0].options} == {"5330", "5331"}  # below Iris' 533


def test_given_account_unverified_without_own_suggestion(chart, history, rules):
    s = make(chart, history, rules, None).classify(ctx("Nešto nejasno", given_konto="533"))
    assert s.konto is None and s.given_check is GivenCheck.UNVERIFIED and s.needs_review
    assert "nije proveren" in s.explanation
    assert [o.konto for o in s.analytic.options] == ["5330", "5331"]


def test_given_account_outside_chart(chart, history, rules):
    s = make(chart, history, rules, FakeLLM()).classify(ctx("Zakup prostora", given_konto="999"))
    assert s.konto == "533"
    assert s.given_check is GivenCheck.NOT_IN_CHART and s.needs_review
    assert s.given_konto_name is None


def test_no_given_account_means_no_check(chart, history, rules):
    s = make(chart, history, rules, FakeLLM()).classify(ctx("Zakup prostora"))
    assert s.given_konto is None and s.given_check is None


def test_history_item_then_supplier_for_analytic(chart, history: HistoryStore, rules):
    llm = FakeLLM(analytic="5330")
    history.add(client_id=CLIENT, item_name="Zakup magacina", konto="533", analytic_konto="5331",
                supplier_pib="400000001")
    clf = make(chart, history, rules, llm)

    same_item = clf.classify(ctx("Zakup magacina", supplier_pib="400000001")).analytic
    assert same_item.konto == "5331" and same_item.source is AnalyticSource.HISTORY

    # One confirmation is not enough for a different item of the same supplier ...
    one = clf.classify(ctx("Zakup - novembar", supplier_pib="400000001")).analytic
    assert one.source is AnalyticSource.LLM and one.konto == "5330"

    # ... two consistent confirmations are.
    history.add(client_id=CLIENT, item_name="Zakup hladnjače", konto="533", analytic_konto="5331",
                supplier_pib="400000001")
    two = clf.classify(ctx("Zakup - novembar", supplier_pib="400000001")).analytic
    assert two.konto == "5331" and two.source is AnalyticSource.HISTORY
    assert "Sve potvrđene stavke ovog dobavljača (2)" in two.explanation


def test_supplier_analytic_never_below_a_different_synthetic_account(chart, history: HistoryStore, rules):
    for name in ("Zakup magacina", "Zakup hladnjače"):
        history.add(client_id=CLIENT, item_name=name, konto="533", analytic_konto="5331", supplier_pib="400000001")
    # Iris says 534: the supplier's consistent 5331 (below 533) must not be suggested.
    s = make(chart, history, rules, FakeLLM()).classify(
        ctx("Prostor za izlaganje", supplier_pib="400000001", given_konto="534"))
    assert s.konto == "533" and s.given_check is GivenCheck.MISMATCH  # supplier history at 3-digit level
    a = s.analytic
    assert a.konto == "5340" and a.source is AnalyticSource.ONLY_OPTION
    assert [o.konto for o in a.options] == ["5340"]


def test_rules_beat_supplier_history_but_not_item_history(chart, history: HistoryStore, rules):
    for name in ("Zakup magacina", "Zakup hladnjače"):
        history.add(client_id=CLIENT, item_name=name, konto="533", supplier_pib="400000001")
    clf = make(chart, history, rules, FakeLLM())
    # Electricity from the same landlord: the energy rule wins over the (consistent) supplier history.
    s = clf.classify(ctx("Električna energija - refakturisanje", supplier_pib="400000001"))
    assert s.konto == "513" and s.source is Source.RULE
    # An item without a rule falls back to the consistent supplier history.
    s2 = clf.classify(ctx("Čišćenje prostorija", supplier_pib="400000001"))
    assert s2.konto == "533" and s2.source is Source.HISTORY
    # Item history beats the rule: the accountant booked this exact item to 539 before.
    history.add(client_id=CLIENT, item_name="Električna energija - refakturisanje", konto="539",
                supplier_pib="400000001")
    s3 = clf.classify(ctx("Električna energija - refakturisanje", supplier_pib="400000001"))
    assert s3.konto == "539" and s3.source is Source.HISTORY


def test_demo_replay_sample_06_learning_without_spreading(settings, sample_bytes):
    """Exactly the demo of 2026-11-07: upload 06 for K001, confirm 5331 on row 2, upload again.

    Before the fix, the single confirmation spread to the landlord's other lines: row 1 got 5331
    and row 3 (electricity) got 533 instead of Iris' 513.
    """
    from dataclasses import replace

    from app.config import DATA_DIR

    llm = FakeLLM(konto="539")  # analytic: first offered option
    app = create_app(replace(settings, analytic_plan_path=DATA_DIR / "analiticki_plan.json"), llm=llm)
    client = TestClient(app)

    def upload():
        response = client.post(
            "/invoices/xml",
            files={"file": ("06.xml", sample_bytes("06_iris_provera_dijetetika.xml"), "application/xml")},
            data={"client_activity": "proizvodnja dijetetskih proizvoda", "client_id": CLIENT},
        )
        assert response.status_code == 200, response.text
        return [r for r in response.json()["items"]]

    first = upload()
    row2 = first[1]
    confirm = client.post("/confirm", json={
        "client_id": CLIENT, "item_name": row2["item"]["name"], "konto": "533",
        "supplier_name": row2["item"]["supplier_name"], "supplier_pib": row2["item"]["supplier_pib"],
        "analytic_konto": "5331", "suggested_konto": "533", "suggested_source": "input",
        "suggested_analytic": row2["suggestion"]["analytic"]["konto"],
        "suggested_analytic_source": row2["suggestion"]["analytic"]["source"],
    })
    assert confirm.status_code == 200, confirm.text

    second = upload()
    r1, r2, r3, r4, r5 = (r["suggestion"] for r in second)

    # Row 2 learned from item history.
    assert r2["analytic"]["konto"] == "5331" and r2["analytic"]["source"] == "history"
    assert r2["konto"] == "533" and r2["source"] == "history"
    # Row 1 (office rent) did NOT take over the warehouse analytic.
    assert r1["analytic"]["konto"] in ("5330", None) and r1["analytic"]["source"] != "history"
    assert r1["source"] == "rule" and r1["given_check"] == "match"
    # Row 3 (electricity) stays under Iris' 513 and matches it.
    assert r3["konto"] == "513" and r3["source"] == "rule" and r3["given_check"] == "match"
    assert r3["analytic"]["konto"] == "5133"
    # Rows 4 and 5 are not taken over by supplier history either.
    assert r4["source"] != "history" and r5["source"] == "rule"
    assert all(o["konto"].startswith("539") for o in r5["analytic"]["options"])


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

    # A different item of the same supplier: one confirmation is not enough for supplier history.
    other_item = {**payload, "items": [{"name": "Zakup - decembar", "supplier_pib": "400000009"}]}
    third = client.post("/invoices", json=other_item).json()["items"][0]["suggestion"]["analytic"]
    assert third["source"] == "llm"


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
        "items": [{"name": "Zakup prostora", "given_konto": "533"},
                  {"name": "Neki opis", "given_konto": "533"}],
    }).json()
    match, mismatch = (r["suggestion"] for r in body["items"])
    assert match["konto"] == "533" and match["given_konto"] == "533" and match["given_check"] == "match"
    assert match["analytic"]["konto"] == "5330"
    assert mismatch["konto"] == "539" and mismatch["given_check"] == "mismatch"  # FakeLLM default 539
    assert mismatch["needs_review"] is True
    assert body["needs_review_count"] >= 1
    assert len(llm.requests) == 1  # the system computed its own suggestion for the unknown item


def test_api_xml_accounting_cost_is_the_given_konto(settings, sample_bytes):
    from dataclasses import replace

    from app.config import DATA_DIR

    app = create_app(replace(settings, analytic_plan_path=DATA_DIR / "analiticki_plan.json"), use_llm=False)
    body = TestClient(app).post(
        "/invoices/xml",
        files={"file": ("f.xml", sample_bytes("06_iris_provera_dijetetika.xml"), "application/xml")},
        data={"client_activity": "proizvodnja dijetetskih proizvoda", "client_id": CLIENT},
    ).json()
    checks = [(r["item"]["given_konto"], r["suggestion"]["konto"], r["suggestion"]["given_check"])
              for r in body["items"]]
    assert checks == [("533", "533", "match"), ("533", "533", "match"), ("513", "513", "match"),
                      ("539", None, "unverified"), ("539", "533", "mismatch")]
    parking = body["items"][4]["suggestion"]
    assert all(o["konto"].startswith("539") for o in parking["analytic"]["options"])
