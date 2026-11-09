"""Import a client's analytic plan from the accounting software's "Konta: Lista" PDF.

    python scripts/import_pdf_plan.py "C:\\...\\kontoai_private\\Kontni plan.pdf" --client-id K001 \\
        --out C:\\...\\kontoai_private\\analiticki_plan.json

The PDF and everything extracted from it are CONFIDENTIAL client data, so --out and the report must be
outside the repository; the script refuses to write inside it. Point the app at the result with
KONTOAI_ANALYTIC_PLAN_PATH in .env. No LLM is involved.

Kept: Aktuelan = Da, classes 01, 02, 10, 13 and 5, accounts with 4 or more digits.
The report (next to --out) lists the count per 3-digit account, every flagged row and 20 random rows
to compare with the PDF by hand.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.analytic import save_client_plan  # noqa: E402
from app.analytic_pdf import build_plan, collect_rows  # noqa: E402


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def read_pdf(path: Path) -> list[list[list]]:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            rows: list[list] = []
            for table in page.extract_tables():
                rows.extend(table)
            pages.append(rows)
    return pages


def report(result, total_rows: int, pdf_name: str, sample_seed: int) -> str:
    per_parent = Counter(a.sintetika for a in result.accounts)
    lines = [
        f"# Uvoz analitičkog plana iz {pdf_name}",
        "",
        f"- Redova u PDF-u: {total_rows}",
        f"- Uvezeno analitičkih konta: **{len(result.accounts)}** (pod {len(per_parent)} trocifrenih konta)",
        f"- Sa bar jednim knjiženjem (TG + PG > 0): {sum(1 for a in result.accounts if a.usage)}",
        "",
        "Preskočeno:",
        *[f"- {reason}: {n}" for reason, n in result.skipped.most_common()],
        "",
        "## Broj uvezenih konta po trocifrenom kontu",
        "",
        "| Konto | Naziv u planu | Analitika | Korišćenih |",
        "|---|---|---|---|",
    ]
    for parent in sorted(per_parent):
        used = sum(1 for a in result.accounts if a.sintetika == parent and a.usage)
        lines.append(f"| {parent} | {result.parents.get(parent, '—')} | {per_parent[parent]} | {used} |")
    lines += ["", f"## Redovi za proveru ({len(result.flagged)})", ""]
    if result.flagged:
        lines += ["| Konto | Naziv | Razlog |", "|---|---|---|"]
        lines += [f"| {k} | {n or '(prazno)'} | {r} |" for k, n, r in result.flagged]
    else:
        lines.append("Nema.")
    sample = random.Random(sample_seed).sample(result.accounts, min(20, len(result.accounts)))
    lines += ["", f"## 20 nasumičnih redova za ručno poređenje sa PDF-om (seed {sample_seed})", "",
              "| Konto | Naziv | TG | PG |", "|---|---|---|---|"]
    lines += [f"| {a.konto} | {a.naziv} | {a.tg} | {a.pg} |" for a in sorted(sample, key=lambda a: a.konto)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--delatnost", help="client's activity (kept from an existing plan in --out if omitted)")
    parser.add_argument("--out", type=Path, required=True, help="plan JSON, OUTSIDE the repository")
    parser.add_argument("--seed", type=int, default=7, help="seed for the 20 random rows in the report")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = parser.parse_args(argv)

    for path in (args.pdf, args.out):
        if inside_repo(path):
            print(f"Odbijeno: {path} je unutar repoa. Poverljivi podaci moraju biti van njega.", file=sys.stderr)
            return 2
    pages = read_pdf(args.pdf)
    rows = collect_rows(pages)
    result = build_plan(rows, source=f"uvoz: {args.pdf.name}")
    text = report(result, len(rows), args.pdf.name, args.seed)
    if args.dry_run:
        print(text)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_client_plan(args.out, args.client_id, result.accounts, delatnost=args.delatnost, source=args.pdf.name)
    report_path = args.out.with_name("izvestaj_uvoza.md")
    report_path.write_text(text, encoding="utf-8")
    print(f"Uvezeno {len(result.accounts)} konta za {args.client_id} -> {args.out}")
    print(f"Izveštaj -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
