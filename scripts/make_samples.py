"""Generate the fictional SEF UBL 2.1 sample invoices in data/samples/.

All companies, tax IDs, people and bank accounts are invented.
Run:  python scripts/make_samples.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "data" / "samples"


@dataclass
class Company:
    name: str
    pib: str
    mb: str
    street: str
    city: str
    contact: str | None = None
    email: str | None = None


@dataclass
class Line:
    name: str
    qty: float
    unit: str
    price: float
    vat: int = 20
    description: str | None = None


BRZI_KURIR = Company("Brzi Kurir DOO", "101000001", "21000001", "Bulevar oslobođenja 12", "Novi Sad", "Ana Ilić")
KOD_STUDIO = Company("Kod Studio DOO", "102000002", "21000002", "Nemanjina 4", "Beograd", "Petar Nikolić")
MARKET = Company("Market Kod Ćoška DOO", "103000003", "21000003", "Kralja Petra 21", "Kragujevac", "Vesna Đorđević")

INVOICES = [
    (
        "01_gorivo_kurirska_sluzba.xml",
        "GS-2026-00417",
        "2026-10-03",
        Company("Benzinska stanica Kosmaj DOO", "201000011", "22000011", "Kragujevački put 88", "Mladenovac",
                "Dragan Stojković", "fakture@bs-kosmaj.example"),
        BRZI_KURIR,
        "160-0000000417001-11",
        [
            Line("Evrodizel", 412.5, "LTR", 172.50),
            Line("BMB 95", 96.0, "LTR", 168.90),
            Line("AdBlue tečnost 10L", 4, "H87", 1290.00),
            Line("Pranje kombija - spoljno", 3, "H87", 1500.00),
            Line("Motorno ulje 5W-30 4L", 2, "H87", 4890.00),
        ],
    ),
    (
        "02_kancelarija_i_oprema_it.xml",
        "BP-1187/2026",
        "2026-10-08",
        Company("Biroprom Plus DOO", "202000022", "22000022", "Cara Dušana 140", "Zemun",
                "Milica Savić", "prodaja@biroprom.example"),
        KOD_STUDIO,
        "205-0000001187002-22",
        [
            Line("Papir A4 80g, 500 listova", 20, "H87", 520.00),
            Line("Toner HP 85A", 3, "H87", 6900.00),
            Line("Laptop Lenovo ThinkPad E14 Gen 6", 2, "H87", 112000.00,
                 description="Laptop Lenovo ThinkPad E14 Gen 6, za zaposlenog Jovana Jovanovića"),
            Line("Bežični miš Logitech M185", 4, "H87", 1650.00),
            Line("Fascikle sa mehanizmom", 30, "H87", 95.00),
            Line("Kafa u zrnu 1kg", 2, "H87", 2890.00),
        ],
    ),
    (
        "03_zakup_poslovnog_prostora.xml",
        "PCV-10/2026",
        "2026-10-01",
        Company("Poslovni Centar Vračar DOO", "203000033", "22000033", "Krunska 50", "Beograd",
                "Milan Marković", "racunovodstvo@pcvracar.example"),
        KOD_STUDIO,
        "170-0000000010003-33",
        [
            Line("Zakup poslovnog prostora za oktobar 2026", 1, "MON", 185000.00),
            Line("Zakup parking mesta", 2, "MON", 6000.00),
            Line("Električna energija - refakturisanje", 1, "C62", 14320.00),
            Line("Troškovi održavanja zajedničkih prostorija", 1, "C62", 9500.00,
                 description="Troškovi održavanja zajedničkih prostorija, upravnik zgrade, kontakt: Milan Marković"),
        ],
    ),
    (
        "04_roba_za_preprodaju_market.xml",
        "VD-55821",
        "2026-10-12",
        Company("Veleprodaja Dunav DOO", "204000044", "22000044", "Industrijska zona bb", "Smederevo",
                "Nenad Popović", "office@vp-dunav.example"),
        MARKET,
        "325-0000005582104-44",
        [
            Line("Mleko 2,8% m.m. 1L", 240, "H87", 118.00, vat=10),
            Line("Hleb beli 500g", 120, "H87", 64.00, vat=10),
            Line("Sok od jabuke 1L", 96, "H87", 139.00),
            Line("Mineralna voda 1,5L, pakovanje 6 kom", 40, "H87", 342.00),
            Line("Kese PVC sa logom, 1000 kom", 2, "H87", 3200.00),
            Line("Prevoz robe do maloprodajnog objekta", 1, "C62", 4500.00),
        ],
    ),
    (
        "05_telekomunikacije.xml",
        "TN-2026-10-778812",
        "2026-10-05",
        Company("TeleNet Srbija DOO", "205000055", "22000055", "Omladinskih brigada 90", "Beograd",
                None, "e-fakture@telenet.example"),
        BRZI_KURIR,
        "265-0000077881205-55",
        [
            Line("Mobilna telefonija - poslovna tarifa, oktobar", 8, "MON", 1990.00),
            Line("Internet 500 Mbps - poslovni paket", 1, "MON", 3490.00),
            Line("Mobilni telefon uređaj Samsung Galaxy A35", 2, "H87", 32990.00),
            Line("GPS praćenje vozila - mesečna usluga", 6, "MON", 850.00),
        ],
    ),
]


def money(value: float) -> str:
    return f"{value:.2f}"


def party(tag: str, c: Company) -> str:
    contact = ""
    if c.contact or c.email:
        contact = "<cac:Contact>"
        if c.contact:
            contact += f"<cbc:Name>{escape(c.contact)}</cbc:Name>"
        if c.email:
            contact += f"<cbc:ElectronicMail>{escape(c.email)}</cbc:ElectronicMail>"
        contact += "</cac:Contact>"
    return f"""  <cac:{tag}>
    <cac:Party>
      <cbc:EndpointID schemeID="9948">{c.pib}</cbc:EndpointID>
      <cac:PartyName><cbc:Name>{escape(c.name)}</cbc:Name></cac:PartyName>
      <cac:PostalAddress>
        <cbc:StreetName>{escape(c.street)}</cbc:StreetName>
        <cbc:CityName>{escape(c.city)}</cbc:CityName>
        <cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>RS{c.pib}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity>
        <cbc:RegistrationName>{escape(c.name)}</cbc:RegistrationName>
        <cbc:CompanyID>{c.mb}</cbc:CompanyID>
      </cac:PartyLegalEntity>
      {contact}
    </cac:Party>
  </cac:{tag}>"""


def invoice_xml(number, date, supplier, buyer, account, lines) -> str:
    rendered, by_rate = [], {}
    for i, line in enumerate(lines, 1):
        net = round(line.qty * line.price, 2)
        by_rate[line.vat] = by_rate.get(line.vat, 0.0) + net
        description = f"<cbc:Description>{escape(line.description)}</cbc:Description>" if line.description else ""
        rendered.append(f"""  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="{line.unit}">{line.qty:g}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="RSD">{money(net)}</cbc:LineExtensionAmount>
    <cac:Item>
      {description}
      <cbc:Name>{escape(line.name)}</cbc:Name>
      <cac:SellersItemIdentification><cbc:ID>ART-{i:04d}</cbc:ID></cac:SellersItemIdentification>
      <cac:ClassifiedTaxCategory>
        <cbc:ID>S</cbc:ID>
        <cbc:Percent>{line.vat}</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="RSD">{money(line.price)}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")

    net_total = round(sum(by_rate.values()), 2)
    subtotals, tax_total = [], 0.0
    for rate, base in sorted(by_rate.items()):
        tax = round(base * rate / 100, 2)
        tax_total += tax
        subtotals.append(f"""    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="RSD">{money(base)}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="RSD">{money(tax)}</cbc:TaxAmount>
      <cac:TaxCategory>
        <cbc:ID>S</cbc:ID>
        <cbc:Percent>{rate}</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>""")
    gross = round(net_total + tax_total, 2)
    nl = "\n"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- IZMIŠLJENA FAKTURA ZA DEMONSTRACIJU. Sve firme, PIB-ovi, osobe i računi su izmišljeni. -->
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022</cbc:CustomizationID>
  <cbc:ID>{escape(number)}</cbc:ID>
  <cbc:IssueDate>{date}</cbc:IssueDate>
  <cbc:DueDate>{date[:8]}{int(date[8:]) + 15:02d}</cbc:DueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>
  <cac:InvoicePeriod><cbc:DescriptionCode>35</cbc:DescriptionCode></cac:InvoicePeriod>
{party("AccountingSupplierParty", supplier)}
{party("AccountingCustomerParty", buyer)}
  <cac:PaymentMeans>
    <cbc:PaymentMeansCode>30</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount><cbc:ID>{account}</cbc:ID></cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="RSD">{money(tax_total)}</cbc:TaxAmount>
{nl.join(subtotals)}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="RSD">{money(net_total)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="RSD">{money(net_total)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="RSD">{money(gross)}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="RSD">{money(gross)}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{nl.join(rendered)}
</Invoice>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, number, date, supplier, buyer, account, lines in INVOICES:
        (OUT / filename).write_text(invoice_xml(number, date, supplier, buyer, account, lines), encoding="utf-8")
        print(f"wrote {OUT / filename}")


if __name__ == "__main__":
    main()
