import pytest

from app.config import DATA_DIR
from app.sef_parser import InvoiceParseError, parse_sef_xml


def test_parses_invoice_header_and_parties(sample_bytes):
    invoice = parse_sef_xml(sample_bytes("02_kancelarija_i_oprema_it.xml"))

    assert invoice.meta.number == "BP-1187/2026"
    assert invoice.meta.issue_date == "2026-10-08"
    assert invoice.meta.currency == "RSD"
    assert invoice.meta.supplier.name == "Biroprom Plus DOO"
    assert invoice.meta.supplier.pib == "202000022"
    assert invoice.meta.supplier.registration_number == "22000022"
    assert invoice.meta.supplier.contact_name == "Milica Savić"
    assert invoice.meta.buyer.pib == "102000002"


def test_parses_line_items(sample_bytes):
    items = parse_sef_xml(sample_bytes("02_kancelarija_i_oprema_it.xml")).items

    assert len(items) == 6
    paper = items[0]
    assert paper.name == "Papir A4 80g, 500 listova"
    assert paper.quantity == 20
    assert paper.unit == "H87"
    assert paper.unit_price == 520.0
    assert paper.amount == 10400.0
    assert paper.vat_rate == 20
    assert paper.supplier_pib == "202000022"

    laptop = items[2]
    assert laptop.description and "Jovana Jovanovića" in laptop.description


def test_all_samples_parse():
    samples = sorted((DATA_DIR / "samples").glob("*.xml"))
    assert 3 <= len(samples) <= 5
    for path in samples:
        invoice = parse_sef_xml(path.read_bytes())
        assert invoice.items, path.name
        assert invoice.meta.supplier.pib and invoice.meta.buyer.pib


def test_parses_credit_note():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
        xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
        xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
      <cbc:ID>KO-1</cbc:ID>
      <cac:AccountingSupplierParty><cac:Party>
        <cac:PartyTaxScheme><cbc:CompanyID>RS123456789</cbc:CompanyID></cac:PartyTaxScheme>
        <cac:PartyLegalEntity><cbc:RegistrationName>Dobavljač DOO</cbc:RegistrationName></cac:PartyLegalEntity>
      </cac:Party></cac:AccountingSupplierParty>
      <cac:CreditNoteLine>
        <cbc:ID>1</cbc:ID>
        <cbc:CreditedQuantity unitCode="H87">2</cbc:CreditedQuantity>
        <cbc:LineExtensionAmount currencyID="RSD">100.00</cbc:LineExtensionAmount>
        <cac:Item><cbc:Name>Povrat robe</cbc:Name></cac:Item>
      </cac:CreditNoteLine>
    </CreditNote>"""
    invoice = parse_sef_xml(xml.encode())
    assert invoice.meta.supplier.pib == "123456789"
    assert invoice.meta.supplier.name == "Dobavljač DOO"
    assert invoice.items[0].quantity == 2
    assert invoice.items[0].name == "Povrat robe"


@pytest.mark.parametrize(
    "content, message",
    [
        (b"not xml at all", "Neispravan XML"),
        (b"<root><child/></root>", "nije UBL"),
        (
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>1</ID></Invoice>',
            "nijednu stavku",
        ),
    ],
)
def test_rejects_invalid_documents(content, message):
    with pytest.raises(InvoiceParseError, match=message):
        parse_sef_xml(content)


def test_blocks_xml_entity_attacks():
    xxe = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&xxe;</Invoice>"""
    with pytest.raises(InvoiceParseError, match="zabranjene"):
        parse_sef_xml(xxe)
