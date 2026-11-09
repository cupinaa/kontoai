"""scripts/evaluate_real_plan.py with invented data: the guard, the privacy refusals and the dry run."""

from __future__ import annotations

import json

import pytest

from app.llm.base import LLMRequest
from app.models import Account
from scripts.evaluate_real_plan import ROOT, ForbiddenContent, Guard, main

PLAN = {"status": "uvezen", "clients": {"K9": {"konta": [
    {"konto": "5130", "naziv": "Troškovi električne energije", "tg": 5, "pg": 5},
    {"konto": "5139", "naziv": "Drugi troškovi energije", "tg": 0, "pg": 0},
    {"konto": "5121", "naziv": "Kancelarijski materijal", "tg": 3, "pg": 3},
    {"konto": "5129", "naziv": "Ostali režijski materijal", "tg": 9, "pg": 9},
]}}}
DATASET = {"client_id": "K9", "items": [
    {"id": "k1", "name": "Električna energija za oktobar", "client_activity": "proizvodnja",
     "expected_konto": "513", "expected_analytic": "5130", "izvor": "izvedeno_iz_plana"},
    {"id": "s1", "name": "Papir A4 za Lipovac Komerc", "client_activity": "proizvodnja",
     "expected_konto": "512", "expected_analytic": "5121", "izvor": "knjigovodja",
     "supplier_name": "Lipovac Komerc DOO", "supplier_pib": "100000009"},
]}


@pytest.fixture
def private(tmp_path, monkeypatch):
    (tmp_path / "plan.json").write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data.json").write_text(json.dumps(DATASET, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("KONTOAI_ANALYTIC_PLAN_PATH", str(tmp_path / "plan.json"))
    monkeypatch.setenv("KONTOAI_DISABLE_LLM", "1")
    return tmp_path


def test_guard_stops_a_request_with_a_forbidden_string():
    guard = Guard(None, ["Zlatni Breg DOO"])
    request = LLMRequest(item_text="Usluga za Zlatni Breg DOO", client_activity="x",
                         accounts=[Account(konto="539", naziv="Ostale usluge", klasa="5")])
    with pytest.raises(ForbiddenContent):
        guard.suggest(request)
    assert guard.blocked == 1 and guard.prompts == []


def test_dataset_inside_the_repository_is_refused():
    assert main(["--dataset", str(ROOT / "data" / "eval" / "dataset.json"), "--dry-run"]) == 2


def test_public_plan_is_refused(private, monkeypatch):
    monkeypatch.setenv("KONTOAI_ANALYTIC_PLAN_PATH", str(ROOT / "data" / "analiticki_plan.json"))
    assert main(["--dataset", str(private / "data.json"), "--dry-run"]) == 2


def test_dry_run_masks_suppliers_and_sends_nothing(private, capsys):
    (private / "forbidden.txt").write_text("Zlatni Breg\n", encoding="utf-8")
    code = main(["--dataset", str(private / "data.json"), "--forbidden", str(private / "forbidden.txt"),
                 "--dry-run", "--no-cache"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "DRY RUN" in out and "zaustavljenih zbog zabranjenog podatka: 0" in out
