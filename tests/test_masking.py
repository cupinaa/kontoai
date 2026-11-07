import pytest

from app.classifier import ItemContext
from app.masking import Masker, mask_for_llm
from app.models import InvoiceItem


def test_supplier_name_and_variant_without_legal_form():
    masked, masker = mask_for_llm(
        "Isporuka od Biroprom Plus DOO; reklamacije: biroprom plus",
        supplier_name="Biroprom Plus DOO",
    )
    assert "Biroprom" not in masked and "biroprom" not in masked
    assert masked.count("[DOBAVLJAC_1]") == 2  # both variants map to the same placeholder
    assert masker.mapping["[DOBAVLJAC_1]"] == "Biroprom Plus DOO"


@pytest.mark.parametrize(
    "text, secret, label",
    [
        ("PIB dobavljača 123456789", "123456789", "[PIB_1]"),
        ("PIB: RS123456789", "123456789", "[PIB_1]"),
        ("MB 12345678", "12345678", "[MB_1]"),
        ("JMBG 0101990710123", "0101990710123", "[JMBG_1]"),
        ("Uplata na račun 160-0000000123456-78", "160-0000000123456-78", "[RACUN_1]"),
        ("Račun 160000000012345678", "160000000012345678", "[RACUN_1]"),
        ("IBAN RS35 1600 0000 0012 3456 78", "RS35 1600", "[RACUN_1]"),
        ("Pišite na prodaja@firma.example", "prodaja@firma.example", "[EMAIL_1]"),
        ("Pozovite 064/123-4567", "123-4567", "[TELEFON_1]"),
        ("Tel +381 11 3456789", "3456789", "[TELEFON_1]"),
    ],
)
def test_regex_identifiers_are_masked(text, secret, label):
    masked, _ = mask_for_llm(text)
    assert secret not in masked
    assert label in masked


@pytest.mark.parametrize(
    "text, name",
    [
        ("Laptop za zaposlenog Jovana Jovanovića", "Jovana Jovanovića"),
        ("Održavanje, kontakt: Milan Marković", "Milan Marković"),
        ("Dostava n/r Ana Petrović-Ilić", "Ana Petrović-Ilić"),
        ("Vozač Petar Petrović, putni nalog", "Petar Petrović"),
    ],
)
def test_person_names_after_markers_are_masked(text, name):
    masked, masker = mask_for_llm(text)
    assert name not in masked
    assert "[OSOBA_1]" in masked
    assert masker.mapping["[OSOBA_1]"] == name


def test_known_person_and_ids_from_invoice_are_masked_anywhere():
    masked, _ = mask_for_llm(
        "Odobrila Milica Savić, PIB 202000022, MB 22000022",
        supplier_pib="202000022",
        supplier_registration_number="22000022",
        person_names=["Milica Savić"],
    )
    assert "Milica" not in masked and "202000022" not in masked and "22000022" not in masked
    assert "[OSOBA_1]" in masked and "[PIB_1]" in masked and "[MB_1]" in masked


def test_same_value_gets_same_placeholder_and_unmask_restores_text():
    masker = Masker()
    original = "PIB 111111111 i PIB 222222222, ponovo 111111111"
    masked = masker.mask(original)
    assert masked == "PIB [PIB_1] i PIB [PIB_2], ponovo [PIB_1]"
    assert masker.unmask(masked) == original


@pytest.mark.parametrize(
    "text",
    [
        "Papir A4 80g, 500 listova",
        "Evrodizel 412.5 L",
        "Zakup poslovnog prostora za oktobar 2026",
        "Laptop Lenovo ThinkPad E14 Gen 6",
    ],
)
def test_ordinary_item_text_is_left_unchanged(text):
    masked, _ = mask_for_llm(text)
    assert masked == text


def test_classifier_sends_only_masked_data_to_llm(classifier, fake_llm):
    item = InvoiceItem(
        name="Laptop",
        description="Laptop za zaposlenog Jovana Jovanovića, Biroprom Plus, PIB 202000022",
        supplier_name="Biroprom Plus DOO",
        supplier_pib="202000022",
        amount=112000,
    )
    ctx = ItemContext(
        client_id="c1",
        client_activity="Razvoj softvera",
        item=item,
        supplier_registration_number="22000022",
        person_names=("Milica Savić",),
    )
    classifier.classify(ctx)

    assert len(fake_llm.requests) == 1
    sent = fake_llm.requests[0].model_dump_json()
    for secret in ("Jovana", "Jovanović", "Biroprom", "202000022"):
        assert secret not in sent
    assert "[OSOBA_1]" in sent and "[DOBAVLJAC_1]" in sent and "[PIB_1]" in sent
