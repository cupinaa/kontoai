"""Import a client's analytic chart of accounts from a CSV or XLSX export.

The export format of the accounting software (Iris) is not known yet, so the column mapping is
configurable instead of guessed. Always look at the result with --dry-run first.

Examples:
    python scripts/import_analytic_plan.py plan.xlsx --client-id K001 --dry-run
    python scripts/import_analytic_plan.py plan.csv --client-id K001 --konto-column "Šifra konta" \\
        --naziv-column "Naziv konta" --encoding cp1250 --delimiter ";"
    python scripts/import_analytic_plan.py plan.xlsx --client-id K001 --konto-column 1 --naziv-column 3 \\
        --header-row 5 --sheet "Kontni plan"

Columns can be given by header name (case-insensitive) or by 1-based column number.
Rows with fewer than --min-digits digits (synthetic accounts) are skipped and listed.
The client's existing plan in data/analiticki_plan.json is REPLACED; other clients are kept.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.analytic import ColumnMapping, import_rows, read_table, save_client_plan  # noqa: E402
from app.chart import ChartOfAccounts  # noqa: E402
from app.config import DATA_DIR, get_settings  # noqa: E402

PLAN = DATA_DIR / "analiticki_plan.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="CSV or XLSX export")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--delatnost", help="client's activity (kept from the existing plan if omitted)")
    parser.add_argument("--konto-column", default="konto", help="header name or 1-based number (default: konto)")
    parser.add_argument("--naziv-column", default="naziv", help="header name or 1-based number (default: naziv)")
    parser.add_argument("--header-row", type=int, help="1-based row number of the header")
    parser.add_argument("--sheet", help="XLSX sheet name (default: first sheet)")
    parser.add_argument("--delimiter", help="CSV delimiter (default: detect ; , or tab)")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSV encoding, e.g. cp1250 (default: utf-8-sig)")
    parser.add_argument("--min-digits", type=int, default=4)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--dry-run", action="store_true", help="show what would be imported, write nothing")
    args = parser.parse_args(argv)

    mapping = ColumnMapping(
        konto=args.konto_column, naziv=args.naziv_column, header_row=args.header_row, sheet=args.sheet,
        delimiter=args.delimiter, encoding=args.encoding, min_digits=args.min_digits,
    )
    try:
        rows = read_table(args.file, mapping)
        result = import_rows(rows, mapping, source=f"uvoz: {args.file.name}")
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        print(f"Greška: {exc}", file=sys.stderr)
        return 1

    chart = ChartOfAccounts.load(get_settings().chart_path)
    unknown = sorted({a.sintetika for a in result.accounts if a.sintetika not in chart})
    print(f"Pronađeno analitičkih konta: {len(result.accounts)}; preskočeno redova: {len(result.skipped)}")
    for account in result.accounts[:10]:
        print(f"  {account.konto}  {account.naziv}")
    if len(result.accounts) > 10:
        print(f"  ... još {len(result.accounts) - 10}")
    for number, reason in result.skipped[:20]:
        print(f"  preskočen red {number}: {reason}")
    if unknown:
        print(f"Upozorenje: sintetička konta {', '.join(unknown)} nisu u data/kontni_okvir.json — "
              "sistem ih neće predlagati dok se ne dodaju.")
    if not result.accounts:
        print("Ništa nije uvezeno.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("DRY RUN — plan nije izmenjen.")
        return 0
    save_client_plan(args.plan, args.client_id, result.accounts, delatnost=args.delatnost,
                     source=f"uvoz: {args.file.name}")
    print(f"Plan klijenta {args.client_id} zamenjen u {args.plan}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
