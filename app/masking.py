"""Masking of identifying data before anything is sent to an external LLM.

Two layers:
1. Known entities from the invoice itself (supplier name, PIB, matični broj,
   contact person) are replaced wherever they appear, case-insensitively.
2. Regex patterns catch identifiers that were not known up front: bank
   accounts / IBAN, JMBG, PIB, matični broj, e-mail, phone numbers and person
   names introduced by markers such as "kontakt:", "n/r", "vozač".

The placeholder -> original mapping stays in memory on our side, so the
explanation returned by the model can be unmasked for the accountant.
"""

from __future__ import annotations

import re
from collections.abc import Callable

_UPPER = "A-ZČĆŠŽĐ"
_LOWER = "a-zčćšžđ"
_NAME = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"

_PERSON_MARKERS = (
    r"kontakt(?:\s+osoba)?|n/r|attn|primalac|vozač|vozac|zaposleni|zaposlenog|zaposlenoj|zaposlena"
    r"|korisnik|ime i prezime|odgovorno lice|direktor|gospodin|gospođa|g-din|g-đa|gdin|gđa"
)
_PERSON_RE = re.compile(
    rf"(?i:\b(?:{_PERSON_MARKERS}))(?:\s*[:\-]\s*|\s+)({_NAME}(?:\s+{_NAME}){{1,2}})"
)

# Order matters: longer / more specific identifiers first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("RACUN", re.compile(r"\bRS\d{2}(?:\s?\d{4}){4}\s?\d{2}\b")),  # IBAN
    ("RACUN", re.compile(r"\b\d{3}-\d{1,13}-\d{2}\b")),  # 160-0000000123456-78
    ("RACUN", re.compile(r"\b\d{18}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("JMBG", re.compile(r"\b\d{13}\b")),
    ("PIB", re.compile(r"\b(?:RS)?\d{9}\b")),
    ("MB", re.compile(r"\b\d{8}\b")),
    ("TELEFON", re.compile(r"(?:\+381|\b0)[\s/-]?\d{2,3}[\s/-]?\d{3,4}[\s/-]?\d{3,4}\b")),
]

_LEGAL_FORMS = re.compile(
    r"\b(?:d\.?\s?o\.?\s?o\.?|a\.?\s?d\.?|o\.?\s?d\.?|k\.?\s?d\.?|pr|szr|str|stur|preduzetnik)(?=\s|$|[.,])",
    re.IGNORECASE,
)


class Masker:
    def __init__(self) -> None:
        self._placeholder_by_value: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}
        self.mapping: dict[str, str] = {}
        self._known: list[tuple[str, str, str]] = []  # (label, variant, canonical value)

    # --- registration of known entities -------------------------------------------------
    def add_known(self, label: str, value: str | None, canonical: str | None = None) -> None:
        if not value or len(value.strip()) < 3:
            return
        self._known.append((label, value.strip(), (canonical or value).strip()))

    def add_company(self, name: str | None) -> None:
        """Register a company name and its variant without the legal form ("Biroprom DOO" -> "Biroprom")."""
        if not name:
            return
        self.add_known("DOBAVLJAC", name)
        core = _LEGAL_FORMS.sub(" ", name.replace('"', " ").replace("„", " ").replace("“", " "))
        core = re.sub(r"\s+", " ", core).strip(" ,.-")
        if len(core) >= 4 and core.lower() != name.strip().lower():
            self.add_known("DOBAVLJAC", core, canonical=name)

    # --- masking ----------------------------------------------------------------------
    def _placeholder(self, label: str, value: str) -> str:
        key = (label, value.casefold())
        if key not in self._placeholder_by_value:
            self._counters[label] = self._counters.get(label, 0) + 1
            placeholder = f"[{label}_{self._counters[label]}]"
            self._placeholder_by_value[key] = placeholder
            self.mapping[placeholder] = value
        return self._placeholder_by_value[key]

    def mask(self, text: str | None) -> str:
        if not text:
            return ""
        result = text
        # Known values first, longest first so "Biroprom Plus DOO" wins over "Biroprom Plus".
        for label, variant, canonical in sorted(self._known, key=lambda k: len(k[1]), reverse=True):
            pattern = re.compile(rf"(?<!\w){re.escape(variant)}(?!\w)", re.IGNORECASE)
            if pattern.search(result):
                result = pattern.sub(self._placeholder(label, canonical), result)

        result = _PERSON_RE.sub(self._replacer("OSOBA", group=1), result)
        for label, pattern in _PATTERNS:
            result = pattern.sub(self._replacer(label), result)
        return result

    def _replacer(self, label: str, group: int = 0) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            value = match.group(group)
            placeholder = self._placeholder(label, value)
            if group == 0:
                return placeholder
            prefix = match.group(0)[: match.start(group) - match.start(0)]
            return prefix + placeholder

        return replace

    def unmask(self, text: str) -> str:
        for placeholder, original in self.mapping.items():
            text = text.replace(placeholder, original)
        return text


def mask_for_llm(
    text: str,
    *,
    supplier_name: str | None = None,
    supplier_pib: str | None = None,
    supplier_registration_number: str | None = None,
    person_names: list[str] | None = None,
) -> tuple[str, Masker]:
    """Convenience wrapper: mask one text using the invoice's known entities."""
    masker = Masker()
    masker.add_company(supplier_name)
    masker.add_known("PIB", supplier_pib)
    masker.add_known("MB", supplier_registration_number)
    for person in person_names or []:
        masker.add_known("OSOBA", person)
    return masker.mask(text), masker
