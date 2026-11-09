"""Per-client analytic chart of accounts (4+ digit accounts below a 3-digit synthetic account).

The analytic level is not prescribed by the Pravilnik; every company has its own plan. The plan is
stored in data/analiticki_plan.json as {client_id: {"konta": [{"konto", "naziv", ...}]}}.
The current file is a TRIAL plan; `import_rows` turns an export from the accounting software
(CSV/XLSX, column mapping configurable) into a client's plan.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field


class AnalyticAccount(BaseModel):
    konto: str = Field(pattern=r"^\d{4,}$")
    naziv: str
    kratko: str | None = None  # short display name for the table ("Zakup magacina"); falls back to naziv
    probni: bool = False
    izvor: str | None = None
    tg: int | None = None  # number of postings this year (Broj stavki TG), when the plan export has it
    pg: int | None = None  # number of postings last year (Broj stavki PG)

    @property
    def sintetika(self) -> str:
        return self.konto[:3]

    @property
    def usage(self) -> int | None:
        """Postings this year + last year; None when the plan carries no counts (e.g. the trial plan)."""
        if self.tg is None and self.pg is None:
            return None
        return (self.tg or 0) + (self.pg or 0)

    def usage_label(self) -> str | None:
        n = self.usage
        if n is None:
            return None
        if n == 0:
            return "nije korišćen"
        if n < 10:
            return f"retko ({n} knjiženja)"
        if n < 100:
            return f"često ({n} knjiženja)"
        return f"vrlo često ({n} knjiženja)"


class AnalyticPlan:
    def __init__(self, clients: dict[str, list[AnalyticAccount]] | None = None, status: str | None = None):
        self._clients = clients or {}
        self.status = status

    @classmethod
    def load(cls, path: Path) -> AnalyticPlan:
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        clients = {
            client_id: [AnalyticAccount.model_validate(a) for a in entry.get("konta", [])]
            for client_id, entry in data.get("clients", {}).items()
        }
        return cls(clients, status=data.get("status"))

    def has_client(self, client_id: str) -> bool:
        return bool(self._clients.get(client_id))

    def accounts(self, client_id: str) -> list[AnalyticAccount]:
        return list(self._clients.get(client_id, []))

    def options(self, client_id: str, sintetika: str | None) -> list[AnalyticAccount]:
        """Analytic accounts (4 or more digits) of this client below the given 3-digit account.

        When the plan carries posting counts, the most used accounts come first. Accounts that were
        never used are kept, just ranked last. Without counts the plan's own order is kept.
        """
        if not sintetika:
            return []
        found = [a for a in self._clients.get(client_id, []) if a.konto[:3] == sintetika[:3] and len(a.konto) > 3]
        if any(a.usage is not None for a in found):
            found.sort(key=lambda a: (-(a.usage or 0), a.konto))
        return found

    def get(self, client_id: str, konto: str) -> AnalyticAccount | None:
        return next((a for a in self._clients.get(client_id, []) if a.konto == konto), None)


_LONG_NUMBER = re.compile(r"\d[\d\-/]{4,}\d")


def mask_plan_name(naziv: str) -> str:
    """Hide long numbers in an account name (tax payment accounts, cadastral numbers) before it goes to an LLM."""
    return _LONG_NUMBER.sub("[BROJ]", naziv)


# ----------------------------------------------------------------------------- import


@dataclass
class ColumnMapping:
    """Which columns of the export hold the account number and name.

    Each column may be given as a header name (case-insensitive) or a 1-based column number.
    The exact Iris export format is not known yet, so nothing here assumes it.
    """

    konto: str | int = "konto"
    naziv: str | int = "naziv"
    header_row: int | None = None  # 1-based; None = first row that contains both column names
    sheet: str | None = None  # XLSX only; None = first sheet
    delimiter: str | None = None  # CSV only; None = detect (; , or tab)
    encoding: str = "utf-8-sig"  # CSV only; exports from Windows software are often cp1250
    min_digits: int = 4  # rows with shorter accounts (synthetic level) are skipped


def read_table(path: Path, mapping: ColumnMapping) -> list[list]:
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[mapping.sheet] if mapping.sheet else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    text = path.read_text(encoding=mapping.encoding)
    delimiter = mapping.delimiter
    if delimiter is None:
        sample = text[:4096]
        delimiter = max([";", ",", "\t"], key=sample.count)
    return [row for row in csv.reader(text.splitlines(), delimiter=delimiter)]


def _resolve(spec: str | int, header: list | None) -> int:
    if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
        return int(spec) - 1
    if header is None:
        raise ValueError(f"Kolona '{spec}' je zadata imenom, ali red zaglavlja nije pronađen.")
    names = [str(h or "").strip().casefold() for h in header]
    try:
        return names.index(str(spec).strip().casefold())
    except ValueError:
        raise ValueError(f"Kolona '{spec}' nije pronađena u zaglavlju: {header}") from None


@dataclass
class ImportResult:
    accounts: list[AnalyticAccount]
    skipped: list[tuple[int, str]]  # (row number, reason)


def import_rows(rows: list[list], mapping: ColumnMapping, source: str = "") -> ImportResult:
    by_name = not (isinstance(mapping.konto, int) or str(mapping.konto).isdigit()) or not (
        isinstance(mapping.naziv, int) or str(mapping.naziv).isdigit()
    )
    header_index: int | None = None
    if mapping.header_row is not None:
        header_index = mapping.header_row - 1
    elif by_name:
        wanted = {str(mapping.konto).casefold(), str(mapping.naziv).casefold()} - {""}
        for i, row in enumerate(rows):
            cells = {str(c or "").strip().casefold() for c in row}
            if wanted <= cells:
                header_index = i
                break
        if header_index is None:
            raise ValueError(f"Zaglavlje sa kolonama {sorted(wanted)} nije pronađeno. "
                             "Zadajte kolone brojem ili --header-row.")
    header = rows[header_index] if header_index is not None else None
    konto_col, naziv_col = _resolve(mapping.konto, header), _resolve(mapping.naziv, header)

    accounts: dict[str, AnalyticAccount] = {}
    skipped: list[tuple[int, str]] = []
    start = header_index + 1 if header_index is not None else 0
    for number, row in enumerate(rows[start:], start=start + 1):
        if not any(c not in (None, "") for c in row):
            continue
        raw_konto = row[konto_col] if konto_col < len(row) else None
        raw_naziv = row[naziv_col] if naziv_col < len(row) else None
        naziv = str(raw_naziv if raw_naziv is not None else "").strip()
        if isinstance(raw_konto, float) and raw_konto.is_integer():
            raw_konto = int(raw_konto)
        konto = re.sub(r"\s", "", str(raw_konto or ""))
        if not konto.isdigit():
            skipped.append((number, f"konto '{raw_konto}' nije broj"))
            continue
        if len(konto) < mapping.min_digits:
            skipped.append((number, f"konto {konto} ima manje od {mapping.min_digits} cifre (sintetika)"))
            continue
        if not naziv:
            skipped.append((number, f"konto {konto} nema naziv"))
            continue
        if konto in accounts:
            skipped.append((number, f"konto {konto} se ponavlja; zadržan je prvi"))
            continue
        accounts[konto] = AnalyticAccount(konto=konto, naziv=naziv, probni=False, izvor=source or None)
    return ImportResult(accounts=list(accounts.values()), skipped=skipped)


def save_client_plan(path: Path, client_id: str, accounts: list[AnalyticAccount], *, delatnost: str | None,
                     source: str) -> None:
    """Replace one client's plan in the JSON file, keeping the other clients."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"clients": {}}
    data.setdefault("clients", {})
    previous = data["clients"].get(client_id, {})
    data["clients"][client_id] = {
        "delatnost": delatnost or previous.get("delatnost"),
        "izvor": source,
        "konta": [a.model_dump(exclude_none=True) for a in sorted(accounts, key=lambda a: a.konto)],
    }
    if all(not any(a.get("probni") for a in c.get("konta", [])) for c in data["clients"].values()):
        data["status"] = "uvezen"
        data.pop("_napomena", None)
        data.pop("_note", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
