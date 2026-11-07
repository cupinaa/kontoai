"""Run the evaluation dataset through the full pipeline and report accuracy.

Usage:
    python scripts/evaluate.py                 # uses Gemini if GEMINI_API_KEY is set
    python scripts/evaluate.py --no-llm        # history + rules only
    python scripts/evaluate.py --rpm 4         # stay under a free-tier quota of 5 requests/minute
    python scripts/evaluate.py --output eval_results.md

History is seeded into a throw-away SQLite database, so the real one is never touched.
Successful LLM answers are cached in .eval_cache/ (keyed by model + masked request),
so re-running the evaluation does not spend API quota again. Use --no-cache to bypass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.classifier import ItemContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.base import LLMProvider, LLMRequest, LLMSuggestion  # noqa: E402
from app.models import InvoiceItem, Source  # noqa: E402
from app.service import build_classifier  # noqa: E402

SOURCE_LABELS = {Source.HISTORY: "history", Source.RULE: "rules", Source.LLM: "LLM", Source.NONE: "undecided"}
CATEGORY_LABELS = {
    "ambiguous": "ambiguous description",
    "abbreviation": "invoice abbreviation",
    "activity": "depends on client activity",
    "no_rule": "not covered by any rule",
}
CACHE_DIR = ROOT / ".eval_cache"


@dataclass
class Row:
    id: int
    name: str
    difficulty: str
    category: str | None
    expected: str
    predicted: str | None
    source: Source
    confidence: float
    needs_review: bool
    seconds: float
    explanation: str
    cached: bool = False

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected

    @property
    def silent_error(self) -> bool:
        """Wrong account that was NOT flagged for review — the dangerous case."""
        return not self.correct and not self.needs_review


class ThrottledProvider(LLMProvider):
    """Spaces out LLM calls to respect a requests-per-minute quota (e.g. the Gemini free tier).

    Time spent waiting for the quota is recorded so it can be excluded from latency numbers.
    """

    def __init__(self, inner: LLMProvider, rpm: float):
        self.inner, self.interval = inner, 60.0 / rpm
        self.name, self.model = inner.name, inner.model
        self._last = 0.0
        self.waited = 0.0

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
            self.waited += wait
        try:
            return self.inner.suggest(request)
        finally:
            self._last = time.monotonic()


class CachedProvider(LLMProvider):
    """Caches successful answers on disk so repeated evaluation runs do not spend quota."""

    def __init__(self, inner: LLMProvider, cache_dir: Path):
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.dir = cache_dir / inner.model
        self.dir.mkdir(parents=True, exist_ok=True)
        self.last_hit = False

    def _path(self, request: LLMRequest) -> Path:
        digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()[:24]
        return self.dir / f"{digest}.json"

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        path = self._path(request)
        if path.exists():
            self.last_hit = True
            return LLMSuggestion.model_validate_json(path.read_text(encoding="utf-8"))
        self.last_hit = False
        answer = self.inner.suggest(request)
        path.write_text(answer.model_dump_json(), encoding="utf-8")
        return answer


def run(dataset_path: Path, use_llm: bool, rpm: float | None, use_cache: bool) -> tuple[list[Row], str | None]:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(get_settings(), db_path=Path(tmp) / "eval.db")
        classifier = build_classifier(settings, use_llm=use_llm)
        throttle = cache = None
        if classifier.llm is not None:
            if rpm:
                throttle = classifier.llm = ThrottledProvider(classifier.llm, rpm)
            if use_cache:
                cache = classifier.llm = CachedProvider(classifier.llm, CACHE_DIR)
        for seed in data["history_seed"]:
            classifier.history.add(**seed, konto_name=classifier.chart.name(seed["konto"]))

        rows: list[Row] = []
        for entry in data["items"]:
            item = InvoiceItem(
                name=entry["name"],
                quantity=entry.get("quantity"),
                unit=entry.get("unit"),
                amount=entry.get("amount"),
                supplier_name=entry.get("supplier_name"),
                supplier_pib=entry.get("supplier_pib"),
            )
            ctx = ItemContext(
                client_id=entry["client_id"], client_activity=data["clients"][entry["client_id"]], item=item
            )
            if cache:
                cache.last_hit = False
            waited_before = throttle.waited if throttle else 0.0
            started = time.perf_counter()
            suggestion = classifier.classify(ctx)
            elapsed = time.perf_counter() - started - ((throttle.waited - waited_before) if throttle else 0.0)
            rows.append(
                Row(
                    id=entry["id"],
                    name=entry["name"],
                    difficulty=entry.get("difficulty", "easy"),
                    category=entry.get("category"),
                    expected=entry["expected_konto"],
                    predicted=suggestion.konto,
                    source=suggestion.source,
                    confidence=suggestion.confidence,
                    needs_review=suggestion.needs_review,
                    seconds=elapsed,
                    explanation=suggestion.explanation,
                    cached=bool(cache and cache.last_hit and suggestion.source is Source.LLM),
                )
            )
        model = classifier.llm.model if classifier.llm else None
    return rows, model


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def avg_ms(rows: list[Row]) -> str:
    timed = [r for r in rows if not r.cached]
    return f"{1000 * sum(r.seconds for r in timed) / len(timed):.1f} ms" if timed else "cached"


def summary_row(label: str, group: list[Row]) -> str:
    ok = sum(r.correct for r in group)
    flagged = sum(r.needs_review for r in group)
    silent = sum(r.silent_error for r in group)
    return f"| {label} | {len(group)} | {ok} | **{pct(ok, len(group))}** | {flagged} | {silent} | {avg_ms(group)} |"


TABLE_HEAD = [
    "| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |",
    "|---|---|---|---|---|---|---|",
]


def render(rows: list[Row], model: str | None, threshold: float) -> str:
    easy = [r for r in rows if r.difficulty == "easy"]
    hard = [r for r in rows if r.difficulty == "hard"]
    llm_errors = [r for r in rows if r.source is Source.LLM and r.predicted is None]
    by_source: dict[Source, list[Row]] = defaultdict(list)
    for r in rows:
        by_source[r.source].append(r)

    out = [
        "# KontoAI — evaluation results",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- LLM: {f'Gemini `{model}`' if model else 'not used (history + rules only)'}",
        f"- Items: {len(rows)} ({len(easy)} easy, {len(hard)} hard) from `data/eval/dataset.json`",
        f"- Review threshold: confidence < {threshold}",
        "",
        "> [!WARNING]",
        "> **This dataset is synthetic and its expected accounts are not verified.** The items, the expected "
        "accounts and the keyword rules were all written by the same author, so a high score here is **not** a "
        "real accuracy measure — in particular, the 100% on easy history/rule items is true by construction. "
        "The expected accounts are pending verification by an accountant. A real measurement needs invoices "
        "and postings from an accounting office.",
        "",
        "**Silent errors** are wrong accounts that were *not* flagged for review — the outcome that matters "
        "most, because nobody looks at them. A wrong suggestion that is flagged costs the accountant a click; "
        "a silent one ends up in the books.",
        "",
        "## Easy vs. hard items",
        "",
        *TABLE_HEAD,
        summary_row("Easy (clear descriptions)", easy),
        summary_row("Hard (ambiguous, abbreviations, activity-dependent, no rule)", hard),
        summary_row("**All**", rows),
        "",
    ]
    if hard:
        out += ["### Hard items by category", "", *TABLE_HEAD]
        for category, label in CATEGORY_LABELS.items():
            group = [r for r in hard if r.category == category]
            if group:
                out.append(summary_row(label, group))
        out.append("")

    out += ["## By decision source", "", *TABLE_HEAD]
    for source in (Source.HISTORY, Source.RULE, Source.LLM, Source.NONE):
        if by_source.get(source):
            out.append(summary_row(SOURCE_LABELS[source], by_source[source]))
    if llm_errors:
        out += ["", f"LLM calls that returned no answer (API error, e.g. quota or overload): {len(llm_errors)}. "
                    "These items are counted as wrong but are flagged for review."]
    if any(r.cached for r in rows):
        out += ["", "Some LLM answers were served from the local cache; their time is excluded from the averages."]

    out += [
        "",
        "## Per item",
        "",
        "| # | Item | Difficulty | Expected | Predicted | Source | Confidence | Review | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        difficulty = r.difficulty + (f" ({CATEGORY_LABELS[r.category]})" if r.category else "")
        result = "✅" if r.correct else ("⚠️ flagged" if r.needs_review else "❌ silent")
        out.append(
            f"| {r.id} | {r.name} | {difficulty} | {r.expected} | {r.predicted or '—'} | "
            f"{SOURCE_LABELS[r.source]} | {r.confidence:.2f} | {'yes' if r.needs_review else ''} | {result} |"
        )

    wrong = [r for r in rows if not r.correct]
    if wrong:
        out += ["", "## Mismatches and undecided items", ""]
        out += [
            f"- **#{r.id} {r.name}** — expected {r.expected}, got {r.predicted or 'no suggestion'}"
            f"{' (flagged)' if r.needs_review else ' (NOT flagged)'}: {r.explanation}"
            for r in wrong
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "eval" / "dataset.json")
    parser.add_argument("--output", type=Path, default=ROOT / "eval_results.md")
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM step even if a key is configured")
    parser.add_argument("--rpm", type=float, default=None,
                        help="max LLM requests per minute (e.g. 4 for the Gemini free tier); waits are not timed")
    parser.add_argument("--no-cache", action="store_true", help="do not read or write .eval_cache/")
    args = parser.parse_args()

    settings = get_settings()
    use_llm = not args.no_llm
    if use_llm and not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set; running without the LLM step.", file=sys.stderr)
        use_llm = False

    rows, model = run(args.dataset, use_llm, args.rpm, use_cache=not args.no_cache)
    args.output.write_text(render(rows, model, settings.review_threshold), encoding="utf-8")

    def line(label: str, group: list[Row]) -> str:
        ok = sum(r.correct for r in group)
        return (f"  {label:<10} {pct(ok, len(group)):>7}  ({ok}/{len(group)}), "
                f"flagged {sum(r.needs_review for r in group)}, silent errors {sum(r.silent_error for r in group)}")

    print(f"Model: {model or 'none'}")
    print(line("all", rows))
    print(line("easy", [r for r in rows if r.difficulty == "easy"]))
    print(line("hard", [r for r in rows if r.difficulty == "hard"]))
    for source in (Source.HISTORY, Source.RULE, Source.LLM, Source.NONE):
        group = [r for r in rows if r.source == source]
        if group:
            print(line(SOURCE_LABELS[source], group))
    print(f"LLM errors: {sum(r.source is Source.LLM and r.predicted is None for r in rows)}")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
