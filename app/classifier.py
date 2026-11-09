"""The decision pipeline.

Synthetic (3-digit) account:   item history -> rules -> supplier history -> (masking) -> LLM -> validation;
                               if Iris gave an account, the result is compared with it (match / mismatch)
Analytic (4th digit) account:  only among the client's analytic accounts below the 3-digit account:
                               history -> single option -> LLM -> validation -> otherwise the accountant decides
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.analytic import AnalyticAccount, AnalyticPlan, common_words, mask_plan_name
from app.chart import ChartOfAccounts
from app.history import HistoryStore
from app.llm.base import AnalyticRequest, LLMError, LLMProvider, LLMRequest, QuestionRequest
from app.masking import Masker
from app.models import (
    AnalyticOption,
    AskResponse,
    AnalyticSource,
    AnalyticSuggestion,
    GivenCheck,
    InvoiceItem,
    PreviousChoice,
    Source,
    Suggestion,
)
from app.rules import RuleEngine
from app.text import normalize

log = logging.getLogger(__name__)

ONLY_OPTION_CONFIDENCE = 0.9
GUESS_CONFIDENCE = 0.3

_STOP = {"za", "i", "u", "na", "od", "po", "sa", "do", "troskovi", "trosak", "usluge", "usluga"}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in normalize(text).split() if len(w) > 2 and w not in _STOP and not w.isdigit()}


def best_by_overlap(text: str, options: list[AnalyticAccount]) -> AnalyticAccount:
    """The option whose name shares the most word stems with the item text.

    On a tie the more used account wins, then the first one in the list.
    """
    words = _stems(text)
    return max(options, key=lambda o: (len(words & _stems(o.naziv)), o.usage or 0))


_GENERIC_NAME = _STOP | {"drugi", "drugih", "ostali", "ostalih", "ostalog", "ostala", "trosk", "zemlj"}


def _name_stems(name: str) -> set[str]:
    return {s for s in _stems(name) if s not in {w[:5] for w in _GENERIC_NAME}}


def close_alternative(text: str, chosen: AnalyticAccount, options: list[AnalyticAccount]) -> AnalyticAccount | None:
    """Another option that makes the choice doubtful, or None.

    Two cases: (1) another option fits the description as well as the chosen one (equal, non-zero word
    overlap with the line) and is not much less used, or (2) the chosen account is used less than another
    one with a similar name (a shared distinctive word, e.g. both "PTT" accounts). Words most options of
    the group share ("materijal" under 512, "zakup" under 533) do not make two names similar.
    """
    common = {s for s in {s for o in options for s in _name_stems(o.naziv)}
              if sum(s in _name_stems(o.naziv) for o in options) * 2 > len(options)}
    words = _stems(text)
    score = len(words & _stems(chosen.naziv))
    chosen_name = _name_stems(chosen.naziv) - common
    for other in options:
        if other.konto == chosen.konto:
            continue
        comparable = chosen.usage is None or other.usage is None or other.usage * 2 >= chosen.usage
        if score and comparable and len(words & _stems(other.naziv)) == score:
            return other
        if (other.usage or 0) > (chosen.usage or 0) and chosen_name & (_name_stems(other.naziv) - common):
            return other
    return None


def _option(account: AnalyticAccount, naziv: str | None = None) -> AnalyticOption:
    return AnalyticOption(konto=account.konto, naziv=naziv if naziv is not None else account.naziv,
                          probni=account.probni, usage=account.usage, usage_label=account.usage_label())


@dataclass
class ItemContext:
    """One line item plus the context needed to classify it."""

    client_id: str
    client_activity: str
    item: InvoiceItem
    supplier_registration_number: str | None = None
    person_names: tuple[str, ...] = ()
    currency: str | None = None

    @property
    def text(self) -> str:
        item = self.item
        if not item.description:
            return item.name
        if item.name.casefold() in item.description.casefold():
            return item.description
        return f"{item.name} — {item.description}"


class Classifier:
    def __init__(
        self,
        chart: ChartOfAccounts,
        history: HistoryStore,
        rules: RuleEngine,
        llm: LLMProvider | None,
        review_threshold: float = 0.75,
        analytic_plan: AnalyticPlan | None = None,
    ):
        self.chart = chart
        self.history = history
        self.rules = rules
        self.llm = llm
        self.review_threshold = review_threshold
        self.analytic_plan = analytic_plan or AnalyticPlan()
        self._common_words: dict[str, frozenset[str]] = {}  # per client, for masking plan names

    # ------------------------------------------------------------------ synthetic account

    def _result(self, konto: str | None, source: Source, confidence: float, explanation: str) -> Suggestion:
        confidence = round(min(max(confidence, 0.0), 1.0), 3)
        return Suggestion(
            konto=konto,
            konto_name=self.chart.name(konto) if konto else None,
            source=source,
            confidence=confidence,
            explanation=explanation,
            needs_review=konto is None or confidence < self.review_threshold,
        )

    def classify(self, ctx: ItemContext) -> Suggestion:
        # The system always computes its own synthetic suggestion, also when Iris already gave one,
        # so that the two can be compared.
        suggestion = self._classify_synthetic(ctx)
        given = ctx.item.given_konto
        if given:
            self._check_given(suggestion, given)
            previous = self._previous_decision(ctx, given)
            if previous is not None:
                # The accountant already overrode this same Iris account for this same item:
                # offer her decision (account + analytic). The item still does not match Iris.
                suggestion.previous_choice, suggestion.analytic = previous
                return suggestion
        # The analytic account is chosen below the given (Iris) account when there is one: it is authoritative.
        suggestion.analytic = self.suggest_analytic(ctx, given or suggestion.konto)
        return suggestion

    def _previous_decision(self, ctx: ItemContext, given: str):
        item = ctx.item
        row = self.history.lookup_item_decision(ctx.client_id, item.name, item.supplier_pib, item.supplier_name, given)
        if row is None or row["konto"] not in self.chart:
            return None
        konto, analytic = row["konto"], row["analytic_konto"]
        choice = PreviousChoice(konto=konto, konto_name=self.chart.name(konto), analytic_konto=analytic,
                                analytic_naziv=row["analytic_name"])
        if not self.analytic_plan.has_client(ctx.client_id):
            return choice, None
        options = self.analytic_plan.options(ctx.client_id, konto)
        label = f"Prošli put ste izabrali {konto}" + (f" · {analytic}" if analytic else "")
        if analytic and any(o.konto == analytic for o in options):
            suggestion = self._analytic(options, analytic, AnalyticSource.HISTORY, 0.95, label + ".")
        elif options:
            # Her analytic is not in the plan (any more): preselect the closest one, flagged.
            suggestion = self._guess(ctx, options, label + ", ali taj analitički konto nije u planu.")
        else:
            suggestion = self._analytic(options, None, AnalyticSource.NONE, 0.0, label + ".")
        return choice, suggestion

    def _check_given(self, s: Suggestion, given: str) -> None:
        s.given_konto = given
        s.given_konto_name = self.chart.name(given)
        if given not in self.chart:
            s.given_check = GivenCheck.NOT_IN_CHART
            s.needs_review = True
            s.explanation = f"Iris konto {given} nije u kontnom okviru sistema. {s.explanation}"
        elif s.konto is None:
            s.given_check = GivenCheck.UNVERIFIED
            s.needs_review = True
            s.explanation = f"Sistem nema svoj predlog, pa Iris konto {given} nije proveren. {s.explanation}"
        elif s.konto == given:
            # Two independent sources agree: no review needed, even if the system alone was unsure.
            s.given_check = GivenCheck.MATCH
            s.needs_review = False
        else:
            s.given_check = GivenCheck.MISMATCH
            s.needs_review = True

    def _classify_synthetic(self, ctx: ItemContext) -> Suggestion:
        item = ctx.item

        # 1. Item history (same supplier + same/similar description) — the accountant already decided.
        match = self.history.lookup_item(ctx.client_id, item.name, item.supplier_pib, item.supplier_name)
        if match is not None and match.konto in self.chart:
            return self._result(match.konto, Source.HISTORY, match.confidence, match.explanation)

        # 2. Keyword rules for obvious cases. They beat supplier-level history.
        rule_match = self.rules.match(ctx.text, ctx.client_activity)
        if rule_match is not None and rule_match.rule.konto in self.chart:
            return self._result(rule_match.rule.konto, Source.RULE, rule_match.rule.confidence, rule_match.explanation)

        # 3. Supplier history: only if every confirmed item of the supplier is on one account (at least two).
        match = self.history.lookup_supplier(ctx.client_id, item.supplier_pib, item.supplier_name)
        if match is not None and match.konto in self.chart:
            return self._result(match.konto, Source.HISTORY, match.confidence, match.explanation)

        # 4. LLM, only with masked data.
        if self.llm is None:
            return self._result(
                None, Source.NONE, 0.0, "Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan."
            )
        return self._ask_llm(ctx)

    def _plan_name(self, ctx: ItemContext, masker: Masker, naziv: str) -> str:
        """An account name of the client's plan as the LLM may see it: identifying numbers, areas and
        place/street/building names become placeholders of `masker`, so answers are unmasked locally."""
        if ctx.client_id not in self._common_words:
            names = [a.naziv for a in self.analytic_plan.accounts(ctx.client_id)]
            self._common_words[ctx.client_id] = common_words(names, [a.naziv for a in self.chart.accounts])
        return mask_plan_name(masker.mask(naziv), masker, self._common_words[ctx.client_id])

    def _masker(self, ctx: ItemContext) -> Masker:
        item = ctx.item
        masker = Masker()
        masker.add_company(item.supplier_name)
        masker.add_known("PIB", item.supplier_pib)
        masker.add_known("MB", ctx.supplier_registration_number)
        for person in ctx.person_names:
            masker.add_known("OSOBA", person)
        return masker

    def answer_question(self, ctx: ItemContext, konto: str | None, analytic_konto: str | None,
                        question: str) -> AskResponse:
        """One LLM call answering the accountant's question about this line.

        The model gets only masked text: the line, the question, the suggested accounts, the candidates
        from the client's plan and the 3-digit chart. A recommended account is accepted only if it exists
        in the client's plan. Raises LLMError (including CallBudgetExceeded) when no answer is possible.
        """
        if self.llm is None:
            raise LLMError("LLM nije uključen (nema ključa ili je uključen bezbedni režim).")
        masker = self._masker(ctx)
        plan = self.analytic_plan
        options = plan.options(ctx.client_id, konto) if konto else []
        analytic = plan.get(ctx.client_id, analytic_konto) if analytic_konto else None
        request = QuestionRequest(
            question=masker.mask(question.strip()),
            item_text=masker.mask(ctx.text),
            client_activity=masker.mask(ctx.client_activity),
            konto=konto,
            konto_naziv=(self.chart.name(konto) or "") if konto else "",
            analytic_konto=analytic.konto if analytic else None,
            analytic_naziv=self._plan_name(ctx, masker, analytic.naziv) if analytic else "",
            options=[_option(o, self._plan_name(ctx, masker, o.naziv)) for o in options],
            chart=[AnalyticOption(konto=a.konto, naziv=a.naziv) for a in self.chart.accounts],
        )
        answer = self.llm.answer_question(request)

        text = masker.unmask(answer.odgovor.strip())[:1200] or "Model nije dao odgovor."
        recommended = (answer.preporuceni_konto or "").strip()
        if not answer.na_temu or not recommended:
            return AskResponse(answer=text, on_topic=answer.na_temu)
        account = plan.get(ctx.client_id, recommended)
        if account is None:
            log.warning("LLM recommended %r, which is not in the client's plan; rejected", recommended)
            return AskResponse(answer=f"{text} (Model je pomenuo konto {recommended}, koji nije u planu klijenta — "
                                      "ta preporuka je odbačena.)", rejected_konto=recommended)
        return AskResponse(answer=text, recommended_konto=account.konto, recommended_naziv=account.naziv)

    def _ask_llm(self, ctx: ItemContext) -> Suggestion:
        item = ctx.item
        masker = self._masker(ctx)
        request = LLMRequest(
            item_text=masker.mask(ctx.text),
            client_activity=masker.mask(ctx.client_activity),
            quantity=item.quantity,
            unit=item.unit,
            amount=item.amount,
            currency=ctx.currency,
            accounts=self.chart.accounts,
        )
        try:
            answer = self.llm.suggest(request)
        except LLMError as exc:
            log.warning("LLM failed for item %r: %s", item.name, exc)
            return self._result(None, Source.LLM, 0.0, f"LLM nije dao odgovor ({exc}). Potrebna ručna provera.")

        # 5. Validation: the model may only choose accounts from our list.
        konto = answer.konto.strip()
        if konto not in self.chart:
            log.warning("LLM returned account %r outside the chart; rejected", konto)
            return self._result(
                None,
                Source.LLM,
                0.0,
                f"LLM je predložio konto '{konto}' koji nije na dozvoljenom spisku — predlog je odbačen. "
                "Potrebna ručna provera.",
            )
        explanation = masker.unmask(answer.obrazlozenje.strip()) or "LLM predlog bez obrazloženja."
        return self._result(konto, Source.LLM, answer.sigurnost, explanation)

    # ------------------------------------------------------------------ analytic account

    def _analytic(
        self,
        options: list[AnalyticAccount],
        konto: str | None,
        source: AnalyticSource,
        confidence: float,
        explanation: str,
        *,
        needs_review: bool | None = None,
        poor_fit: bool = False,
        better_konto: str | None = None,
    ) -> AnalyticSuggestion:
        confidence = round(min(max(confidence, 0.0), 1.0), 3)
        chosen = next((o for o in options if o.konto == konto), None)
        if needs_review is None:
            needs_review = chosen is None or confidence < self.review_threshold or poor_fit
        return AnalyticSuggestion(
            konto=chosen.konto if chosen else None,
            naziv=chosen.naziv if chosen else None,
            source=source,
            confidence=confidence,
            explanation=explanation,
            needs_review=needs_review,
            options=[_option(o) for o in options],
            poor_fit=poor_fit,
            better_konto=better_konto,
            better_konto_name=self.chart.name(better_konto) if better_konto else None,
        )

    def _guess(self, ctx: ItemContext, options: list[AnalyticAccount], reason: str) -> AnalyticSuggestion:
        """No usable LLM answer: preselect the option whose name shares the most words with the item."""
        best = best_by_overlap(ctx.text, options)
        return self._analytic(options, best.konto, AnalyticSource.GUESS, GUESS_CONFIDENCE,
                              f"{reason} Izabran je najbliži konto po opisu — proverite.", needs_review=True)

    def suggest_analytic(self, ctx: ItemContext, konto: str | None) -> AnalyticSuggestion | None:
        """Choose the analytic account below `konto`, only among the client's plan. None if no plan."""
        if not konto or not self.analytic_plan.has_client(ctx.client_id):
            return None
        options = self.analytic_plan.options(ctx.client_id, konto)
        if not options:
            return self._analytic(options, None, AnalyticSource.NONE, 0.0,
                                  f"Analitički plan klijenta nema konto ispod {konto}. Potrebna ručna provera.")
        item = ctx.item
        codes = {o.konto for o in options}

        # 1. History: same/similar item of the same supplier, then a consistent supplier (at least two
        #    confirmations) — both only BELOW `konto`, which is Iris' account when one is given.
        match = self.history.lookup_analytic(ctx.client_id, item.name, item.supplier_pib, item.supplier_name, konto)
        if match is not None and match.konto in codes:
            return self._analytic(options, match.konto, AnalyticSource.HISTORY, match.confidence, match.explanation)

        # 2. Nothing to choose: the plan has exactly one analytic account below this synthetic account.
        if len(options) == 1:
            only = options[0]
            return self._analytic(options, only.konto, AnalyticSource.ONLY_OPTION, ONLY_OPTION_CONFIDENCE,
                                  f"Plan klijenta ima samo jedan analitički konto ispod {konto}: {only.konto}.")

        # 3. LLM chooses from the offered list, with masked data. Something is ALWAYS preselected:
        #    when the model is unsure or unavailable, the item is flagged instead of left empty.
        if self.llm is None:
            return self._guess(ctx, options, "Nema potvrde u istoriji.")
        masker = self._masker(ctx)
        request = AnalyticRequest(
            item_text=masker.mask(ctx.text),
            client_activity=masker.mask(ctx.client_activity),
            konto=konto,
            konto_naziv=self.chart.name(konto) or "",
            # Account names of a real plan can hold the client's own details (addresses, tax account
            # numbers), so they are masked like the item text.
            options=[_option(o, self._plan_name(ctx, masker, o.naziv)) for o in options],
            chart=[AnalyticOption(konto=a.konto, naziv=a.naziv) for a in self.chart.accounts],
        )
        try:
            answer = self.llm.choose_analytic(request)
        except LLMError as exc:
            log.warning("LLM analytic choice failed for item %r: %s", item.name, exc)
            return self._guess(ctx, options, "Model nije odgovorio.")

        # 4. Validation: only an offered analytic account is accepted.
        chosen = answer.konto.strip()
        if chosen not in codes:
            log.warning("LLM returned analytic %r outside the offered list; rejected", chosen)
            return self._guess(ctx, options, f"Predlog modela '{chosen}' nije u planu ispod {konto} i odbačen je.")
        explanation = masker.unmask(answer.obrazlozenje.strip()) or "Predlog bez obrazloženja."
        confidence = min(max(answer.sigurnost, 0.0), 1.0)
        better = (answer.bolji_konto or "").strip()
        better = better if better in self.chart and better != konto else None
        if not answer.dobro_odgovara:
            # Keep the closest option preselected, but say plainly that none fits well.
            return self._analytic(options, chosen, AnalyticSource.LLM, confidence,
                                  f"Nijedna analitika ne odgovara dobro. {explanation}",
                                  poor_fit=True, better_konto=better)
        # Two close candidates: keep the model's choice preselected, but flag it instead of looking certain.
        picked = next(o for o in options if o.konto == chosen)
        rival = close_alternative(ctx.text, picked, options)
        if rival is not None:
            return self._analytic(options, chosen, AnalyticSource.LLM, confidence,
                                  f"{explanation} Blizak je i konto {rival.konto} {rival.naziv} — proverite.",
                                  needs_review=True)
        # Low confidence: still preselected; needs_review flags it (yellow dot, not in "Potvrdi sve usklađene").
        return self._analytic(options, chosen, AnalyticSource.LLM, confidence, explanation)
