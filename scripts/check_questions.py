"""Check the accountant-question feature against a real LLM, with a fixed set of questions.

    python scripts/check_questions.py --dry-run     # shows every masked prompt and the call count, sends nothing
    python scripts/check_questions.py --yes         # sends them: one call per question, hard limit = their number

The analytic plan comes from KONTOAI_ANALYTIC_PLAN_PATH (the client's real plan, kept outside the repository)
or the trial plan. Real calls cost money, so never run without --dry-run first and an explicit approval.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.classifier import ItemContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.base import LLMError, LLMProvider, QuestionAnswer, QuestionRequest, build_question_prompt  # noqa: E402
from app.models import InvoiceItem  # noqa: E402
from app.service import build_classifier  # noqa: E402

CLIENT = "K001"
ACTIVITY = "proizvodnja dijetetskih proizvoda"
SUPPLIER = {"supplier_name": "Poslovni Park Morava DOO", "supplier_pib": "204000077"}  # invented

# (item, 3-digit, analytic preselected, question, what a good answer does)
QUESTIONS = [
    ("Električna energija za oktobar 2026", "513", "5133",
     "Da li je 5133 dobro za struju?", "preporuči 5130 (električna energija), ne 5133 (gorivo za vozila)"),
    ("Poštanske usluge - slanje paketa kupcima", "531", "5312",
     "Gde ide slanje paketa kupcima?", "izabere neki od kandidata pod 531 ili kaže da nije sigurno"),
    ("Zaštitne maske i rukavice za proizvodnju", "539", "5390",
     "Da li je ovo usluga ili materijal?", "kaže da su maske materijal (512), a ne usluga — bez izmišljenog konta"),
    ("Provizija banke za platni promet", "553", "5530",
     "Koliko je visok kurs evra danas?", "na_temu = false, bez preporuke"),
]


class Recorder(LLMProvider):
    """Dry run: records what would be sent and answers nothing real."""

    name, model = "dry-run", "-"

    def __init__(self):
        self.requests: list[QuestionRequest] = []

    def suggest(self, request):  # pragma: no cover - not used here
        raise LLMError("dry run")

    def answer_question(self, request: QuestionRequest) -> QuestionAnswer:
        self.requests.append(request)
        return QuestionAnswer(odgovor="(dry run)", preporuceni_konto="", na_temu=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true", help="really send the questions (paid calls)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.dry_run:
        recorder = Recorder()
        classifier = build_classifier(settings, llm=recorder)
    else:
        if not settings.gemini_api_key:
            print("Nema GEMINI_API_KEY (ili je uključen bezbedni režim).", file=sys.stderr)
            return 1
        classifier = build_classifier(replace(settings, max_llm_calls=len(QUESTIONS)))
    print(f"Plan: {settings.analytic_plan_path.name} ({classifier.analytic_plan.status or 'bez statusa'}), "
          f"model: {settings.gemini_model}, pitanja: {len(QUESTIONS)}, najviše poziva: {len(QUESTIONS)}\n")

    for i, (name, konto, analytic, question, expected) in enumerate(QUESTIONS, start=1):
        ctx = ItemContext(client_id=CLIENT, client_activity=ACTIVITY, item=InvoiceItem(name=name, **SUPPLIER))
        print(f"--- {i}. {name} | {konto} · {analytic}\nPitanje: {question}\nDobar odgovor: {expected}")
        try:
            result = classifier.answer_question(ctx, konto, analytic, question)
        except LLMError as exc:
            print(f"GREŠKA: {exc}\n")
            continue
        if args.dry_run:
            print("Šalje se:\n" + build_question_prompt(recorder.requests[-1]) + "\n")
        else:
            print(f"Odgovor: {result.answer}\nPreporuka: {result.recommended_konto or '—'}"
                  f"{' (odbačeno: ' + result.rejected_konto + ')' if result.rejected_konto else ''}"
                  f" | na temu: {result.on_topic}\n")
    if not args.dry_run:
        print("Poslato zahteva:", classifier.llm.budget.used if classifier.llm.budget else "?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
