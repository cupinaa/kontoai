"""Turn the table rows of an accounting software's "Konta: Lista" PDF into analytic accounts.

The PDF itself is confidential client material and never belongs in the repository; this module only
knows its column layout:

    Konto | Naziv | Analitika (partner) | Aktuelan | Važi od 2014 | AOP | Broj stavki TG | Broj stavki PG

Only accounts that are current (Aktuelan = Da) and belong to the classes relevant for incoming invoices
are kept: 01, 02 (intangible and fixed assets), 10 (materials and small inventory), 13 (goods) and 5
(expenses). Banks, loans, equity and partner accounts are never imported.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.analytic import AnalyticAccount

COLUMNS = ("konto", "naziv", "analitika", "aktuelan", "vazi", "aop", "tg", "pg")
RELEVANT_PREFIXES = ("01", "02", "10", "13", "5")
_PREFIX = re.compile(r"^\s*\d{4}\s*-\s*")  # "2014 - " / "2022 - " in front of the name
_LEGAL_FORM = re.compile(r"\b(d\.?o\.?o|a\.?d|szr|str|pr|ltd|gmbh)\b\.?", re.IGNORECASE)


@dataclass
class ParsedRow:
    konto: str
    naziv: str
    aktuelan: bool
    tg: int | None
    pg: int | None
    page: int
    wrapped: bool = False  # the name spanned more than one line or continued on the next row/page
    notes: list[str] = field(default_factory=list)


@dataclass
class PdfImport:
    accounts: list[AnalyticAccount]
    parents: dict[str, str]  # 3-digit account -> its name in the client's plan
    flagged: list[tuple[str, str, str]]  # (konto, naziv, reason)
    skipped: Counter  # reason -> count (not current, other class, synthetic level, ...)


def clean_name(text: str | None) -> str:
    text = " ".join(str(text or "").split())  # joins names wrapped inside one cell
    return _PREFIX.sub("", text).strip()


def _number(value) -> int | None:
    text = re.sub(r"[\s.]", "", str(value or ""))
    return int(text) if text.isdigit() else None


def relevant(konto: str) -> bool:
    return konto.startswith(RELEVANT_PREFIXES)


def collect_rows(pages: list[list[list]]) -> list[ParsedRow]:
    """pages: for every PDF page, its table rows (lists of cell values, columns as in COLUMNS).

    A row without an account number continues the previous row's name (a name wrapped across rows or
    across a page break), so it is appended to that account instead of becoming an account of its own.
    """
    rows: list[ParsedRow] = []
    for page_no, table in enumerate(pages, start=1):
        for raw in table:
            cells = [("" if c is None else str(c)) for c in raw] + [""] * len(COLUMNS)
            konto = re.sub(r"\s", "", cells[0])
            if konto.casefold() == "konto":
                continue  # header repeated on every page
            naziv_raw = cells[1]
            if not konto:
                if rows and naziv_raw.strip():
                    rows[-1].naziv = clean_name(f"{rows[-1].naziv} {naziv_raw}")
                    rows[-1].wrapped = True
                    rows[-1].notes.append(f"naziv nastavljen u sledećem redu (str. {page_no})")
                continue
            if not konto.isdigit():
                continue
            rows.append(ParsedRow(
                konto=konto, naziv=clean_name(naziv_raw), aktuelan=cells[3].strip().casefold() == "da",
                tg=_number(cells[6]), pg=_number(cells[7]), page=page_no, wrapped="\n" in naziv_raw,
            ))
    return rows


def build_plan(rows: list[ParsedRow], source: str) -> PdfImport:
    skipped: Counter = Counter()
    parents: dict[str, str] = {}
    accounts: dict[str, AnalyticAccount] = {}
    flagged: list[tuple[str, str, str]] = []
    for row in rows:
        if not relevant(row.konto):
            skipped["druga klasa (banke, krediti, kapital, partneri…)"] += 1
            continue
        if not row.aktuelan:
            skipped["Aktuelan = Ne"] += 1
            continue
        if len(row.konto) <= 3:
            parents.setdefault(row.konto, row.naziv)
            skipped["sintetički ili viši nivo (do 3 cifre)"] += 1
            continue
        reasons = list(row.notes)
        if row.wrapped and not row.notes:
            reasons.append("naziv prelomljen u više redova")
        if not row.naziv:
            reasons.append("prazan naziv")
        elif len(row.naziv) < 4:
            reasons.append("vrlo kratak naziv")
        if row.naziv and _LEGAL_FORM.search(row.naziv):
            reasons.append("naziv možda sadrži ime firme ili osobe")
        if row.tg is None or row.pg is None:
            reasons.append("broj stavki nije broj")
        if len(row.konto) > 5:
            reasons.append(f"konto ima {len(row.konto)} cifara")
        if row.konto in accounts:
            flagged.append((row.konto, row.naziv, "konto se ponavlja; zadržan je prvi"))
            continue
        for reason in reasons:
            flagged.append((row.konto, row.naziv, reason))
        if not row.naziv:
            continue
        accounts[row.konto] = AnalyticAccount(
            konto=row.konto, naziv=row.naziv, izvor=source, tg=row.tg or 0, pg=row.pg or 0,
        )
    return PdfImport(accounts=sorted(accounts.values(), key=lambda a: a.konto), parents=parents,
                     flagged=flagged, skipped=skipped)
