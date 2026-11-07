"""Per-client history of confirmed postings, stored in SQLite.

Two kinds of evidence, used at different points of the pipeline:

* ITEM history — the same supplier AND the same or a similar item description was confirmed before
  for this client. Strongest signal; used before the keyword rules.
* SUPPLIER history — used only when EVERY confirmed item of that supplier is on the same account and
  there are at least two of them. A supplier that was ever confirmed on two different accounts is never
  used at supplier level. Weaker than the keyword rules, so it is consulted after them.

The demo on 2026-11-07 showed why: a single confirmation of "warehouse rent" from a landlord spread to
the landlord's electricity and office-rent lines. With these rules it cannot.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models import AnalyticSource, HistoryRecord, Source
from app.text import normalize

_SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL,
    item_key        TEXT NOT NULL,
    item_name       TEXT NOT NULL,
    supplier_key    TEXT,
    supplier_name   TEXT,
    supplier_pib    TEXT,
    konto           TEXT NOT NULL,
    konto_name      TEXT,
    suggested_konto TEXT,
    suggested_source TEXT,
    corrected       INTEGER NOT NULL DEFAULT 0,
    confirmed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conf_item ON confirmations (client_id, item_key);
CREATE INDEX IF NOT EXISTS ix_conf_supplier ON confirmations (client_id, supplier_key);
"""

# Columns added after the first release; created on start-up if an older database lacks them.
_ANALYTIC_COLUMNS = {
    "analytic_konto": "TEXT",
    "analytic_name": "TEXT",
    "suggested_analytic": "TEXT",
    "suggested_analytic_source": "TEXT",
    "analytic_corrected": "INTEGER NOT NULL DEFAULT 0",
}

ITEM_MATCH_CONFIDENCE = 0.95
ITEM_SIMILAR_CONFIDENCE = 0.90
ITEM_MATCH_MIXED_CONFIDENCE = 0.85
SUPPLIER_MATCH_CONFIDENCE = 0.85
SUPPLIER_MIN_CONFIRMATIONS = 2
SIMILARITY_THRESHOLD = 0.8

# Words that do not identify WHAT was bought: months, filler words. Tokens with digits
# (dates, quantities, article codes like T-500) are dropped as well.
_IGNORED_WORDS = {
    "januar", "februar", "mart", "april", "maj", "jun", "jul", "avgust", "septembar", "oktobar", "novembar",
    "decembar", "za", "i", "u", "na", "od", "po", "sa", "do", "mesec", "mesecni", "mesecna",
}
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class HistoryMatch:
    konto: str
    confidence: float
    explanation: str


def supplier_key(pib: str | None, name: str | None) -> str | None:
    if pib and pib.strip():
        return f"pib:{pib.strip()}"
    if name and normalize(name):
        return f"name:{normalize(name)}"
    return None


def item_signature(name: str) -> frozenset[str]:
    """Words that describe the item, ignoring months, filler words and anything with digits."""
    return frozenset(
        t for t in normalize(name).split() if len(t) > 1 and t not in _IGNORED_WORDS and not _DIGIT.search(t)
    )


def similarity(a: str, b: str) -> float:
    """1.0 for the same normalised text, otherwise the Jaccard overlap of the item signatures."""
    if normalize(a) == normalize(b):
        return 1.0
    sa, sb = item_signature(a), item_signature(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class HistoryStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(confirmations)")}
            for column, ddl in _ANALYTIC_COLUMNS.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE confirmations ADD COLUMN {column} {ddl}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ write / list

    def add(
        self,
        *,
        client_id: str,
        item_name: str,
        konto: str,
        konto_name: str | None = None,
        supplier_name: str | None = None,
        supplier_pib: str | None = None,
        suggested_konto: str | None = None,
        suggested_source: Source | None = None,
        analytic_konto: str | None = None,
        analytic_name: str | None = None,
        suggested_analytic: str | None = None,
        suggested_analytic_source: AnalyticSource | None = None,
    ) -> HistoryRecord:
        corrected = suggested_konto is not None and suggested_konto != konto
        analytic_corrected = analytic_konto is not None and suggested_analytic not in (None, analytic_konto)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                """INSERT INTO confirmations (client_id, item_key, item_name, supplier_key, supplier_name,
                       supplier_pib, konto, konto_name, suggested_konto, suggested_source, corrected, confirmed_at,
                       analytic_konto, analytic_name, suggested_analytic, suggested_analytic_source,
                       analytic_corrected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    client_id,
                    normalize(item_name),
                    item_name,
                    supplier_key(supplier_pib, supplier_name),
                    supplier_name,
                    supplier_pib,
                    konto,
                    konto_name,
                    suggested_konto,
                    suggested_source.value if suggested_source else None,
                    int(corrected),
                    now,
                    analytic_konto,
                    analytic_name,
                    suggested_analytic,
                    suggested_analytic_source.value if suggested_analytic_source else None,
                    int(analytic_corrected),
                ),
            )
            row = conn.execute("SELECT * FROM confirmations WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _to_record(row)

    def list(self, client_id: str) -> list[HistoryRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM confirmations WHERE client_id = ? ORDER BY id DESC", (client_id,)
            ).fetchall()
        return [_to_record(r) for r in rows]

    # ------------------------------------------------------------------ queries

    def _supplier_rows(self, client_id: str, key: str | None) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            if key is None:
                sql = "SELECT * FROM confirmations WHERE client_id = ? AND supplier_key IS NULL ORDER BY id DESC"
                return conn.execute(sql, (client_id,)).fetchall()
            sql = "SELECT * FROM confirmations WHERE client_id = ? AND supplier_key = ? ORDER BY id DESC"
            return conn.execute(sql, (client_id, key)).fetchall()

    @staticmethod
    def _item_rows(rows: list[sqlite3.Row], item_name: str) -> tuple[list[sqlite3.Row], bool]:
        """Rows for the same item: exact normalised name first, else similar descriptions."""
        exact = [r for r in rows if r["item_key"] == normalize(item_name)]
        if exact:
            return exact, True
        similar = [r for r in rows if similarity(r["item_name"], item_name) >= SIMILARITY_THRESHOLD]
        return similar, False

    def lookup_item(
        self, client_id: str, item_name: str, supplier_pib: str | None, supplier_name: str | None
    ) -> HistoryMatch | None:
        """Same supplier + same or similar item description, confirmed before for this client."""
        rows, exact = self._item_rows(self._supplier_rows(client_id, supplier_key(supplier_pib, supplier_name)),
                                      item_name)
        if not rows:
            return None
        latest = rows[0]["konto"]
        consistent = all(r["konto"] == latest for r in rows)
        confidence = (ITEM_MATCH_CONFIDENCE if exact else ITEM_SIMILAR_CONFIDENCE) if consistent \
            else ITEM_MATCH_MIXED_CONFIDENCE
        what = "Ista stavka" if exact else f"Slična stavka („{rows[0]['item_name']}”)"
        return HistoryMatch(
            konto=latest,
            confidence=confidence,
            explanation=(
                f"{what} istog dobavljača je kod ovog klijenta ranije potvrđena na konto {latest} "
                f"(broj potvrda: {len(rows)}"
                f"{'' if consistent else '; ranije je bilo i drugačijih kontiranja, uzeto je poslednje'})."
            ),
        )

    def lookup_supplier(self, client_id: str, supplier_pib: str | None, supplier_name: str | None) -> HistoryMatch | None:
        """Only if ALL confirmations of this supplier are on one account and there are at least two."""
        key = supplier_key(supplier_pib, supplier_name)
        if key is None:
            return None
        rows = self._supplier_rows(client_id, key)
        kontos = {r["konto"] for r in rows}
        if len(rows) < SUPPLIER_MIN_CONFIRMATIONS or len(kontos) != 1:
            return None  # too little evidence, or the supplier was ever booked to different accounts
        konto = kontos.pop()
        return HistoryMatch(
            konto=konto,
            confidence=SUPPLIER_MATCH_CONFIDENCE,
            explanation=(f"Sve potvrđene stavke ovog dobavljača ({len(rows)}) su kod klijenta na kontu {konto}."),
        )

    def lookup(
        self, client_id: str, item_name: str, supplier_pib: str | None, supplier_name: str | None
    ) -> HistoryMatch | None:
        """Item history, else supplier history (the classifier puts the keyword rules in between)."""
        return (self.lookup_item(client_id, item_name, supplier_pib, supplier_name)
                or self.lookup_supplier(client_id, supplier_pib, supplier_name))

    def lookup_analytic_item(
        self, client_id: str, item_name: str, supplier_pib: str | None, supplier_name: str | None, konto: str
    ) -> HistoryMatch | None:
        """Analytic account of the same/similar item of the same supplier, confirmed BELOW `konto` only."""
        rows = [r for r in self._supplier_rows(client_id, supplier_key(supplier_pib, supplier_name))
                if r["konto"] == konto and r["analytic_konto"] and r["analytic_konto"].startswith(konto)]
        rows, exact = self._item_rows(rows, item_name)
        if not rows:
            return None
        latest = rows[0]["analytic_konto"]
        consistent = all(r["analytic_konto"] == latest for r in rows)
        confidence = (ITEM_MATCH_CONFIDENCE if exact else ITEM_SIMILAR_CONFIDENCE) if consistent \
            else ITEM_MATCH_MIXED_CONFIDENCE
        what = "Ista stavka" if exact else f"Slična stavka („{rows[0]['item_name']}”)"
        return HistoryMatch(
            konto=latest,
            confidence=confidence,
            explanation=(f"{what} istog dobavljača je kod ovog klijenta ranije potvrđena na analitički konto "
                         f"{latest} (broj potvrda: {len(rows)})."),
        )

    def lookup_analytic_supplier(
        self, client_id: str, supplier_pib: str | None, supplier_name: str | None, konto: str
    ) -> HistoryMatch | None:
        """Only if ALL analytic confirmations of the supplier are one account (≥2) and it lies below `konto`."""
        key = supplier_key(supplier_pib, supplier_name)
        if key is None:
            return None
        rows = [r for r in self._supplier_rows(client_id, key) if r["analytic_konto"]]
        analytics = {r["analytic_konto"] for r in rows}
        if len(rows) < SUPPLIER_MIN_CONFIRMATIONS or len(analytics) != 1:
            return None
        analytic = analytics.pop()
        if not analytic.startswith(konto):
            return None  # never suggest an analytic account below a different synthetic account
        return HistoryMatch(
            konto=analytic,
            confidence=SUPPLIER_MATCH_CONFIDENCE,
            explanation=(f"Sve potvrđene stavke ovog dobavljača ({len(rows)}) su na analitičkom kontu {analytic}."),
        )

    def lookup_analytic(
        self, client_id: str, item_name: str, supplier_pib: str | None, supplier_name: str | None, konto: str
    ) -> HistoryMatch | None:
        return (self.lookup_analytic_item(client_id, item_name, supplier_pib, supplier_name, konto)
                or self.lookup_analytic_supplier(client_id, supplier_pib, supplier_name, konto))


def _to_record(row: sqlite3.Row) -> HistoryRecord:
    return HistoryRecord(
        id=row["id"],
        client_id=row["client_id"],
        item_name=row["item_name"],
        supplier_name=row["supplier_name"],
        supplier_pib=row["supplier_pib"],
        konto=row["konto"],
        konto_name=row["konto_name"],
        suggested_konto=row["suggested_konto"],
        suggested_source=Source(row["suggested_source"]) if row["suggested_source"] else None,
        corrected=bool(row["corrected"]),
        analytic_konto=row["analytic_konto"],
        analytic_name=row["analytic_name"],
        suggested_analytic=row["suggested_analytic"],
        suggested_analytic_source=(
            AnalyticSource(row["suggested_analytic_source"]) if row["suggested_analytic_source"] else None
        ),
        analytic_corrected=bool(row["analytic_corrected"]),
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
    )
