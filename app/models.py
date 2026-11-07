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
    INPUT = "input"  # used in confirmations: the preselected account came from the input (Iris)
    NONE = "none"


class GivenCheck(StrEnum):
    """How the system's own 3-digit suggestion compares with the account given on input (Iris)."""

    MATCH = "match"  # "Poklapa se sa Iris-om"
    MISMATCH = "mismatch"  # "Ne poklapa se — proveri" (goes to manual review)
    UNVERIFIED = "unverified"  # the system had no suggestion of its own
    NOT_IN_CHART = "not_in_chart"  # the given account is not in the system's chart


class AnalyticSource(StrEnum):
    """Which step chose the analytic (4th-digit) account."""

    HISTORY = "history"
    ONLY_OPTION = "only_option"  # the client's plan has exactly one analytic below the account
    LLM = "llm"
    GUESS = "guess"  # closest option by word overlap when the LLM gave no usable answer (always flagged)
    NONE = "none"  # nothing to choose: no analytic account below the synthetic one


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
        description="3-digit account already proposed elsewhere (e.g. by Iris). The system still computes its own "
                    "suggestion and compares; the analytic account is chosen below the given account.",
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
    poor_fit: bool = Field(default=False, description="No offered analytic account fits the item well")
    better_konto: str | None = Field(default=None, description="A 3-digit account that would fit better, if clear")
    better_konto_name: str | None = None


class PreviousChoice(BaseModel):
    konto: str
    konto_name: str | None = None
    analytic_konto: str | None = None
    analytic_naziv: str | None = None


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
    previous_choice: PreviousChoice | None = Field(
        default=None,
        description="The accountant's earlier decision for the same item when it differed from the same Iris "
                    "account; the UI preselects it (the item still does not match Iris)",
    )
    given_konto: str | None = Field(default=None, description="3-digit account given on input (Iris), if any")
    given_konto_name: str | None = None
    given_check: GivenCheck | None = Field(
        default=None, description="Comparison of the system's own suggestion (konto) with given_konto"
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
    given_konto: str | None = Field(default=None, pattern=r"^\d{3}$",
                                    description="Iris account of the item at confirmation time, if any")


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
    given_konto: str | None = None
    confirmed_at: datetime


class ConfirmResponse(BaseModel):
    status: str = Field(description="'confirmed' when the suggestion was accepted, 'corrected' otherwise")
    record: HistoryRecord


class Account(BaseModel):
    konto: str
    naziv: str
    klasa: str
    opis: str = ""
