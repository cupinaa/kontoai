"""Wiring: builds the classifier from settings and runs whole invoices through it."""

from __future__ import annotations

from app.analytic import AnalyticPlan
from app.chart import ChartOfAccounts
from app.classifier import Classifier, ItemContext
from app.config import Settings
from app.history import HistoryStore
from app.llm.base import LLMProvider
from app.models import InvoiceItem, InvoiceMeta, InvoiceResponse, ItemResult
from app.rules import RuleEngine


def build_llm(settings: Settings) -> LLMProvider | None:
    if not settings.gemini_api_key:
        return None
    from app.llm.base import CallBudget
    from app.llm.cache import MemoryCachedProvider
    from app.llm.gemini import GeminiProvider

    budget = CallBudget(settings.max_llm_calls) if settings.max_llm_calls is not None else None
    provider = GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model, budget=budget)
    return MemoryCachedProvider(provider)  # identical masked requests are answered once per server process


def build_classifier(settings: Settings, llm: LLMProvider | None = None, *, use_llm: bool = True) -> Classifier:
    if llm is None and use_llm:
        llm = build_llm(settings)
    return Classifier(
        chart=ChartOfAccounts.load(settings.chart_path),
        history=HistoryStore(settings.db_path),
        rules=RuleEngine.load(settings.rules_path),
        llm=llm,
        review_threshold=settings.review_threshold,
        analytic_plan=AnalyticPlan.load(settings.analytic_plan_path),
    )


def classify_invoice(
    classifier: Classifier,
    *,
    client_id: str,
    client_activity: str,
    items: list[InvoiceItem],
    meta: InvoiceMeta | None = None,
) -> InvoiceResponse:
    people: list[str] = []
    if meta is not None:
        people = [p for p in (meta.supplier.contact_name, meta.buyer.contact_name) if p]

    results = []
    for item in items:
        ctx = ItemContext(
            client_id=client_id,
            client_activity=client_activity,
            item=item,
            supplier_registration_number=meta.supplier.registration_number if meta else None,
            person_names=tuple(people),
            currency=meta.currency if meta else None,
        )
        results.append(ItemResult(item=item, suggestion=classifier.classify(ctx)))

    return InvoiceResponse(
        client_id=client_id,
        client_activity=client_activity,
        invoice=meta,
        items=results,
        needs_review_count=sum(
            r.suggestion.needs_review or bool(r.suggestion.analytic and r.suggestion.analytic.needs_review)
            for r in results
        ),
    )
