"""The decision pipeline.

Synthetic (3-digit) account:   history -> rules -> (masking) -> LLM -> validation;
                               if Iris gave an account, the result is compared with it (match / mismatch)
Analytic (4th digit) account:  only among the client's analytic accounts below the 3-digit account:
                               history -> single option -> LLM -> validation -> otherwise the accountant decides
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.analytic import AnalyticAccount, AnalyticPlan
from app.chart import ChartOfAccounts
from app.history import HistoryStore
from app.llm.base import AnalyticRequest, LLMError, LLMProvider, LLMRequest
from app.masking import Masker
from app.models import (
    AnalyticOption,
    AnalyticSource,
    AnalyticSuggestion,
    GivenCheck,
    InvoiceItem,
    Source,
    Suggestion,
)
from app.rules import RuleEngine

log = logging.getLogger(__name__)

ONLY_OPTION_CONFIDENCE = 0.9


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
        # The analytic account is chosen below the given (Iris) account when there is one: it is authoritative.
        suggestion.analytic = self.suggest_analytic(ctx, given or suggestion.konto)
        return suggestion

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

        # 1. Client history — the strongest signal, because the accountant already decided.
        match = self.history.lookup(ctx.client_id, item.name, item.supplier_pib, item.supplier_name)
        if match is not None and match.konto in self.chart:
            return self._result(match.konto, Source.HISTORY, match.confidence, match.explanation)

        # 2. Keyword rules for obvious cases.
        rule_match = self.rules.match(ctx.text, ctx.client_activity)
        if rule_match is not None and rule_match.rule.konto in self.chart:
            return self._result(rule_match.rule.konto, Source.RULE, rule_match.rule.confidence, rule_match.explanation)

        # 3. LLM, only with masked data.
        if self.llm is None:
            return self._result(
                None, Source.NONE, 0.0, "Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan."
            )
        return self._ask_llm(ctx)

    def _masker(self, ctx: ItemContext) -> Masker:
        item = ctx.item
        masker = Masker()
        masker.add_company(item.supplier_name)
        masker.add_known("PIB", item.supplier_pib)
        masker.add_known("MB", ctx.supplier_registration_number)
        for person in ctx.person_names:
            masker.add_known("OSOBA", person)
        return masker

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

        # 4. Validation: the model may only choose accounts from our list.
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
    ) -> AnalyticSuggestion:
        confidence = round(min(max(confidence, 0.0), 1.0), 3)
        chosen = next((o for o in options if o.konto == konto), None)
        return AnalyticSuggestion(
            konto=chosen.konto if chosen else None,
            naziv=chosen.naziv if chosen else None,
            source=source,
            confidence=confidence,
            explanation=explanation,
            needs_review=(chosen is None or confidence < self.review_threshold) if needs_review is None
            else needs_review,
            options=[AnalyticOption(konto=o.konto, naziv=o.naziv, probni=o.probni) for o in options],
        )

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

        # 1. History: same item, then same supplier, confirmed below this synthetic account.
        match = self.history.lookup_analytic(ctx.client_id, item.name, item.supplier_pib, item.supplier_name, konto)
        if match is not None and match.konto in codes:
            return self._analytic(options, match.konto, AnalyticSource.HISTORY, match.confidence, match.explanation)

        # 2. Nothing to choose: the plan has exactly one analytic account below this synthetic account.
        if len(options) == 1:
            only = options[0]
            return self._analytic(options, only.konto, AnalyticSource.ONLY_OPTION, ONLY_OPTION_CONFIDENCE,
                                  f"Plan klijenta ima samo jedan analitički konto ispod {konto}: {only.konto}.")

        # 3. LLM chooses from the offered list, with masked data.
        if self.llm is None:
            return self._analytic(options, None, AnalyticSource.NONE, 0.0,
                                  "Nema potvrde u istoriji, a LLM nije konfigurisan — izbor je na knjigovođi.")
        masker = self._masker(ctx)
        request = AnalyticRequest(
            item_text=masker.mask(ctx.text),
            client_activity=masker.mask(ctx.client_activity),
            konto=konto,
            konto_naziv=self.chart.name(konto) or "",
            options=[AnalyticOption(konto=o.konto, naziv=o.naziv) for o in options],
        )
        try:
            answer = self.llm.choose_analytic(request)
        except LLMError as exc:
            log.warning("LLM analytic choice failed for item %r: %s", item.name, exc)
            return self._analytic(options, None, AnalyticSource.LLM, 0.0,
                                  f"LLM nije izabrao analitiku ({exc}). Izbor je na knjigovođi.")

        # 4. Validation: only an offered analytic account is accepted.
        chosen = answer.konto.strip()
        if chosen not in codes:
            log.warning("LLM returned analytic %r outside the offered list; rejected", chosen)
            return self._analytic(options, None, AnalyticSource.LLM, 0.0,
                                  f"LLM je predložio analitički konto '{chosen}' koji nije u planu klijenta ispod "
                                  f"{konto} — predlog je odbačen. Izbor je na knjigovođi.")
        explanation = masker.unmask(answer.obrazlozenje.strip()) or "LLM izbor bez obrazloženja."
        confidence = min(max(answer.sigurnost, 0.0), 1.0)
        if confidence < self.review_threshold:
            # Not sure enough: do not preselect anything, leave the choice to the accountant.
            return self._analytic(options, None, AnalyticSource.LLM, confidence,
                                  f"LLM nije dovoljno siguran (najbliži: {chosen}, sigurnost {confidence:.2f}): "
                                  f"{explanation} Izbor je na knjigovođi.")
        return self._analytic(options, chosen, AnalyticSource.LLM, confidence, explanation)
