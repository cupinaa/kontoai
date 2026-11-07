"""Parser for SEF (Sistem e-faktura) invoices in UBL 2.1 XML.

Supports `Invoice` and `CreditNote` documents. XML is parsed with defusedxml
to block XXE / entity-expansion attacks, since files come from the outside.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from app.models import InvoiceItem, InvoiceMeta, ParsedInvoice, Party

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
_INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"

_PIB_RE = re.compile(r"(\d{9})")


class InvoiceParseError(ValueError):
    """Raised when the uploaded file is not a readable UBL invoice."""


def _text(element: Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path, NS)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _number(element: Element | None, path: str) -> float | None:
    value = _text(element, path)
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _extract_pib(party: Element) -> str | None:
    # SEF puts PIB in EndpointID (schemeID 9948) and in PartyTaxScheme as "RS" + PIB.
    for path in ("cbc:EndpointID", "cac:PartyTaxScheme/cbc:CompanyID", "cac:PartyIdentification/cbc:ID"):
        value = _text(party, path)
        if value:
            match = _PIB_RE.search(value)
            if match:
                return match.group(1)
    return None


def _parse_party(root: Element, role: str) -> Party:
    party = root.find(f"cac:{role}/cac:Party", NS)
    if party is None:
        return Party()
    name = (
        _text(party, "cac:PartyName/cbc:Name")
        or _text(party, "cac:PartyLegalEntity/cbc:RegistrationName")
    )
    return Party(
        name=name,
        pib=_extract_pib(party),
        registration_number=_text(party, "cac:PartyLegalEntity/cbc:CompanyID"),
        contact_name=_text(party, "cac:Contact/cbc:Name"),
    )


def parse_sef_xml(content: bytes | str) -> ParsedInvoice:
    """Parse a SEF UBL 2.1 Invoice/CreditNote into invoice metadata and line items."""
    try:
        root = SafeET.fromstring(content)
    except DefusedXmlException as exc:
        raise InvoiceParseError("XML sadrži zabranjene konstrukcije (DTD/entiteti).") from exc
    except SafeET.ParseError as exc:
        raise InvoiceParseError(f"Neispravan XML: {exc}") from exc

    if root.tag == f"{{{_INVOICE_NS}}}Invoice":
        line_tag, qty_tag = "cac:InvoiceLine", "cbc:InvoicedQuantity"
    elif root.tag == f"{{{_CREDIT_NOTE_NS}}}CreditNote":
        line_tag, qty_tag = "cac:CreditNoteLine", "cbc:CreditedQuantity"
    else:
        raise InvoiceParseError("Fajl nije UBL 2.1 faktura (očekivan Invoice ili CreditNote).")

    supplier = _parse_party(root, "AccountingSupplierParty")
    buyer = _parse_party(root, "AccountingCustomerParty")
    meta = InvoiceMeta(
        number=_text(root, "cbc:ID"),
        issue_date=_text(root, "cbc:IssueDate"),
        currency=_text(root, "cbc:DocumentCurrencyCode"),
        supplier=supplier,
        buyer=buyer,
    )

    items: list[InvoiceItem] = []
    for line in root.findall(line_tag, NS):
        name = _text(line, "cac:Item/cbc:Name") or _text(line, "cac:Item/cbc:Description")
        if not name:
            continue
        description = _text(line, "cac:Item/cbc:Description")
        qty_el = line.find(qty_tag, NS)
        items.append(
            InvoiceItem(
                line_id=_text(line, "cbc:ID"),
                name=name,
                description=description if description != name else None,
                quantity=_number(line, qty_tag),
                unit=qty_el.get("unitCode") if qty_el is not None else None,
                unit_price=_number(line, "cac:Price/cbc:PriceAmount"),
                amount=_number(line, "cbc:LineExtensionAmount"),
                vat_rate=_number(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
                supplier_name=supplier.name,
                supplier_pib=supplier.pib,
            )
        )

    if not items:
        raise InvoiceParseError("Faktura ne sadrži nijednu stavku.")
    return ParsedInvoice(meta=meta, items=items)
