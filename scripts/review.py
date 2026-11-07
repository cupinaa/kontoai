"""Materials for review by an accountant — and import of the filled-in files.

    python scripts/review.py predictions   # freeze the system's suggestions from the local LLM cache
    python scripts/review.py generate      # create the three Excel files in data/review/
    python scripts/review.py import        # read the filled files, write the report and data/eval/knjigovodja.json

None of these commands calls the Gemini API. `predictions` replays the pipeline with a
provider that only reads answers cached by the approved evaluation run (.eval_cache/);
an item missing from the cache gets no suggestion instead of triggering a call.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.chart import ChartOfAccounts  # noqa: E402
from app.classifier import ItemContext  # noqa: E402
from app.config import DATA_DIR, get_settings  # noqa: E402
from app.llm.base import LLMError, LLMProvider, LLMRequest, LLMSuggestion  # noqa: E402
from app.masking import mask_for_llm  # noqa: E402
from app.models import InvoiceItem  # noqa: E402
from app.service import build_classifier  # noqa: E402

REVIEW_DIR = DATA_DIR / "review"
DATASET = DATA_DIR / "eval" / "dataset.json"
PREDICTIONS = DATA_DIR / "eval" / "system_predictions.json"
ACCOUNTANT_DATASET = DATA_DIR / "eval" / "knjigovodja.json"
REPORT = REVIEW_DIR / "izvestaj_provere.md"

CHART_FILE = "kontni_okvir_provera.xlsx"
BLIND_FILE = "slepa_provera.xlsx"
NEW_FILE = "nove_stavke.xlsx"

EXAMPLE_MARKER = "PRIMER"
SHUFFLE_SEED = 2026
PREDICTION_MODEL = "gemini-3.6-flash"

# ----------------------------------------------------------------------------- styling

_HEADER_FILL = PatternFill("solid", fgColor="E8ECF1")
_INPUT_FILL = PatternFill("solid", fgColor="FFF8E1")
_EXAMPLE_FONT = Font(italic=True, color="7A7A7A")
_THIN = Side(style="thin", color="C8CED6")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrap_text=True, vertical="top")


def _sheet(wb: Workbook, title: str, intro: list[str], headers: list[str], widths: list[int], first: bool = True):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    for i, line in enumerate(intro, start=1):
        ws.cell(row=i, column=1, value=line).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
        ws.cell(row=i, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=len(headers))
        if i > 1:
            ws.row_dimensions[i].height = 32
    header_row = len(intro) + 2
    for col, (name, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=header_row, column=col, value=name)
        cell.font = Font(bold=True)
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = _WRAP
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    return ws, header_row


def _row(ws, row: int, values: list, input_cols: set[int], text_cols: set[int] = frozenset()):
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.border = _BORDER
        cell.alignment = _WRAP
        if col in input_cols:
            cell.fill = _INPUT_FILL
        if col in text_cols:
            cell.number_format = "@"  # keep leading zeros: "023" must not become 23


# ----------------------------------------------------------------------------- predictions


class _CacheMiss(LLMProvider):
    name, model = "cache-only", PREDICTION_MODEL

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        raise LLMError("odgovor nije u lokalnom kešu — API nije pozvan")


def export_predictions(dataset: Path = DATASET, output: Path = PREDICTIONS, model: str = PREDICTION_MODEL) -> dict:
    """Replay the pipeline using ONLY cached LLM answers. Never calls the API."""
    import evaluate  # scripts/evaluate.py

    data = json.loads(dataset.read_text(encoding="utf-8"))
    miss = _CacheMiss()
    miss.model = model
    cached = evaluate.CachedProvider(miss, evaluate.CACHE_DIR)
    predictions, misses = {}, 0
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(get_settings(), db_path=Path(tmp) / "p.db", gemini_api_key=None)
        classifier = build_classifier(settings, llm=cached, use_llm=False)
        for seed in data["history_seed"]:
            classifier.history.add(**seed, konto_name=classifier.chart.name(seed["konto"]))
        for entry in data["items"]:
            item = InvoiceItem(name=entry["name"], quantity=entry.get("quantity"), unit=entry.get("unit"),
                               amount=entry.get("amount"), supplier_name=entry.get("supplier_name"),
                               supplier_pib=entry.get("supplier_pib"))
            ctx = ItemContext(client_id=entry["client_id"], client_activity=data["clients"][entry["client_id"]],
                              item=item)
            s = classifier.classify(ctx)
            misses += "nije u lokalnom kešu" in s.explanation
            predictions[str(entry["id"])] = {
                "konto": s.konto, "source": s.source.value, "confidence": s.confidence,
                "needs_review": s.needs_review,
            }
    result = {
        "_note": "Predlozi sistema za stavke iz data/eval/dataset.json, rekonstruisani iz keširanih odgovora "
                 "odobrenog pokretanja evaluacije, bez ijednog poziva ka API-ju.",
        "model": model,
        "generated": date.today().isoformat(),
        "cache_misses": misses,
        "predictions": predictions,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


# ----------------------------------------------------------------------------- generate


def generate(out_dir: Path = REVIEW_DIR, dataset: Path = DATASET) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chart = ChartOfAccounts.load(get_settings().chart_path)
    data = json.loads(dataset.read_text(encoding="utf-8"))
    paths = []

    # 1. Chart of accounts check
    wb = Workbook()
    ws, hr = _sheet(
        wb, "Kontni okvir",
        ["Provera kontnog okvira — KontoAI",
         "Za svaki konto proverite da li postoji u Pravilniku o kontnom okviru (Sl. glasnik RS 89/2020) i da li je "
         "naziv tačan. U kolonu 'Tačno? (da/ne)' upišite da ili ne; ispravan broj ili naziv upišite u 'Napomena'.",
         "Konta koja nedostaju, a česta su na ulaznim fakturama, upišite na listu 'Predlog dopune'."],
        ["Konto", "Naziv", "Tačno? (da/ne)", "Napomena"], [10, 48, 16, 50],
    )
    yes_no = DataValidation(type="list", formula1='"da,ne"', allow_blank=True)
    ws.add_data_validation(yes_no)
    for i, account in enumerate(chart.accounts, start=hr + 1):
        _row(ws, i, [account.konto, account.naziv, None, None], input_cols={3, 4}, text_cols={1})
        yes_no.add(ws.cell(row=i, column=3))
    ws2, hr2 = _sheet(wb, "Predlog dopune",
                      ["Konta koja treba dodati",
                       "Trocifreni konto, naziv iz Pravilnika i kratko objašnjenje za koje stavke se koristi."],
                      ["Konto", "Naziv", "Napomena"], [10, 48, 60], first=False)
    for r in range(hr2 + 1, hr2 + 21):
        _row(ws2, r, [None, None, None], input_cols={1, 2, 3}, text_cols={1})
    paths.append(out_dir / CHART_FILE)
    wb.save(paths[-1])

    # 2. Blind check — no system suggestion, no expected account; order shuffled
    items = list(data["items"])
    random.Random(SHUFFLE_SEED).shuffle(items)
    wb = Workbook()
    ws, hr = _sheet(
        wb, "Slepa provera",
        ["Slepa provera kontiranja — KontoAI",
         "Za svaku stavku upišite konto na koji biste je proknjižili. Dovoljan je trocifreni konto; ako upišete "
         "analitički (npr. 5130), porediće se prve tri cifre. Konto ne mora biti iz bilo kog spiska.",
         "Ako opis nije dovoljan da se odluči, upišite ? i u napomeni navedite šta bi vam trebalo. "
         "Stavke su izmišljene; redosled je namerno izmešan."],
        ["ID", "Opis stavke", "Delatnost klijenta", "Tačan konto", "Napomena"], [6, 46, 38, 14, 50],
    )
    for i, entry in enumerate(items, start=hr + 1):
        _row(ws, i, [entry["id"], entry["name"], data["clients"][entry["client_id"]], None, None],
             input_cols={4, 5}, text_cols={4})
    paths.append(out_dir / BLIND_FILE)
    wb.save(paths[-1])

    # 3. Template for new items
    wb = Workbook()
    ws, hr = _sheet(
        wb, "Nove stavke",
        ["Nove stavke za evaluaciju — KontoAI",
         "VAŽNO: bez imena klijenata i dobavljača. Ne upisujte ni imena osoba, PIB, matične brojeve ni brojeve "
         "računa — samo opis stavke kako stoji na fakturi i delatnost klijenta opštim rečima.",
         f"Dva sivo označena reda su primeri formata (u napomeni počinju sa '{EXAMPLE_MARKER}') i ne uvoze se. "
         "Tačan konto: trocifreni ili analitički; ako stavka može na više konta, navedite to u napomeni."],
        ["Opis stavke", "Delatnost klijenta", "Tačan konto", "Napomena"], [46, 38, 14, 56],
    )
    examples = [
        ["Taxi prevoz do aerodroma", "Konsultantske usluge u oblasti IT", "531",
         f"{EXAMPLE_MARKER} — prevoz zaposlenih na službeni put; ovaj red se ne uvozi"],
        ["Stolica kancelarijska ergonomska", "Trgovina na malo nameštajem", "134",
         f"{EXAMPLE_MARKER} — za ovu delatnost roba za prodaju, ne inventar; ovaj red se ne uvozi"],
    ]
    for i, values in enumerate(examples, start=hr + 1):
        _row(ws, i, values, input_cols=set(), text_cols={3})
        for col in range(1, 5):
            ws.cell(row=i, column=col).font = _EXAMPLE_FONT
    for r in range(hr + 3, hr + 3 + 200):
        _row(ws, r, [None, None, None, None], input_cols={1, 2, 3, 4}, text_cols={3})
    paths.append(out_dir / NEW_FILE)
    wb.save(paths[-1])
    return paths


# ----------------------------------------------------------------------------- import


def _rows(path: Path, first_header: str) -> tuple[list[str], list[list]]:
    """Return (headers, rows) of the first sheet, locating the header row by its first cell."""
    ws = load_workbook(path, data_only=True).worksheets[0]
    values = list(ws.iter_rows(values_only=True))
    for i, row in enumerate(values):
        if row and str(row[0] or "").strip() == first_header:
            headers = [str(h or "").strip() for h in row]
            return headers, [list(r) for r in values[i + 1:] if any(c not in (None, "") for c in r)]
    raise ValueError(f"{path.name}: nije pronađen red sa zaglavljem '{first_header}'")


def normalize_konto(value) -> tuple[str | None, str]:
    """Return (3-digit konto or '?' or None, raw text). Accepts 513, '5130', ' 023 ', 23 (Excel lost the zero)."""
    if value is None or str(value).strip() == "":
        return None, ""
    raw = str(value).strip()
    if raw == "?":
        return "?", raw
    if isinstance(value, (int, float)) and float(value).is_integer():
        raw = str(int(value))
        if len(raw) < 3:
            raw = raw.zfill(3)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 3:
        return None, raw
    return digits[:3], raw


def import_chart(path: Path) -> dict:
    _, rows = _rows(path, "Konto")
    result = {"ok": [], "wrong": [], "empty": []}
    for konto, naziv, verdict, note, *_ in rows + []:
        if konto is None:
            continue
        verdict = str(verdict or "").strip().lower()
        key = "ok" if verdict == "da" else "wrong" if verdict == "ne" else "empty"
        result[key].append({"konto": str(konto), "naziv": naziv, "napomena": note})
    additions = []
    ws = load_workbook(path, data_only=True)
    if len(ws.worksheets) > 1:
        for row in list(ws.worksheets[1].iter_rows(values_only=True)):
            if row and row[0] not in (None, "", "Konto") and re.match(r"^\s*\d{3}", str(row[0])):
                additions.append({"konto": str(row[0]).strip(), "naziv": row[1], "napomena": row[2]})
    result["additions"] = additions
    return result


def import_blind(path: Path, dataset: Path, predictions_path: Path, chart: ChartOfAccounts) -> dict:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    by_id = {str(i["id"]): i for i in data["items"]}
    predictions = {}
    if predictions_path.exists():
        predictions = json.loads(predictions_path.read_text(encoding="utf-8"))["predictions"]
    _, rows = _rows(path, "ID")
    out = []
    for row in rows:
        item_id, _desc, _activity, answer, note = (row + [None] * 5)[:5]
        if item_id is None or str(int(item_id) if isinstance(item_id, float) else item_id) not in by_id:
            continue
        key = str(int(item_id)) if isinstance(item_id, float) else str(item_id)
        entry = by_id[key]
        konto, raw = normalize_konto(answer)
        pred = predictions.get(key, {})
        out.append({
            "id": int(key), "name": entry["name"], "difficulty": entry.get("difficulty", "easy"),
            "accountant": konto, "accountant_raw": raw, "note": note,
            "expected": entry["expected_konto"], "system": pred.get("konto"),
            "system_needs_review": pred.get("needs_review"),
            "in_chart": konto in chart if konto not in (None, "?") else None,
        })
    return {"rows": sorted(out, key=lambda r: r["id"]), "total": len(data["items"])}


def import_new(path: Path, chart: ChartOfAccounts, output: Path = ACCOUNTANT_DATASET) -> dict:
    _, rows = _rows(path, "Opis stavke")
    clients: dict[str, str] = {}
    items, skipped = [], []
    for n, row in enumerate(rows, start=1):
        desc, activity, answer, note = (row + [None] * 4)[:4]
        if str(note or "").strip().upper().startswith(EXAMPLE_MARKER):
            continue
        if not desc and not activity and answer in (None, ""):
            continue
        desc, activity = str(desc or "").strip(), str(activity or "").strip()
        konto, raw = normalize_konto(answer)
        problems = []
        if not desc:
            problems.append("nema opisa stavke")
        if len(activity) < 2:
            problems.append("nema delatnosti klijenta")
        if konto in (None, "?"):
            problems.append("nema tačnog konta")
        masked_desc, _ = mask_for_llm(desc)
        masked_act, _ = mask_for_llm(activity)
        if masked_desc != desc or masked_act != activity:
            problems.append("izgleda da sadrži lične/poslovne podatke (PIB, ime, račun...) — ispraviti")
        if problems:
            skipped.append({"row": n, "opis": desc, "razlozi": problems})
            continue
        client_id = clients.setdefault(activity, f"K{len(clients) + 1:03d}")
        items.append({
            "id": len(items) + 1, "client_id": client_id, "name": desc, "expected_konto": konto,
            "accountant_konto_raw": raw, "note": note, "konto_in_chart": konto in chart,
            "difficulty": "accountant", "expected_source": "unknown",
        })
    dataset = {
        "_napomena": "Stavke i tačna konta koje je uneo knjigovođa (data/review/nove_stavke.xlsx). "
                     "Evaluacija na ovom skupu traži posebno odobrenje jer šalje pozive ka LLM-u.",
        "_note": "Items and accounts provided by an accountant. Running the evaluation on them needs separate "
                 "approval because it calls the LLM API.",
        "source": "accountant",
        "imported": date.today().isoformat(),
        "clients": {v: k for k, v in clients.items()},
        "history_seed": [],
        "items": items,
    }
    if items:
        output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"items": items, "skipped": skipped, "written": bool(items), "path": output}


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}%" if b else "—"


def render_report(chart_res: dict | None, blind: dict | None, new: dict | None) -> str:
    out = ["# Izveštaj provere knjigovođe", "", f"Datum uvoza: {date.today().isoformat()}", ""]

    out += ["## 1. Kontni okvir", ""]
    if chart_res is None:
        out.append("Fajl nije pronađen.")
    else:
        filled = len(chart_res["ok"]) + len(chart_res["wrong"])
        out.append(f"Provereno: {filled} od {filled + len(chart_res['empty'])} konta — tačno: "
                   f"{len(chart_res['ok'])}, netačno: {len(chart_res['wrong'])}.")
        if chart_res["wrong"]:
            out += ["", "| Konto | Naziv | Napomena |", "|---|---|---|"]
            out += [f"| {w['konto']} | {w['naziv']} | {w['napomena'] or ''} |" for w in chart_res["wrong"]]
        if chart_res["additions"]:
            out += ["", "Predlog dopune:", "", "| Konto | Naziv | Napomena |", "|---|---|---|"]
            out += [f"| {a['konto']} | {a['naziv'] or ''} | {a['napomena'] or ''} |" for a in chart_res["additions"]]
    out.append("")

    out += ["## 2. Slepa provera", ""]
    if blind is None:
        out.append("Fajl nije pronađen.")
    else:
        rows = [r for r in blind["rows"] if r["accountant"] is not None]
        decided = [r for r in rows if r["accountant"] != "?"]
        unclear = [r for r in rows if r["accountant"] == "?"]
        agree_exp = [r for r in decided if r["accountant"] == r["expected"]]
        agree_sys = [r for r in decided if r["system"] and r["accountant"] == r["system"]]
        out += [
            f"Popunjeno: {len(rows)} od {blind['total']} stavki ({len(unclear)} označeno sa '?').",
            "",
            "| Poređenje (stavke gde je knjigovođa upisao konto) | Slaže se | Udeo |",
            "|---|---|---|",
            f"| Knjigovođa = očekivani konto iz dataseta | {len(agree_exp)} / {len(decided)} | "
            f"{_pct(len(agree_exp), len(decided))} |",
            f"| Knjigovođa = predlog sistema | {len(agree_sys)} / {len(decided)} | "
            f"{_pct(len(agree_sys), len(decided))} |",
        ]
        for difficulty in ("easy", "hard"):
            group = [r for r in decided if r["difficulty"] == difficulty]
            if group:
                out.append(f"| — samo {difficulty}: knjigovođa = sistem | "
                           f"{sum(r['system'] == r['accountant'] for r in group)} / {len(group)} | "
                           f"{_pct(sum(r['system'] == r['accountant'] for r in group), len(group))} |")
        silent = [r for r in decided if r["system"] and r["system"] != r["accountant"] and not r["system_needs_review"]]
        out += ["", f"**Tihe greške sistema prema knjigovođi** (sistem pogrešio, a nije označio za proveru): "
                    f"{len(silent)}"]
        if unclear:
            flagged = sum(bool(r["system_needs_review"]) for r in unclear)
            out.append(f"Od {len(unclear)} stavki koje je knjigovođa označio sa '?', sistem je {flagged} "
                       "takođe označio za ručnu proveru.")
        outside = [r for r in decided if r["in_chart"] is False]
        if outside:
            out.append(f"Konta koja je knjigovođa upisao, a nisu na spisku sistema: "
                       f"{', '.join(sorted({r['accountant'] for r in outside}))} — sistem ih ne može predložiti.")
        diff = [r for r in decided if r["accountant"] != r["expected"] or r["accountant"] != r["system"]] + unclear
        if diff:
            out += ["", "### Razlike", "", "| ID | Stavka | Knjigovođa | Očekivano (dataset) | Sistem | "
                    "Sistem označio proveru | Napomena |", "|---|---|---|---|---|---|---|"]
            for r in sorted(diff, key=lambda r: r["id"]):
                out.append(f"| {r['id']} | {r['name']} | {r['accountant_raw']} | {r['expected']} | "
                           f"{r['system'] or '—'} | {'da' if r['system_needs_review'] else 'ne'} | "
                           f"{r['note'] or ''} |")
            out += ["", "Očekivana konta u datasetu NISU automatski izmenjena — odluku o ispravci donosi autor "
                        "uz knjigovođu."]
    out.append("")

    out += ["## 3. Nove stavke", ""]
    if new is None:
        out.append("Fajl nije pronađen.")
    else:
        out.append(f"Uvezeno: {len(new['items'])} stavki; preskočeno: {len(new['skipped'])}.")
        if new["written"]:
            path = new["path"]
            shown = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
            out.append(f"Dataset: `{shown}`. Evaluacija NIJE pokrenuta — "
                       "traži posebno odobrenje.")
        not_in_chart = [i for i in new["items"] if not i["konto_in_chart"]]
        if not_in_chart:
            out.append(f"Stavke sa kontom van spiska sistema: {len(not_in_chart)} "
                       f"({', '.join(sorted({i['expected_konto'] for i in not_in_chart}))}).")
        if new["skipped"]:
            out += ["", "| Red | Opis | Razlog |", "|---|---|---|"]
            out += [f"| {s['row']} | {s['opis']} | {'; '.join(s['razlozi'])} |" for s in new["skipped"]]
    return "\n".join(out) + "\n"


def run_import(review_dir: Path = REVIEW_DIR, dataset: Path = DATASET, predictions: Path = PREDICTIONS,
               accountant_dataset: Path = ACCOUNTANT_DATASET, report: Path = REPORT) -> str:
    chart = ChartOfAccounts.load(get_settings().chart_path)
    chart_res = import_chart(review_dir / CHART_FILE) if (review_dir / CHART_FILE).exists() else None
    blind = (import_blind(review_dir / BLIND_FILE, dataset, predictions, chart)
             if (review_dir / BLIND_FILE).exists() else None)
    new = import_new(review_dir / NEW_FILE, chart, accountant_dataset) if (review_dir / NEW_FILE).exists() else None
    text = render_report(chart_res, blind, new)
    report.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["predictions", "generate", "import"])
    args = parser.parse_args()
    if args.command == "predictions":
        result = export_predictions()
        print(f"Wrote {PREDICTIONS} ({len(result['predictions'])} items, cache misses: {result['cache_misses']}). "
              "No API calls.")
    elif args.command == "generate":
        for path in generate():
            print(f"Wrote {path}")
    else:
        run_import()
        print(f"Report: {REPORT}")
        if ACCOUNTANT_DATASET.exists():
            print(f"Accountant dataset: {ACCOUNTANT_DATASET} (evaluation NOT run)")


if __name__ == "__main__":
    main()
