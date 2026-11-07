"""Pydantic models shared by the pipeline and the API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    """Which stage of the pipeline produced the suggestion."""

    HISTORY = "history"
    RULE = "rule"
    LLM = "llm"
    INPUT = "input"  # 3-digit account supplied with the item (e.g. already proposed by Iris)
    NONE = "none"


class AnalyticSource(StrEnum):
    """Which step chose the analytic (4th-digit) account."""

    HISTORY = "history"
    ONLY_OPTION = "only_option"  # the client's plan has exactly one analytic below the account
    LLM = "llm"
    NONE = "none"  # left to the accountant


class Party(BaseModel):
    name: str | None = None
    pib: str | None = Field(default=None, description="Tax ID (PIB), 9 digits")
    registration_number: str | None = Field(default=None, description="Matični broj")
    contact_name: str | None = None


class InvoiceItem(BaseModel):
    line_id: str | None = None
    name: str = Field(min_length=1)
    description: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    amount: float | None = Field(default=None, description="Line net amount (without VAT)")
    vat_rate: float | None = None
    supplier_name: str | None = None
    supplier_pib: str | None = None
    given_konto: str | None = Field(
        default=None,
        pattern=r"^\d{3}$",
        description="3-digit account already chosen elsewhere (e.g. by Iris); only the analytic account is suggested",
    )


class InvoiceMeta(BaseModel):
    number: str | None = None
    issue_date: str | None = None
    currency: str | None = None
    supplier: Party = Field(default_factory=Party)
    buyer: Party = Field(default_factory=Party)


class ParsedInvoice(BaseModel):
    meta: InvoiceMeta
    items: list[InvoiceItem]


class AnalyticOption(BaseModel):
    konto: str
    naziv: str
    probni: bool = False


class AnalyticSuggestion(BaseModel):
    konto: str | None = Field(description="Suggested analytic account, or null when left to the accountant")
    naziv: str | None = None
    source: AnalyticSource
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    needs_review: bool
    options: list[AnalyticOption] = Field(description="All analytic accounts of the client below the 3-digit account")


class Suggestion(BaseModel):
    konto: str | None = Field(description="Suggested 3-digit account, or null when undecided")
    konto_name: str | None = None
    source: Source
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    needs_review: bool
    analytic: AnalyticSuggestion | None = Field(
        default=None, description="Analytic (4th-digit) suggestion; null when the client has no analytic plan"
    )


class ItemResult(BaseModel):
    item: InvoiceItem
    suggestion: Suggestion


class InvoiceRequest(BaseModel):
    client_id: str = Field(min_length=1, examples=["100000001"])
    client_activity: str = Field(min_length=2, examples=["Razvoj softvera po narudžbini"])
    supplier_name: str | None = Field(default=None, examples=["Biroprom Plus DOO"])
    supplier_pib: str | None = Field(default=None, examples=["111222333"])
    items: list[InvoiceItem] = Field(min_length=1)


class InvoiceResponse(BaseModel):
    client_id: str
    client_activity: str
    invoice: InvoiceMeta | None = None
    items: list[ItemResult]
    needs_review_count: int


class ConfirmRequest(BaseModel):
    client_id: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    konto: str = Field(pattern=r"^\d{3}$", examples=["513"])
    supplier_name: str | None = None
    supplier_pib: str | None = None
    suggested_konto: str | None = None
    suggested_source: Source | None = None
    analytic_konto: str | None = Field(default=None, pattern=r"^\d{4,}$", examples=["5133"])
    suggested_analytic: str | None = None
    suggested_analytic_source: AnalyticSource | None = None


class HistoryRecord(BaseModel):
    id: int
    client_id: str
    item_name: str
    supplier_name: str | None
    supplier_pib: str | None
    konto: str
    konto_name: str | None
    suggested_konto: str | None
    suggested_source: Source | None
    corrected: bool
    analytic_konto: str | None = None
    analytic_name: str | None = None
    suggested_analytic: str | None = None
    suggested_analytic_source: AnalyticSource | None = None
    analytic_corrected: bool = False
    confirmed_at: datetime


class ConfirmResponse(BaseModel):
    status: str = Field(description="'confirmed' when the suggestion was accepted, 'corrected' otherwise")
    record: HistoryRecord


class Account(BaseModel):
    konto: str
    naziv: str
    klasa: str
    opis: str = ""
