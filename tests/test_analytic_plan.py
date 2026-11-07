import json

import pytest
from openpyxl import Workbook

from app.analytic import AnalyticAccount, AnalyticPlan, ColumnMapping, import_rows, read_table, save_client_plan
from app.config import DATA_DIR
from scripts.import_analytic_plan import main as import_main


def test_trial_plan_contains_every_analytic_account_the_accountant_wrote():
    plan = AnalyticPlan.load(DATA_DIR / "analiticki_plan.json")
    codes = {a.konto for a in plan.accounts("K001")}
    blind = {"5110", "5112", "5120", "5133", "5315", "5321", "5331", "5390", "5501", "5510", "5530"}
    new = {"5311", "5330", "5133", "5150", "5340", "5390", "5501", "5503", "5510", "5530", "5391"}
    assert codes == blind | new
    assert "5590" not in codes  # pending correction, deliberately left out
    assert all(a.probni for a in plan.accounts("K001"))
    assert plan.status == "probni"


def test_trial_plan_has_short_names_and_the_api_returns_them(client):
    plan = AnalyticPlan.load(DATA_DIR / "analiticki_plan.json")
    assert all(a.kratko for a in plan.accounts("K001"))
    assert plan.get("K001", "5331").kratko == "Zakup magacina"
    assert AnalyticAccount(konto="5330", naziv="x").kratko is None  # Iris imports may not have one


def test_every_trial_analytic_belongs_to_an_account_in_the_chart(chart):
    plan = AnalyticPlan.load(DATA_DIR / "analiticki_plan.json")
    assert all(a.sintetika in chart for a in plan.accounts("K001"))


def test_options_only_below_the_synthetic_account():
    plan = AnalyticPlan({"c": [AnalyticAccount(konto="5330", naziv="a"), AnalyticAccount(konto="5331", naziv="b"),
                               AnalyticAccount(konto="5340", naziv="c")]})
    assert [a.konto for a in plan.options("c", "533")] == ["5330", "5331"]
    assert plan.options("c", "513") == []
    assert plan.options("other", "533") == []
    assert plan.options("c", None) == []


def test_import_csv_semicolon_cp1250_with_custom_headers(tmp_path):
    path = tmp_path / "iris.csv"
    path.write_text("Izvoz kontnog plana\n\nŠifra;Opis;Tip\n513;Troškovi goriva;S\n5130;Gorivo;A\n"
                    "5131;Električna energija;A\n5131;duplikat;A\nx;neispravno;A\n", encoding="cp1250")
    mapping = ColumnMapping(konto="Šifra", naziv="Opis", encoding="cp1250")
    result = import_rows(read_table(path, mapping), mapping, source="iris.csv")
    assert [(a.konto, a.naziv) for a in result.accounts] == [("5130", "Gorivo"), ("5131", "Električna energija")]
    reasons = " ".join(r for _, r in result.skipped)
    assert "sintetika" in reasons and "ponavlja" in reasons and "nije broj" in reasons
    assert all(a.probni is False for a in result.accounts)


def test_import_xlsx_by_column_number_and_header_row(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Plan"
    ws.append(["Firma — kontni plan"])
    ws.append([])
    ws.append(["Rb", "Konto", "Naziv računa"])
    ws.append([1, 5330, "Zakup poslovnog prostora"])
    ws.append([2, "5331", "Zakup magacina"])
    ws.append([3, 5332, None])
    path = tmp_path / "plan.xlsx"
    wb.save(path)
    mapping = ColumnMapping(konto=2, naziv=3, header_row=3, sheet="Plan")
    result = import_rows(read_table(path, mapping), mapping)
    assert [a.konto for a in result.accounts] == ["5330", "5331"]
    assert any("nema naziv" in r for _, r in result.skipped)


def test_default_column_names_are_found_case_insensitively(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("KONTO,Naziv\n5501,Advokatske usluge\n", encoding="utf-8")
    mapping = ColumnMapping()
    assert [a.konto for a in import_rows(read_table(path, mapping), mapping).accounts] == ["5501"]


def test_missing_header_is_an_error(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("a;b\n5501;x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Zaglavlje"):
        import_rows(read_table(path, ColumnMapping()), ColumnMapping())


def test_save_replaces_one_client_and_keeps_others(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"status": "probni", "_napomena": "probni", "clients": {
        "K001": {"delatnost": "dijetetski proizvodi", "konta": [{"konto": "5110", "naziv": "x", "probni": True}]},
        "K002": {"konta": [{"konto": "5330", "naziv": "y", "probni": True}]},
    }}), encoding="utf-8")
    save_client_plan(plan_path, "K001", [AnalyticAccount(konto="5130", naziv="Gorivo")], delatnost=None,
                     source="uvoz: iris.xlsx")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["clients"]["K001"]["konta"] == [{"konto": "5130", "naziv": "Gorivo", "probni": False}]
    assert data["clients"]["K001"]["delatnost"] == "dijetetski proizvodi"
    assert data["clients"]["K002"]["konta"][0]["konto"] == "5330"
    assert data["status"] == "probni"  # K002 is still a trial plan


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    export = tmp_path / "e.csv"
    export.write_text("konto;naziv\n5130;Gorivo\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    assert import_main([str(export), "--client-id", "K001", "--plan", str(plan_path), "--dry-run"]) == 0
    assert not plan_path.exists()
    assert "DRY RUN" in capsys.readouterr().out
    assert import_main([str(export), "--client-id", "K001", "--plan", str(plan_path)]) == 0
    assert json.loads(plan_path.read_text(encoding="utf-8"))["status"] == "uvezen"
