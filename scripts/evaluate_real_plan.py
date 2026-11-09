"""Evaluate against a client's REAL analytic plan, using a private dataset kept outside the repository.

    python scripts/evaluate_real_plan.py --dataset C:\\...\\kontoai_private\\eval_pravi_plan.json \\
        --forbidden C:\\...\\kontoai_private\\zabranjeno.txt --dry-run
    python scripts/evaluate_real_plan.py --dataset ... --forbidden ... --max-calls 36

The plan comes from KONTOAI_ANALYTIC_PLAN_PATH. Each item is classified as for client `client_id`
with the expected 3-digit account given as the accounting software's account (as Iris would give it),
so the run measures:
  - the system's OWN 3-digit suggestion against the expected account, and
  - the analytic account chosen below the expected 3-digit account,
separately for items whose expected account the accountant confirmed ("knjigovodja") and items whose
account was chosen from the plan by name ("izvedeno_iz_plana").

Before any request is sent (also in --dry-run) it is checked against --forbidden (one string per line:
company name, address, registration numbers, place names); a hit stops the run. The per-item report with
account names goes next to the dataset (private); --summary gets aggregate numbers only (public).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from app.classifier import ItemContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.base import (  # noqa: E402
    AnalyticChoice,
    AnalyticRequest,
    CallBudget,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMSuggestion,
    build_analytic_prompt,
    build_user_prompt,
)
from app.models import InvoiceItem  # noqa: E402
from app.service import build_classifier  # noqa: E402
from scripts.evaluate import CACHE_DIR, CachedProvider, estimated_cost  # noqa: E402

GROUPS = ("knjigovodja", "izvedeno_iz_plana")


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


class ForbiddenContent(LLMError):
    """A request contained a string from the forbidden list; nothing was sent."""


class Guard(LLMProvider):
    """Checks every outgoing request for forbidden strings, then passes it on (or records it in a dry run)."""

    def __init__(self, inner: LLMProvider | None, forbidden: list[str], cache_dir: Path | None = None,
                 model: str = "-"):
        self.inner = inner
        self.forbidden = [f.casefold() for f in forbidden if f.strip()]
        self.name = inner.name if inner else "dry-run"
        self.model = inner.model if inner else model
        # Answers already in the evaluation cache (.eval_cache/, same model and same masked request) are
        # reused instead of paid for again; in a dry run they are not counted as calls.
        self.cache = CachedProvider(inner or self, cache_dir) if cache_dir else None
        self.cached = 0
        self.prompts: list[str] = []
        self.checked = 0
        self.blocked = 0  # requests stopped because they contained a forbidden string

    @property
    def budget(self):
        return getattr(self.inner, "budget", None)

    def _check(self, prompt: str) -> None:
        low = prompt.casefold()
        hits = [f for f in self.forbidden if f in low]
        if hits:
            self.blocked += 1
            raise ForbiddenContent(f"zahtev sadrži zabranjen podatak ({len(hits)}); NIJE poslat")
        self.checked += 1

    def _hit(self, request, prefix: str) -> bool:
        return self.cache is not None and self.cache._path(request, prefix).exists()

    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        self._check(build_user_prompt(request))
        if self._hit(request, ""):
            self.cached += 1
            return self.cache.suggest(request)
        self.prompts.append("call")
        if self.inner is None:
            return LLMSuggestion(konto=request.accounts[0].konto, naziv_konta="-", sigurnost=0.5, obrazlozenje="dry")
        return self.cache.suggest(request) if self.cache else self.inner.suggest(request)

    def choose_analytic(self, request: AnalyticRequest) -> AnalyticChoice:
        self._check(build_analytic_prompt(request))
        if self._hit(request, "analytic:"):
            self.cached += 1
            return self.cache.choose_analytic(request)
        self.prompts.append("call")
        if self.inner is None:
            return AnalyticChoice(konto=request.options[0].konto, sigurnost=0.5, obrazlozenje="dry")
        return self.cache.choose_analytic(request) if self.cache else self.inner.choose_analytic(request)


@dataclass
class Row:
    item: dict
    konto: str | None
    confidence: float
    konto_flagged: bool
    analytic: str | None
    analytic_name: str | None
    analytic_flagged: bool
    analytic_source: str | None

    @property
    def konto_ok(self) -> bool:
        return self.konto == self.item["expected_konto"]

    @property
    def analytic_ok(self) -> bool:
        return self.analytic == self.item["expected_analytic"]


def stats(rows: list[Row], level: str) -> dict:
    ok = [getattr(r, f"{level}_ok") for r in rows]
    flagged = [getattr(r, f"{level}_flagged") for r in rows]
    n = len(rows)
    return {
        "n": n, "correct": sum(ok),
        "pct": f"{100 * sum(ok) / n:.0f}%" if n else "—",
        "flagged": sum(flagged),
        "silent": sum(1 for o, f in zip(ok, flagged) if not o and not f),
    }


def summary_md(rows: list[Row], info: dict) -> str:
    lines = [
        "# Evaluation against the client's real analytic plan",
        "",
        f"- Date: {info['date']} · model `{info['model']}` · items: {len(rows)}",
        "- The dataset and the plan are confidential and kept outside this repository; only aggregate numbers are here.",
        "- Expected accounts: **knjigovodja** = the accountant's own answer, which matches the client's plan;",
        "  **izvedeno_iz_plana** = her answer did not match the plan, so the account was chosen from the plan by name",
        "  (the more used one when two fit equally). The second group was labelled by the author, not by the accountant.",
        "- Each item gets the expected 3-digit account as the accounting software's account (as Iris gives it). The",
        "  3-digit columns score the system's *own* suggestion; the analytic step chooses below the given account.",
        "- *Flagged* = shown for review (low confidence, or no suggestion). *Silent error* = wrong and not flagged.",
        "",
        "| Group | Items | 3-digit correct | Flagged | Silent errors | Analytic correct | Flagged | Silent errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label, group in [("all", rows)] + [(g, [r for r in rows if r.item["izvor"] == g]) for g in GROUPS]:
        k, a = stats(group, "konto"), stats(group, "analytic")
        lines.append(f"| {label} | {len(group)} | {k['correct']}/{k['n']} ({k['pct']}) | {k['flagged']} | {k['silent']} "
                     f"| {a['correct']}/{a['n']} ({a['pct']}) | {a['flagged']} | {a['silent']} |")
    lines += ["", f"API requests sent in this run: {info['calls']} (hard limit {info['max_calls']}); answers reused from "
              f"the evaluation cache (identical masked requests answered in earlier runs): {info.get('cached', 0)}. "
              f"Tokens: prompt {info['usage'].get('prompt_tokens', 0)}, output {info['usage'].get('output_tokens', 0)}, "
              f"thinking {info['usage'].get('thinking_tokens', 0)}. Estimated cost: {info['cost']}."]
    return "\n".join(lines) + "\n"


def private_md(rows: list[Row], info: dict) -> str:
    lines = [summary_md(rows, info), "## Po stavkama (POVERLJIVO)", "",
             "| ID | Izvor | Stavka | Očekivano | Sistem 3 | Sig. | Očekivana analitika | Sistem analitika | Izvor analitike |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        it = r.item
        mark3 = ("✅" if r.konto_ok else "❌") + (" 🟡" if r.konto_flagged else "")
        markA = ("✅" if r.analytic_ok else "❌") + (" 🟡" if r.analytic_flagged else "")
        lines.append(f"| {it['id']} | {it['izvor']} | {it['name']} | {it['expected_konto']} | {r.konto or '—'} {mark3} "
                     f"| {r.confidence:.2f} | {it['expected_analytic']} {it.get('expected_analytic_name', '')} "
                     f"| {r.analytic or '—'} {r.analytic_name or ''} {markA} | {r.analytic_source or '—'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True, help="private dataset, OUTSIDE the repository")
    parser.add_argument("--forbidden", type=Path, help="strings that must never be sent (one per line)")
    parser.add_argument("--max-calls", type=int, default=36)
    parser.add_argument("--summary", type=Path, default=ROOT / "eval_results_real_plan.md",
                        help="aggregate numbers only (default: eval_results_real_plan.md in the repo)")
    parser.add_argument("--dry-run", action="store_true", help="count and check the requests, send nothing")
    parser.add_argument("--no-cache", action="store_true", help="do not reuse answers from .eval_cache/")
    args = parser.parse_args(argv)

    if inside_repo(args.dataset):
        print("Odbijeno: dataset sa pravim planom mora biti van repoa.", file=sys.stderr)
        return 2
    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    forbidden = args.forbidden.read_text(encoding="utf-8").splitlines() if args.forbidden else []
    # Supplier names and tax IDs of the items must never be sent either (masking replaces them).
    forbidden += [str(it[k]) for it in data["items"] for k in ("supplier_name", "supplier_pib") if it.get(k)]
    settings = get_settings()
    if inside_repo(settings.analytic_plan_path):
        print("Odbijeno: KONTOAI_ANALYTIC_PLAN_PATH ne pokazuje na pravi (privatni) plan.", file=sys.stderr)
        return 2

    inner = None
    if not args.dry_run:
        if not settings.gemini_api_key:
            print("Nema GEMINI_API_KEY (ili je uključen bezbedni režim).", file=sys.stderr)
            return 1
        from app.llm.gemini import GeminiProvider

        inner = GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model,
                               budget=CallBudget(args.max_calls))
    guard = Guard(inner, forbidden, None if args.no_cache else CACHE_DIR, model=settings.gemini_model)

    rows: list[Row] = []
    with tempfile.TemporaryDirectory() as tmp:
        classifier = build_classifier(replace(settings, db_path=Path(tmp) / "eval.db"), llm=guard)
        for it in data["items"]:
            item = InvoiceItem(name=it["name"], given_konto=it["expected_konto"], quantity=it.get("quantity"),
                               unit=it.get("unit"), amount=it.get("amount"), supplier_name=it.get("supplier_name"),
                               supplier_pib=it.get("supplier_pib"))
            ctx = ItemContext(client_id=data["client_id"], client_activity=it["client_activity"], item=item)
            s = classifier.classify(ctx)
            a = s.analytic
            rows.append(Row(item=it, konto=s.konto, confidence=s.confidence,
                            konto_flagged=s.konto is None or s.confidence < classifier.review_threshold,
                            analytic=a.konto if a else None, analytic_name=a.naziv if a else None,
                            analytic_flagged=True if a is None else a.needs_review,
                            analytic_source=a.source.value if a else None))

    if args.dry_run:
        print(f"DRY RUN — ništa nije poslato. Stavki: {len(rows)}; proverenih zahteva: {guard.checked}; "
              f"iz keša: {guard.cached}; novih API poziva: {len(guard.prompts)} (limit {args.max_calls}); zaustavljenih zbog zabranjenog podatka: {guard.blocked} "
              f"(proveravano {len(guard.forbidden)} stringova)")
        return 0 if guard.blocked == 0 else 3
    if guard.blocked:
        print(f"UPOZORENJE: {guard.blocked} zahteva sadržalo je zabranjen podatak i NIJE poslato.", file=sys.stderr)

    usage = dict(getattr(inner, "usage", {}) or {})
    info = {"date": date.today().isoformat(), "model": settings.gemini_model, "calls": inner.budget.used,
            "cached": guard.cached,
            "max_calls": args.max_calls, "usage": usage}
    cost = estimated_cost(settings.gemini_model, usage) if usage else None
    info["cost"] = f"${cost:.4f}" if cost is not None else "unknown"
    report = args.dataset.with_name("rezultati_pravi_plan.md")
    report.write_text(private_md(rows, info), encoding="utf-8")
    args.summary.write_text(summary_md(rows, info), encoding="utf-8", newline="\n")
    print(summary_md(rows, info))
    print(f"Po stavkama (privatno): {report}")
    return 0 if guard.blocked == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
