"""Text normalisation shared by rules and history lookups.

Serbian invoices mix Latin and Cyrillic script, with and without diacritics
("Električna", "Elektricna", "Електрична"). Everything is folded to lowercase
ASCII Latin so that the same item always produces the same key.
"""

from __future__ import annotations

import re

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "dj", "е": "e", "ж": "z",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "c", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "c", "џ": "dz", "ш": "s",
}
_LATIN = {"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"}

_TRANSLATE = str.maketrans({**_CYRILLIC, **_LATIN})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str | None) -> str:
    """Lowercase, transliterate Cyrillic, strip diacritics and punctuation, collapse spaces."""
    if not text:
        return ""
    folded = text.lower().translate(_TRANSLATE)
    return _NON_ALNUM.sub(" ", folded).strip()


def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Match a normalised keyword at the start of a word (so stems like 'zakup' hit 'zakupnina')."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize(keyword)))
