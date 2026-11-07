"""Review materials for the accountant: generation and import of filled files. No API calls."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.config import DATA_DIR

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review.py"


@pytest.fixture
def review(monkeypatch):
    spec = importlib.util.spec_from_file_location("review_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "review_script", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def generated(review, tmp_path):
    review.generate(out_dir=tmp_path)
    return tmp_path


def header_and_rows(path, first_header):
    ws = load_workbook(path).worksheets[0]
    rows = list(ws.iter_rows())
    for i, row in enumerate(rows):
        if row[0].value == first_header:
            return ws, i + 1, [c.value for c in row], rows[i + 1:]
    raise AssertionError("header not found")


def test_chart_file_lists_every_account(generated):
    chart = json.loads((DATA_DIR / "kontni_okvir.json").read_text(encoding="utf-8"))["konta"]
    _, _, headers, rows = header_and_rows(generated / "kontni_okvir_provera.xlsx", "Konto")
    assert headers == ["Konto", "Naziv", "Tačno? (da/ne)", "Napomena"]
    listed = [(r[0].value, r[1].value) for r in rows if r[0].value]
    assert listed == [(a["konto"], a["naziv"]) for a in chart]
    assert all(r[2].value is None and r[3].value is None for r in rows)
    assert listed[0][0] == "023"  # leading zero kept


def test_blind_file_has_only_allowed_columns_and_all_items(generated):
    data = json.loads((DATA_DIR / "eval" / "dataset.json").read_text(encoding="utf-8"))
    path = generated / "slepa_provera.xlsx"
    _, _, headers, rows = header_and_rows(path, "ID")
    assert headers == ["ID", "Opis stavke", "Delatnost klijenta", "Tačan konto", "Napomena"]
    ids = [r[0].value for r in rows if r[0].value is not None]
    assert sorted(ids) == sorted(i["id"] for i in data["items"])
    assert ids != sorted(ids)  # shuffled, so easy/hard order does not leak

    # No expected account, system suggestion, source or confidence anywhere in the workbook.
    text = " ".join(str(c) for ws in load_workbook(path).worksheets for row in ws.iter_rows(values_only=True)
                    for c in row if c is not None)
    for leak in ("expected", "Očekivan", "Predlog", "Sigurnost", "Izvor", "history", "llm"):
        assert leak not in text
    assert all(r[3].value is None and r[4].value is None for r in rows)


def test_new_items_template(generated):
    ws = load_workbook(generated / "nove_stavke.xlsx").worksheets[0]
    top = " ".join(str(ws.cell(row=r, column=1).value or "") for r in range(1, 4))
    assert "bez imena klijenata i dobavljača" in top
    _, _, headers, rows = header_and_rows(generated / "nove_stavke.xlsx", "Opis stavke")
    assert headers == ["Opis stavke", "Delatnost klijenta", "Tačan konto", "Napomena"]
    examples = [r for r in rows if r[0].value]
    assert len(examples) == 2
    assert all(str(r[3].value).startswith("PRIMER") for r in examples)


@pytest.mark.parametrize(
    "value, expected",
    [(513, "513"), ("5130", "513"), (" 023 ", "023"), (23, "023"), ("?", "?"), (None, None), ("", None), ("x", None)],
)
def test_normalize_konto(review, value, expected):
    assert review.normalize_konto(value)[0] == expected


def fill(path, first_header, values_by_row):
    wb = load_workbook(path)
    ws, header_row, _, _ = header_and_rows(path, first_header)
    ws = wb.worksheets[0]
    for offset, values in values_by_row.items():
        for col, value in values.items():
            ws.cell(row=header_row + 1 + offset, column=col, value=value)
    wb.save(path)


def blind_row_index(path, item_id):
    _, _, _, rows = header_and_rows(path, "ID")
    return next(i for i, r in enumerate(rows) if r[0].value == item_id)


def test_import_compares_accountant_with_expected_and_system(review, generated, tmp_path):
    blind = generated / "slepa_provera.xlsx"
    fill(blind, "ID", {
        blind_row_index(blind, 7): {4: "513"},               # Evrodizel: agrees with both
        blind_row_index(blind, 33): {4: "5300", 5: "podizvođač"},  # system said 530, expected 539
        blind_row_index(blind, 31): {4: "?", 5: "premalo podataka"},
        blind_row_index(blind, 19): {4: 23},                 # Excel dropped the zero of 023
    })
    chart_file = generated / "kontni_okvir_provera.xlsx"
    fill(chart_file, "Konto", {0: {3: "da"}, 1: {3: "ne", 4: "proveriti naziv"}})

    report = review.run_import(review_dir=generated, accountant_dataset=tmp_path / "k.json",
                               report=tmp_path / "r.md")

    assert "Popunjeno: 4 od 50" in report
    assert "| Knjigovođa = očekivani konto iz dataseta | 2 / 3 |" in report
    assert "| Knjigovođa = predlog sistema | 3 / 3 |" in report
    assert "Tihe greške sistema prema knjigovođi** (sistem pogrešio, a nije označio za proveru): 0" in report
    assert "sistem je 1 takođe označio" in report
    assert "| 33 | Usluge po ugovoru za oktobar | 5300 | 539 | 530 | da | podizvođač |" in report
    assert "tačno: 1, netačno: 1" in report
    assert "NISU automatski izmenjena" in report


def test_import_new_items_builds_dataset_and_skips_examples_and_personal_data(review, generated, tmp_path):
    new = generated / "nove_stavke.xlsx"
    fill(new, "Opis stavke", {
        2: {1: "Servis klima uređaja", 2: "Proizvodnja nameštaja", 3: "532"},
        3: {1: "Nabavka drveta - hrast", 2: "Proizvodnja nameštaja", 3: "1010", 4: "materijal na zalihama"},
        4: {1: "Usluga čišćenja, kontakt: Marko Marković", 2: "Restoran", 3: "539"},  # personal data
        5: {1: "Licenca za softver", 2: "Razvoj softvera", 3: "012"},  # outside our chart
        6: {1: "Bez konta", 2: "Restoran"},
    })
    out = tmp_path / "knjigovodja.json"
    report = review.run_import(review_dir=generated, accountant_dataset=out, report=tmp_path / "r.md")

    data = json.loads(out.read_text(encoding="utf-8"))
    names = [i["name"] for i in data["items"]]
    assert names == ["Servis klima uređaja", "Nabavka drveta - hrast", "Licenca za softver"]
    assert [i["expected_konto"] for i in data["items"]] == ["532", "101", "012"]
    assert data["items"][0]["client_id"] == data["items"][1]["client_id"]  # same activity, same client
    assert data["clients"][data["items"][0]["client_id"]] == "Proizvodnja nameštaja"
    assert data["items"][2]["konto_in_chart"] is False
    assert "Taxi" not in json.dumps(data, ensure_ascii=False)  # examples are not imported
    assert "Uvezeno: 3 stavki; preskočeno: 2" in report
    assert "lične/poslovne podatke" in report
    assert "Evaluacija NIJE pokrenuta" in report


def test_import_with_empty_files_does_not_write_dataset(review, generated, tmp_path):
    out = tmp_path / "k.json"
    report = review.run_import(review_dir=generated, accountant_dataset=out, report=tmp_path / "r.md")
    assert not out.exists()
    assert "Popunjeno: 0 od 50" in report


def test_predictions_file_matches_evaluation():
    data = json.loads((DATA_DIR / "eval" / "dataset.json").read_text(encoding="utf-8"))
    preds = json.loads((DATA_DIR / "eval" / "system_predictions.json").read_text(encoding="utf-8"))
    assert preds["cache_misses"] == 0
    assert len(preds["predictions"]) == len(data["items"])
    correct = sum(preds["predictions"][str(i["id"])]["konto"] == i["expected_konto"] for i in data["items"])
    assert correct == 49
