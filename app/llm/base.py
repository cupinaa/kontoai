"""Provider-agnostic LLM interface.

The rest of the application only knows `LLMProvider`. Switching to another
model or vendor means writing one new subclass; nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.models import Account, AnalyticOption


class LLMError(RuntimeError):
    """The provider failed (network, quota, invalid response...)."""


class CallBudgetExceeded(LLMError):
    """The configured maximum number of API calls was reached; no request was sent."""


class CallBudget:
    """Hard cap on the number of real API requests (every attempt, including retries, counts)."""

    def __init__(self, max_calls: int):
        if max_calls < 0:
            raise ValueError("max_calls must be >= 0")
        self.max_calls = max_calls
        self.used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    def consume(self) -> None:
        if self.exhausted:
            raise CallBudgetExceeded(f"dostignut limit od {self.max_calls} API poziva, zahtev nije poslat")
        self.used += 1


class LLMRequest(BaseModel):
    """Everything the model is allowed to see. Text fields are already masked."""

    item_text: str
    client_activity: str
    quantity: float | None = None
    unit: str | None = None
    amount: float | None = None
    currency: str | None = None
    accounts: list[Account]


class LLMSuggestion(BaseModel):
    """Structured output expected from the model (field names match the JSON schema sent to it)."""

    konto: str = Field(description="Trocifreni konto iz dozvoljenog spiska")
    naziv_konta: str = Field(description="Naziv konta")
    sigurnost: float = Field(description="Sigurnost od 0 do 1 (van opsega se seče na [0, 1])")
    obrazlozenje: str = Field(description="Kratko obrazloženje na srpskom jeziku")


SYSTEM_PROMPT = """Ti si iskusan knjigovođa u Republici Srbiji. Za stavku sa ulazne fakture predlažeš
trocifreni konto iz kontnog okvira za privredna društva (Sl. glasnik RS 89/2020).

Pravila:
- Smeš da izabereš ISKLJUČIVO konto iz priloženog spiska dozvoljenih konta. Nikada ne izmišljaj konto.
- Uzmi u obzir delatnost klijenta: ista stavka može biti trošak, materijal, osnovno sredstvo
  ili roba za dalju prodaju u zavisnosti od toga čime se klijent bavi.
- Oznake u uglastim zagradama (npr. [DOBAVLJAC_1], [OSOBA_1]) zamenjuju poverljive podatke; ne pokušavaj da ih pogodiš.
- "sigurnost" je broj od 0 do 1. Budi realan: ako stavka može opravdano da ide na više konta
  ili je opis nejasan, sigurnost treba da bude ispod 0.7.
- "obrazlozenje" piši na srpskom jeziku (latinica), u jednoj ili dve rečenice.
"""


def build_user_prompt(request: LLMRequest) -> str:
    lines = [
        f"Delatnost klijenta: {request.client_activity}",
        f"Stavka fakture: {request.item_text}",
    ]
    if request.quantity is not None:
        lines.append(f"Količina: {request.quantity:g}{' ' + request.unit if request.unit else ''}")
    if request.amount is not None:
        lines.append(f"Iznos bez PDV-a: {request.amount:,.2f} {request.currency or 'RSD'}")
    lines.append("")
    lines.append("Dozvoljena konta:")
    lines.extend(f"- {a.konto} {a.naziv}: {a.opis}" for a in request.accounts)
    return "\n".join(lines)


class AnalyticRequest(BaseModel):
    """Choice of an analytic account among the client's options. Text fields are already masked."""

    item_text: str
    client_activity: str
    konto: str
    konto_naziv: str
    options: list[AnalyticOption]
    # Synthetic accounts the model may name as a better fit when no offered analytic fits well.
    chart: list[AnalyticOption] = Field(default_factory=list)


class AnalyticChoice(BaseModel):
    konto: str = Field(description="Analitički konto iz ponuđenog spiska")
    sigurnost: float = Field(description="Sigurnost od 0 do 1")
    obrazlozenje: str = Field(description="Kratko obrazloženje na srpskom jeziku")
    dobro_odgovara: bool = Field(default=True, description="Da li izabrani konto dobro odgovara opisu stavke")
    bolji_konto: str = Field(default="", description="Trocifreni konto koji bi bolje odgovarao, ili prazno")


ANALYTIC_SYSTEM_PROMPT = """Ti si iskusan knjigovođa u Republici Srbiji. Sintetički (trocifreni) konto stavke
je već određen. Tvoj zadatak je da izabereš analitički konto iz kontnog plana klijenta.

Pravila:
- UVEK izaberi jedan od ponuđenih analitičkih konta — najbliži opisu stavke. Nikada ne izmišljaj konto.
- Ako je opis nejasan ili izbor nije očigledan, stavi sigurnost ispod 0.6.
- Ako nijedan ponuđeni konto ne odgovara dobro, postavi "dobro_odgovara" na false. Ako je jasno da bi stavka
  bolje pristajala na drugi sintetički konto sa spiska sintetičkih konta, upiši ga u "bolji_konto"; inače ostavi prazno.
- Oznake u uglastim zagradama (npr. [DOBAVLJAC_1]) zamenjuju poverljive podatke; ne pokušavaj da ih pogodiš.
- "obrazlozenje" piši na srpskom jeziku (latinica), u jednoj rečenici.
"""


def build_analytic_prompt(request: AnalyticRequest) -> str:
    lines = [
        f"Delatnost klijenta: {request.client_activity}",
        f"Stavka fakture: {request.item_text}",
        f"Sintetički konto: {request.konto} {request.konto_naziv}",
        "",
        "Ponuđeni analitički konti:",
    ]
    lines.extend(f"- {o.konto} {o.naziv}" for o in request.options)
    if request.chart:
        lines += ["", "Sintetička konta (samo za \"bolji_konto\"):"]
        lines.extend(f"- {o.konto} {o.naziv}" for o in request.chart)
    return "\n".join(lines)


class LLMProvider(ABC):
    """Interface every model backend implements."""

    name: str = "llm"
    model: str = ""

    @abstractmethod
    def suggest(self, request: LLMRequest) -> LLMSuggestion:
        """Return a structured suggestion. Raise `LLMError` on failure."""

    def choose_analytic(self, request: AnalyticRequest) -> AnalyticChoice:
        """Choose an analytic account among `request.options`. Raise `LLMError` on failure.

        Providers that do not implement it simply leave the analytic choice to the accountant.
        """
        raise LLMError(f"{self.name} ne podržava izbor analitičkog konta")
