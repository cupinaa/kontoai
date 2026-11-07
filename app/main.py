"""FastAPI application."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.classifier import Classifier
from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.models import Account, ConfirmRequest, ConfirmResponse, HistoryRecord, InvoiceRequest, InvoiceResponse
from app.sef_parser import InvoiceParseError, parse_sef_xml
from app.service import build_classifier, classify_invoice

STATIC_DIR = Path(__file__).parent / "static"
MAX_XML_BYTES = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None, *, use_llm: bool = True) -> FastAPI:
    settings = settings or get_settings()
    classifier: Classifier = build_classifier(settings, llm=llm, use_llm=use_llm)

    app = FastAPI(
        title="KontoAI",
        version=__version__,
        description="Suggests accounts from the Serbian chart of accounts for incoming SEF invoice items.",
    )
    app.state.classifier = classifier
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/logo-preview", include_in_schema=False)
    def logo_preview() -> FileResponse:
        return FileResponse(STATIC_DIR / "logo-preview.html")

    def llm_info() -> dict | None:
        llm = classifier.llm
        if llm is None:
            return None
        info: dict = {"provider": llm.name, "model": llm.model}
        budget = getattr(llm, "budget", None)
        if budget is not None:
            info["calls_sent"] = budget.used  # every real request, retries included
            info["max_calls"] = budget.max_calls
        usage = getattr(llm, "usage", None)
        if usage is not None:
            info["usage"] = dict(usage)  # successful responses and token counts
        if hasattr(llm, "hits"):
            info["cache_hits"] = llm.hits  # identical requests answered without an API call
        return info

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "llm": llm_info(),
            "accounts": len(classifier.chart),
            "chart_verified": classifier.chart.verified,
            "review_threshold": classifier.review_threshold,
            "analytic_plan_status": classifier.analytic_plan.status,
        }

    @app.get("/analytic-plan/{client_id}")
    def analytic_plan(client_id: str) -> dict:
        """The client's analytic accounts (empty list if the client has no plan)."""
        plan = classifier.analytic_plan
        return {
            "client_id": client_id,
            "status": plan.status if plan.has_client(client_id) else None,
            "accounts": [
                {"konto": a.konto, "naziv": a.naziv, "sintetika": a.sintetika, "probni": a.probni}
                for a in plan.accounts(client_id)
            ],
        }

    @app.get("/accounts", response_model=list[Account])
    def accounts() -> list[Account]:
        return classifier.chart.accounts

    @app.post("/invoices/xml", response_model=InvoiceResponse)
    async def invoice_xml(
        file: UploadFile = File(..., description="SEF UBL 2.1 XML"),
        client_activity: str = Form(..., min_length=2, description="Delatnost klijenta"),
        client_id: str | None = Form(None, description="Defaults to the buyer's PIB from the invoice"),
    ) -> InvoiceResponse:
        content = await file.read(MAX_XML_BYTES + 1)
        if len(content) > MAX_XML_BYTES:
            raise HTTPException(status_code=413, detail="Fajl je veći od 5 MB.")
        try:
            parsed = parse_sef_xml(content)
        except InvoiceParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        resolved_client = (client_id or "").strip() or parsed.meta.buyer.pib
        if not resolved_client:
            raise HTTPException(status_code=422, detail="client_id nije zadat, a faktura ne sadrži PIB kupca.")
        return classify_invoice(
            classifier,
            client_id=resolved_client,
            client_activity=client_activity.strip(),
            items=parsed.items,
            meta=parsed.meta,
        )

    @app.post("/invoices", response_model=InvoiceResponse)
    def invoice_json(request: InvoiceRequest) -> InvoiceResponse:
        items = [
            item.model_copy(
                update={
                    "supplier_name": item.supplier_name or request.supplier_name,
                    "supplier_pib": item.supplier_pib or request.supplier_pib,
                }
            )
            for item in request.items
        ]
        return classify_invoice(
            classifier, client_id=request.client_id, client_activity=request.client_activity, items=items
        )

    @app.post("/confirm", response_model=ConfirmResponse)
    def confirm(request: ConfirmRequest) -> ConfirmResponse:
        if request.konto not in classifier.chart:
            raise HTTPException(status_code=422, detail=f"Konto {request.konto} nije u kontnom okviru.")
        analytic = None
        if request.analytic_konto is not None:
            analytic = classifier.analytic_plan.get(request.client_id, request.analytic_konto)
            if analytic is None or analytic.sintetika != request.konto:
                raise HTTPException(
                    status_code=422,
                    detail=f"Analitički konto {request.analytic_konto} nije u planu klijenta ispod konta {request.konto}.",
                )
        record = classifier.history.add(
            client_id=request.client_id,
            item_name=request.item_name,
            konto=request.konto,
            konto_name=classifier.chart.name(request.konto),
            supplier_name=request.supplier_name,
            supplier_pib=request.supplier_pib,
            suggested_konto=request.suggested_konto,
            suggested_source=request.suggested_source,
            analytic_konto=analytic.konto if analytic else None,
            analytic_name=analytic.naziv if analytic else None,
            suggested_analytic=request.suggested_analytic,
            suggested_analytic_source=request.suggested_analytic_source,
        )
        corrected = record.corrected or record.analytic_corrected
        return ConfirmResponse(status="corrected" if corrected else "confirmed", record=record)

    @app.get("/history/{client_id}", response_model=list[HistoryRecord])
    def history(client_id: str) -> list[HistoryRecord]:
        return classifier.history.list(client_id)

    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` works, but importing this module (e.g. in tests) has no side effects:
    # the default app, its SQLite file and the Gemini client are only created on first access.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
