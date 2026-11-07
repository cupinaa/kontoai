"""Run the evaluation dataset through the full pipeline and report accuracy.

Usage:
    python scripts/evaluate.py                 # uses Gemini if GEMINI_API_KEY is set
    python scripts/evaluate.py --no-llm        # history + rules only
    python scripts/evaluate.py --output eval_results.md

History is seeded into a throw-away SQLite database, so the real one is never touched.
"""

from __future__ import annotations

import argparse
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
from app.models import InvoiceItem, Source  # noqa: E402
from app.service import build_classifier  # noqa: E402

SOURCE_LABELS = {Source.HISTORY: "history", Source.RULE: "rules", Source.LLM: "LLM", Source.NONE: "undecided"}


@dataclass
class Row:
    id: int
    name: str
    expected: str
    predicted: str | None
    source: Source
    confidence: float
    needs_review: bool
    seconds: float
    explanation: str

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


def run(dataset_path: Path, use_llm: bool) -> tuple[list[Row], str | None]:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(get_settings(), db_path=Path(tmp) / "eval.db")
        classifier = build_classifier(settings, use_llm=use_llm)
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
            started = time.perf_counter()
            suggestion = classifier.classify(ctx)
            elapsed = time.perf_counter() - started
            rows.append(
                Row(
                    id=entry["id"],
                    name=entry["name"],
                    expected=entry["expected_konto"],
                    predicted=suggestion.konto,
                    source=suggestion.source,
                    confidence=suggestion.confidence,
                    needs_review=suggestion.needs_review,
                    seconds=elapsed,
                    explanation=suggestion.explanation,
                )
            )
        model = classifier.llm.model if classifier.llm else None
    return rows, model


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def render(rows: list[Row], model: str | None, threshold: float) -> str:
    total = len(rows)
    correct = sum(r.correct for r in rows)
    flagged = [r for r in rows if r.needs_review]
    auto = [r for r in rows if not r.needs_review]
    by_source: dict[Source, list[Row]] = defaultdict(list)
    for r in rows:
        by_source[r.source].append(r)

    out = [
        "# KontoAI — evaluation results",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- LLM: {f'Gemini `{model}`' if model else 'not used (history + rules only)'}",
        f"- Items: {total} (fictional dataset `data/eval/dataset.json`)",
        f"- Review threshold: confidence < {threshold}",
        "",
        "> **The expected accounts in the dataset are not yet verified by an accountant.** "
        "Treat these numbers as a sanity check of the pipeline, not as a measured production accuracy.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Overall accuracy | **{pct(correct, total)}** ({correct}/{total}) |",
        f"| Accuracy of auto-accepted items (not flagged) | {pct(sum(r.correct for r in auto), len(auto))} ({sum(r.correct for r in auto)}/{len(auto)}) |",
        f"| Flagged for manual review | {len(flagged)} of {total} |",
        f"| Average time per item | {1000 * sum(r.seconds for r in rows) / total:.1f} ms |",
        "",
        "## By decision source",
        "",
        "| Source | Items | Correct | Accuracy | Flagged | Avg time / item |",
        "|---|---|---|---|---|---|",
    ]
    for source in (Source.HISTORY, Source.RULE, Source.LLM, Source.NONE):
        group = by_source.get(source, [])
        if not group:
            continue
        ok = sum(r.correct for r in group)
        out.append(
            f"| {SOURCE_LABELS[source]} | {len(group)} | {ok} | {pct(ok, len(group))} | "
            f"{sum(r.needs_review for r in group)} | {1000 * sum(r.seconds for r in group) / len(group):.1f} ms |"
        )

    out += [
        "",
        "## Per item",
        "",
        "| # | Item | Expected | Predicted | Source | Confidence | Review | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r.id} | {r.name} | {r.expected} | {r.predicted or '—'} | {SOURCE_LABELS[r.source]} | "
            f"{r.confidence:.2f} | {'yes' if r.needs_review else ''} | {'✅' if r.correct else '❌'} |"
        )

    wrong = [r for r in rows if not r.correct and r.predicted]
    if wrong:
        out += ["", "## Mismatches", ""]
        out += [f"- **#{r.id} {r.name}** — expected {r.expected}, got {r.predicted}: {r.explanation}" for r in wrong]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "eval" / "dataset.json")
    parser.add_argument("--output", type=Path, default=ROOT / "eval_results.md")
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM step even if a key is configured")
    args = parser.parse_args()

    settings = get_settings()
    use_llm = not args.no_llm
    if use_llm and not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set; running without the LLM step.", file=sys.stderr)
        use_llm = False

    rows, model = run(args.dataset, use_llm)
    report = render(rows, model, settings.review_threshold)
    args.output.write_text(report, encoding="utf-8")

    total, correct = len(rows), sum(r.correct for r in rows)
    print(f"Overall accuracy: {pct(correct, total)} ({correct}/{total})")
    for source in (Source.HISTORY, Source.RULE, Source.LLM, Source.NONE):
        group = [r for r in rows if r.source == source]
        if group:
            print(f"  {SOURCE_LABELS[source]:<10} {pct(sum(r.correct for r in group), len(group)):>7}  ({len(group)} items)")
    print(f"Flagged for review: {sum(r.needs_review for r in rows)}")
    print(f"Average time per item: {1000 * sum(r.seconds for r in rows) / total:.1f} ms")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
