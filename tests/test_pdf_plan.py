"""Importing an analytic plan from the "Konta: Lista" PDF table, 5-digit analytics and usage ranking.

All rows here are invented; the real client's PDF never enters the repository.
"""

from __future__ import annotations

import pytest

from app.analytic import AnalyticAccount, AnalyticPlan, mask_plan_name
from app.analytic_pdf import build_plan, clean_name, collect_rows
from app.classifier import Classifier, ItemContext, best_by_overlap
from app.models import AnalyticSource, InvoiceItem
from tests.conftest import FakeLLM

HEADER = ["Konto", "Naziv", "Analiti\nka\n(partn\ner)", "Aktuel\nan", "Vazi\nod\n2014", "AOP\n2021",
          "Broj\nstavki\nTG", "Broj\nstavki\nPG"]


def row(konto, naziv, aktuelan="Da", tg="0", pg="0"):
    return [konto, naziv, "Ne", aktuelan, "Da", "0005", tg, pg, "", ""]


PAGES = [
    [
        HEADER,
        row("513", "2014 - Troškovi goriva i energije"),
        row("5130", "2014 - Troškovi električne energije", tg="12", pg="11"),
        row("5133", "2014 - Troškovi goriva za vozila", tg="30", pg="31"),
        row("5139", "2014 - Drugi troškovi goriva i energije"),
        row("53190", "2022 - Drugi troskovi transportnih usluga-PTT markice", tg="6", pg="7"),
        row("5131", "2014 - Drugi troškovi pogonskog goriva (ugalj, nafta i njeni derivati,\ngas, itd)"),
        row("5132", "2014 - Stari konto grejanja", aktuelan="Ne", tg="3"),
        row("2410", "2014 - Tekući račun kod banke", tg="400"),  # bank: never imported
        row("5590", "2014 - Sudski troškovi i troškovi veštačenja"),
    ],
    [
        HEADER,
        ["", "i troškovi taksi", "", "", "", "", "", ""],  # continuation of 5590's name on the next page
        row("5591", "2014 - Takse - Primer DOO"),
        row("55505", "2014 - Porez na imovinu 700000001-11", tg="2", pg="2"),
    ],
]


@pytest.fixture
def imported():
    return build_plan(collect_rows(PAGES), source="test.pdf")


def test_clean_name_strips_year_prefix_and_joins_lines():
    assert clean_name("2014 - Troškovi\nelektrične energije") == "Troškovi električne energije"
    assert clean_name("2022 -Ispravka vrednosti") == "Ispravka vrednosti"


def test_only_current_accounts_of_relevant_classes_are_imported(imported):
    codes = [a.konto for a in imported.accounts]
    assert "2410" not in codes  # banks are never imported
    assert "5132" not in codes  # Aktuelan = Ne
    assert "513" not in codes and imported.parents["513"] == "Troškovi goriva i energije"
    assert {"5130", "5133", "53190", "55505"} <= set(codes)
    assert imported.skipped["Aktuelan = Ne"] == 1


def test_wrapped_names_are_joined_with_their_own_account(imported):
    by_code = {a.konto: a for a in imported.accounts}
    assert by_code["5131"].naziv == "Drugi troškovi pogonskog goriva (ugalj, nafta i njeni derivati, gas, itd)"
    assert by_code["5590"].naziv == "Sudski troškovi i troškovi veštačenja i troškovi taksi"
    reasons = {(k, r) for k, _, r in imported.flagged}
    assert ("5131", "naziv prelomljen u više redova") in reasons
    assert any(k == "5590" and "nastavljen" in r for k, r in reasons)
    assert ("5591", "naziv možda sadrži ime firme ili osobe") in reasons


def test_usage_comes_from_tg_plus_pg(imported):
    by_code = {a.konto: a for a in imported.accounts}
    assert by_code["5133"].usage == 61
    assert by_code["5139"].usage == 0
    assert by_code["5133"].usage_label() == "često (61 knjiženja)"
    assert by_code["5139"].usage_label() == "nije korišćen"


def test_five_digit_analytics_belong_to_their_three_digit_account(imported):
    plan = AnalyticPlan({"K1": imported.accounts})
    assert "53190" in [a.konto for a in plan.options("K1", "531")]
    assert plan.get("K1", "53190").sintetika == "531"


def test_options_rank_by_usage_and_keep_unused_accounts_last(imported):
    plan = AnalyticPlan({"K1": imported.accounts})
    assert [a.konto for a in plan.options("K1", "513")] == ["5133", "5130", "5131", "5139"]


def test_trial_plan_without_counts_keeps_its_order():
    plan = AnalyticPlan({"K1": [AnalyticAccount(konto="5139", naziv="b"), AnalyticAccount(konto="5130", naziv="a")]})
    assert [a.konto for a in plan.options("K1", "513")] == ["5139", "5130"]


def test_overlap_tie_goes_to_the_more_used_account():
    options = [AnalyticAccount(konto="5121", naziv="Kancelarijski materijal", tg=0, pg=0),
               AnalyticAccount(konto="5129", naziv="Ostali materijal", tg=50, pg=40)]
    assert best_by_overlap("materijal", options).konto == "5129"


def test_long_numbers_in_plan_names_are_masked():
    assert mask_plan_name("Porez na imovinu 700000001-11") == "Porez na imovinu [BROJ]"
    assert mask_plan_name("Troškovi zakupa 2026") == "Troškovi zakupa 2026"


def test_llm_gets_usage_labels_and_masked_names(chart, history, rules, imported):
    llm = FakeLLM(analytic="5130")
    classifier = Classifier(chart=chart, history=history, rules=rules, llm=llm,
                            analytic_plan=AnalyticPlan({"K1": imported.accounts}))
    item = InvoiceItem(name="Električna energija za oktobar", supplier_name="Elektro Test DOO",
                       supplier_pib="100000001", given_konto="513")
    result = classifier.classify(ItemContext(client_id="K1", client_activity="proizvodnja", item=item))
    assert result.analytic.konto == "5130" and result.analytic.source == AnalyticSource.LLM
    sent = llm.analytic_requests[0]
    assert [o.konto for o in sent.options] == ["5133", "5130", "5131", "5139"]
    assert sent.options[0].usage_label == "često (61 knjiženja)"
    assert sent.options[-1].usage_label == "nije korišćen"

    item = InvoiceItem(name="Porez na imovinu", given_konto="555")
    classifier.classify(ItemContext(client_id="K1", client_activity="proizvodnja", item=item))
    assert all("700000001" not in o.naziv for r in llm.analytic_requests for o in r.options)


def test_import_script_refuses_to_write_inside_the_repo(tmp_path):
    from scripts.import_pdf_plan import ROOT, main

    assert main([str(tmp_path / "x.pdf"), "--client-id", "K1", "--out", str(ROOT / "data" / "plan.json")]) == 2
    assert main([str(ROOT / "x.pdf"), "--client-id", "K1", "--out", str(tmp_path / "plan.json")]) == 2
