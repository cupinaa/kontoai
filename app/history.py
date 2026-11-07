"""Per-client history of confirmed postings, stored in SQLite.

Lookups, in order of strength:
1. the same item (normalised name) was confirmed before for this client;
2. the same supplier (PIB, or normalised name) was consistently confirmed to one account.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
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
ITEM_MATCH_MIXED_CONFIDENCE = 0.85
SUPPLIER_MATCH_CONFIDENCE = 0.85
SUPPLIER_SINGLE_CONFIDENCE = 0.80
SUPPLIER_MIN_SHARE = 0.8


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

    def lookup(
        self, client_id: str, item_name: str, supplier_pib: str | None, supplier_name: str | None
    ) -> HistoryMatch | None:
        with closing(self._connect()) as conn:
            item_rows = conn.execute(
                "SELECT konto FROM confirmations WHERE client_id = ? AND item_key = ? ORDER BY id DESC",
                (client_id, normalize(item_name)),
            ).fetchall()
            if item_rows:
                latest = item_rows[0]["konto"]
                consistent = all(r["konto"] == latest for r in item_rows)
                n = len(item_rows)
                return HistoryMatch(
                    konto=latest,
                    confidence=ITEM_MATCH_CONFIDENCE if consistent else ITEM_MATCH_MIXED_CONFIDENCE,
                    explanation=(
                        f"Ista stavka je kod ovog klijenta ranije potvrđena na konto {latest} "
                        f"(broj potvrda: {n}"
                        f"{'' if consistent else '; ranije je bilo i drugačijih kontiranja, uzeto je poslednje'})."
                    ),
                )

            key = supplier_key(supplier_pib, supplier_name)
            if key is None:
                return None
            supplier_rows = conn.execute(
                "SELECT konto FROM confirmations WHERE client_id = ? AND supplier_key = ?", (client_id, key)
            ).fetchall()

        if not supplier_rows:
            return None
        counts = Counter(r["konto"] for r in supplier_rows)
        konto, top = counts.most_common(1)[0]
        total = len(supplier_rows)
        share = top / total
        if share < SUPPLIER_MIN_SHARE:
            return None  # supplier is booked to different accounts; not a reliable signal
        confidence = SUPPLIER_SINGLE_CONFIDENCE if total == 1 else SUPPLIER_MATCH_CONFIDENCE * share
        return HistoryMatch(
            konto=konto,
            confidence=round(confidence, 3),
            explanation=(
                f"Stavke ovog dobavljača su kod klijenta ranije potvrđene na konto {konto} "
                f"({top} od {total} potvrda)."
            ),
        )


    def lookup_analytic(
        self,
        client_id: str,
        item_name: str,
        supplier_pib: str | None,
        supplier_name: str | None,
        konto: str,
    ) -> HistoryMatch | None:
        """Confirmed analytic account for the same item, else the same supplier, below `konto`."""
        with closing(self._connect()) as conn:
            item_rows = conn.execute(
                """SELECT analytic_konto FROM confirmations
                   WHERE client_id = ? AND item_key = ? AND konto = ? AND analytic_konto IS NOT NULL
                   ORDER BY id DESC""",
                (client_id, normalize(item_name), konto),
            ).fetchall()
            key = supplier_key(supplier_pib, supplier_name)
            supplier_rows = []
            if not item_rows and key is not None:
                supplier_rows = conn.execute(
                    """SELECT analytic_konto FROM confirmations
                       WHERE client_id = ? AND supplier_key = ? AND konto = ? AND analytic_konto IS NOT NULL""",
                    (client_id, key, konto),
                ).fetchall()

        if item_rows:
            latest = item_rows[0]["analytic_konto"]
            consistent = all(r["analytic_konto"] == latest for r in item_rows)
            return HistoryMatch(
                konto=latest,
                confidence=ITEM_MATCH_CONFIDENCE if consistent else ITEM_MATCH_MIXED_CONFIDENCE,
                explanation=(f"Ista stavka je kod ovog klijenta ranije potvrđena na analitički konto {latest} "
                             f"(broj potvrda: {len(item_rows)})."),
            )
        if not supplier_rows:
            return None
        counts = Counter(r["analytic_konto"] for r in supplier_rows)
        analytic, top = counts.most_common(1)[0]
        total = len(supplier_rows)
        if top / total < SUPPLIER_MIN_SHARE:
            return None
        confidence = SUPPLIER_SINGLE_CONFIDENCE if total == 1 else SUPPLIER_MATCH_CONFIDENCE * top / total
        return HistoryMatch(
            konto=analytic,
            confidence=round(confidence, 3),
            explanation=(f"Stavke ovog dobavljača na kontu {konto} su ranije potvrđene na analitički konto "
                         f"{analytic} ({top} od {total} potvrda)."),
        )


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
