"""Run the evaluation dataset through the full pipeline and report accuracy.

Usage:
    python scripts/evaluate.py --dry-run       # plan only: counts calls and tokens, sends NOTHING to the API
    python scripts/evaluate.py                 # uses Gemini if GEMINI_API_KEY is set
    python scripts/evaluate.py --no-llm        # history + rules only
    python scripts/evaluate.py --max-calls 40  # hard cap on real API requests (default 40, retries count)
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
from app.llm.base import (  # noqa: E402
    SYSTEM_PROMPT,
    CallBudget,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMSuggestion,
    build_user_prompt,
)
from app.llm.gemini import GeminiProvider  # noqa: E402
from app.models import InvoiceItem, Source  # noqa: E402
from app.service import build_classifier  # noqa: E402

DEFAULT_MAX_CALLS = 40

# Paid-tier prices in USD per 1M tokens (input, output incl. thinking), from
# https://ai.google.dev/gemini-api/docs/pricing as of 2026-11-07. Valid through 2026-12-31; check before relying on it.
PRICES_USD_PER_1M = {
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}


def estimated_cost(model: str, usage: dict) -> float | None:
    if model not in PRICES_USD_PER_1M:
        return None
    price_in, price_out = PRICES_USD_PER_1M[model]
    output = usage["output_tokens"] + usage["thinking_tokens"]
    return (usage["prompt_tokens"] * price_in + output * price_out) / 1_000_000

SOURCE_LABELS = {Source.HISTORY: "history", Source.RULE: "rules", Source.LLM: "LLM", Source.NONE: "undecided"}
BUDGET_MARKER = "dostignut limit"  # text of CallBudgetExceeded, surfaced in the item explanation
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


class DryRunProvider(LLMProvider):
    """Stands in for the real model: records what would be sent and never touches the network."""

    name = "dry-run"

    def __init__(self, model: str):
        self.model = model
        self.requests: list[LLMRequest] = []

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        self.requests.append(request)
        raise LLMError("dry run — no API call sent")

    def estimated_prompt_tokens(self) -> int:
        # ~4 characters per token is a conservative rule of thumb for Latin-script text.
        return sum((len(SYSTEM_PROMPT) + len(build_user_prompt(r))) // 4 for r in self.requests)


@dataclass
class RunInfo:
    model: str | None
    budget: CallBudget | None = None
    gemini: GeminiProvider | None = None
    dry_run: DryRunProvider | None = None
    cache_hits: int = 0


def run(
    dataset_path: Path,
    use_llm: bool,
    rpm: float | None,
    use_cache: bool,
    max_calls: int = DEFAULT_MAX_CALLS,
    dry_run: bool = False,
) -> tuple[list[Row], RunInfo]:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(get_settings(), db_path=Path(tmp) / "eval.db")
        info = RunInfo(model=settings.gemini_model if use_llm else None)
        llm: LLMProvider | None = None
        if use_llm and dry_run:
            llm = info.dry_run = DryRunProvider(settings.gemini_model)
        elif use_llm:
            info.budget = CallBudget(max_calls)
            llm = info.gemini = GeminiProvider(
                api_key=settings.gemini_api_key or "", model=settings.gemini_model, budget=info.budget
            )
        classifier = build_classifier(settings, llm=llm, use_llm=False)
        throttle = cache = None
        if classifier.llm is not None:
            if rpm and not dry_run:
                throttle = classifier.llm = ThrottledProvider(classifier.llm, rpm)
            if use_cache:
                cache = classifier.llm = CachedProvider(classifier.llm, CACHE_DIR)
        for seed in data["history_seed"]:
            classifier.history.add(**seed, konto_name=classifier.chart.name(seed["konto"]))

        rows: list[Row] = []
        announced = False
        excluded = [e for e in data["items"] if e.get("exclude_from_eval")]
        if excluded:
            print(f"Skipping {len(excluded)} item(s) excluded from evaluation (e.g. pending correction): "
                  f"{', '.join(str(e['id']) for e in excluded)}", file=sys.stderr)
        for entry in (e for e in data["items"] if not e.get("exclude_from_eval")):
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
            info.cache_hits += rows[-1].cached
            if BUDGET_MARKER in suggestion.explanation and not announced:
                announced = True
                print(f"!!! Reached --max-calls {max_calls}: no further API calls will be sent. "
                      f"Remaining LLM items are flagged for review.", file=sys.stderr)
    return rows, info


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


def budget_skipped(rows: list[Row]) -> list[Row]:
    return [r for r in rows if BUDGET_MARKER in r.explanation]


def render(rows: list[Row], info: RunInfo, threshold: float) -> str:
    model = info.model
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
    if info.gemini is not None and info.budget is not None:
        u = info.gemini.usage
        out += [
            "",
            "## API usage",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| API requests sent (incl. retries) | {info.budget.used} of max {info.budget.max_calls} |",
            f"| Successful responses | {u['calls']} |",
            f"| Answers served from cache | {info.cache_hits} |",
            f"| Prompt tokens | {u['prompt_tokens']:,} |",
            f"| Output tokens | {u['output_tokens']:,} |",
            f"| Thinking tokens | {u['thinking_tokens']:,} |",
        ]
        cost = estimated_cost(info.gemini.model, u)
        if cost is not None:
            out.append(f"| Estimated cost (paid tier, prices of 2026-11-07) | ${cost:.3f} |")
        skipped = budget_skipped(rows)
        if skipped:
            out += ["", f"**Stopped at the call limit:** {len(skipped)} items were not sent to the API because "
                        f"`--max-calls {info.budget.max_calls}` was reached."]

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
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help=f"hard cap on real API requests incl. retries (default {DEFAULT_MAX_CALLS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan only: report how many API calls would be needed; sends nothing")
    args = parser.parse_args()

    settings = get_settings()
    use_llm = not args.no_llm
    if use_llm and not settings.gemini_api_key and not args.dry_run:
        print("GEMINI_API_KEY is not set; running without the LLM step.", file=sys.stderr)
        use_llm = False

    rows, info = run(args.dataset, use_llm, args.rpm, use_cache=not args.no_cache,
                     max_calls=args.max_calls, dry_run=args.dry_run)

    if args.dry_run:
        planner = info.dry_run
        needed = len(planner.requests) if planner else 0
        print("DRY RUN — no API calls were sent.")
        print(f"Model: {settings.gemini_model}")
        print(f"Items: {len(rows)}; resolved by history/rules: {sum(r.source is not Source.LLM for r in rows)}")
        print(f"LLM answers already in cache: {info.cache_hits}")
        print(f"API calls needed (without retries): {needed}  (limit --max-calls {args.max_calls})")
        if planner:
            print(f"Estimated prompt tokens in total: ~{planner.estimated_prompt_tokens():,}")
        return

    args.output.write_text(render(rows, info, settings.review_threshold), encoding="utf-8")
    model = info.model

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
    if info.budget is not None and info.gemini is not None:
        u = info.gemini.usage
        print(f"API requests sent: {info.budget.used} of max {info.budget.max_calls}; cache hits: {info.cache_hits}")
        print(f"Tokens: prompt {u['prompt_tokens']:,}, output {u['output_tokens']:,}, "
              f"thinking {u['thinking_tokens']:,}")
        skipped = budget_skipped(rows)
        if skipped:
            print(f"!!! STOPPED: reached --max-calls {info.budget.max_calls}. "
                  f"{len(skipped)} items were NOT sent to the API and are flagged for review.")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
