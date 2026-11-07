"""The allowed chart of accounts (kontni okvir). Every suggestion must come from this list."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Account


class ChartOfAccounts:
    def __init__(self, accounts: list[Account], source: str = "", verified: bool = False):
        if not accounts:
            raise ValueError("Chart of accounts is empty")
        self._by_code = {a.konto: a for a in accounts}
        self.source = source
        self.verified = verified

    @classmethod
    def load(cls, path: Path) -> ChartOfAccounts:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        accounts = [Account.model_validate(a) for a in data["konta"]]
        return cls(accounts, source=data.get("izvor", ""), verified=bool(data.get("verifikovano")))

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and code in self._by_code

    def __len__(self) -> int:
        return len(self._by_code)

    def get(self, code: str) -> Account | None:
        return self._by_code.get(code)

    def name(self, code: str) -> str | None:
        account = self._by_code.get(code)
        return account.naziv if account else None

    @property
    def codes(self) -> list[str]:
        return list(self._by_code)

    @property
    def accounts(self) -> list[Account]:
        return list(self._by_code.values())
