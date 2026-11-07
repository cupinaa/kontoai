"""The decision pipeline: history -> rules -> (masking) -> LLM -> validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.chart import ChartOfAccounts
from app.history import HistoryStore
from app.llm.base import LLMError, LLMProvider, LLMRequest
from app.masking import Masker
from app.models import InvoiceItem, Source, Suggestion
from app.rules import RuleEngine

log = logging.getLogger(__name__)


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
    ):
        self.chart = chart
        self.history = history
        self.rules = rules
        self.llm = llm
        self.review_threshold = review_threshold

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

    def _ask_llm(self, ctx: ItemContext) -> Suggestion:
        item = ctx.item
        masker = Masker()
        masker.add_company(item.supplier_name)
        masker.add_known("PIB", item.supplier_pib)
        masker.add_known("MB", ctx.supplier_registration_number)
        for person in ctx.person_names:
            masker.add_known("OSOBA", person)

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
