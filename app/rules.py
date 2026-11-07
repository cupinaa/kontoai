"""Keyword rules for obvious cases (fuel, rent, electricity, telecom...)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.text import keyword_pattern, normalize


def _compile(words: list[str]) -> list[re.Pattern[str]]:
    return [keyword_pattern(w) for w in words if normalize(w)]


@dataclass
class Rule:
    id: str
    konto: str
    confidence: float
    keywords: list[str]
    reason: str
    exclude_keywords: list[str] = field(default_factory=list)
    # The same purchase means something else for some businesses: fuel bought by a
    # petrol station is goods for resale, not a fuel expense. Such clients go to the LLM.
    exclude_activity_keywords: list[str] = field(default_factory=list)
    _kw: list[re.Pattern[str]] = field(init=False, repr=False)
    _ex: list[re.Pattern[str]] = field(init=False, repr=False)
    _ex_act: list[re.Pattern[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._kw = _compile(self.keywords)
        self._ex = _compile(self.exclude_keywords)
        self._ex_act = _compile(self.exclude_activity_keywords)

    def match(self, text: str, activity: str) -> str | None:
        """Return the matched keyword, or None. Both arguments must already be normalised."""
        hit = _first(self._kw, text)
        if hit is None or _first(self._ex, text) is not None or _first(self._ex_act, activity) is not None:
            return None
        return hit


def _first(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    keyword: str

    @property
    def explanation(self) -> str:
        return f"Pravilo '{self.rule.id}' (ključna reč: '{self.keyword}'). {self.rule.reason}"


class RuleEngine:
    def __init__(self, rules: list[Rule]):
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> RuleEngine:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Rule(**r) for r in data["rules"]])

    def match(self, text: str, activity: str = "") -> RuleMatch | None:
        """Return the matching rule, or None when nothing matches or rules disagree on the account."""
        norm_text, norm_activity = normalize(text), normalize(activity)
        matches = []
        for rule in self.rules:
            keyword = rule.match(norm_text, norm_activity)
            if keyword is not None:
                matches.append(RuleMatch(rule, keyword))
        if not matches:
            return None
        if len({m.rule.konto for m in matches}) > 1:
            return None  # ambiguous, e.g. "zakup + struja" on one line — let the LLM decide
        return matches[0]
