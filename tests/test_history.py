import pytest

from app.history import HistoryStore
from app.models import Source


def test_same_item_is_matched_with_high_confidence(history: HistoryStore):
    history.add(client_id="c1", item_name="Servis kombija", konto="532", supplier_pib="301000001")

    match = history.lookup_item("c1", "  SERVIS kombija ", supplier_pib="301000001", supplier_name=None)

    assert match is not None
    assert match.konto == "532"
    assert match.confidence >= 0.9


def test_item_history_requires_the_same_supplier(history: HistoryStore):
    history.add(client_id="c1", item_name="Servis kombija", konto="532", supplier_pib="301000001")
    assert history.lookup_item("c1", "Servis kombija", supplier_pib="999999999", supplier_name=None) is None
    assert history.lookup_item("c1", "Servis kombija", supplier_pib=None, supplier_name=None) is None


def test_similar_description_of_the_same_supplier_is_matched(history: HistoryStore):
    history.add(client_id="c1", item_name="Zakup poslovnog prostora za novembar 2026", konto="533",
                supplier_pib="203000033")
    match = history.lookup_item("c1", "Zakup poslovnog prostora za decembar 2026", "203000033", None)
    assert match is not None and match.konto == "533"
    assert match.confidence == 0.90 and "Slična stavka" in match.explanation
    # a different kind of rent from the same landlord is NOT similar
    assert history.lookup_item("c1", "Zakup magacinskog prostora za gotove proizvode", "203000033", None) is None


@pytest.mark.parametrize(
    "a, b, similar",
    [
        ("Brašno T-500 25kg", "Brašno T-400 25kg", True),
        ("Internet 500 Mbps - oktobar", "Internet 500 Mbps - novembar", True),
        ("Zakup poslovnog prostora", "Zakup magacinskog prostora", False),
        ("Električna energija - refakturisanje", "Zakup magacinskog prostora za gotove proizvode", False),
        ("Usluga", "Usluga hostinga", False),
    ],
)
def test_similarity(a, b, similar):
    from app.history import SIMILARITY_THRESHOLD, similarity

    assert (similarity(a, b) >= SIMILARITY_THRESHOLD) is similar


def test_supplier_match_when_item_is_new(history: HistoryStore):
    history.add(client_id="c1", item_name="Mleko 1L", konto="134", supplier_pib="301000003")
    history.add(client_id="c1", item_name="Sir 1kg", konto="134", supplier_pib="301000003")

    match = history.lookup("c1", "Jogurt 1kg", supplier_pib="301000003", supplier_name=None)

    assert match is not None
    assert match.konto == "134"
    assert 0.75 <= match.confidence < 0.95
    assert "dobavljača" in match.explanation


def test_supplier_match_by_name_without_pib(history: HistoryStore):
    history.add(client_id="c1", item_name="Brašno", konto="101", supplier_name="Mlin Žito DOO")
    history.add(client_id="c1", item_name="Kvasac", konto="101", supplier_name="Mlin Žito DOO")
    match = history.lookup_supplier("c1", supplier_pib=None, supplier_name="MLIN ZITO doo")
    assert match is not None and match.konto == "101"


def test_single_supplier_confirmation_is_not_enough(history: HistoryStore):
    history.add(client_id="c1", item_name="Zakup magacina", konto="533", supplier_pib="203000033")
    assert history.lookup_supplier("c1", "203000033", None) is None


def test_supplier_ever_on_two_accounts_is_never_used(history: HistoryStore):
    for name in ("Zakup 1", "Zakup 2", "Zakup 3"):
        history.add(client_id="c1", item_name=name, konto="533", supplier_pib="203000033")
    history.add(client_id="c1", item_name="Struja", konto="513", supplier_pib="203000033")
    # 3 of 4 on 533 is not enough: once a supplier is seen on two accounts, supplier history is off
    assert history.lookup_supplier("c1", "203000033", None) is None


def test_inconsistent_supplier_is_not_used(history: HistoryStore):
    for konto in ("134", "512", "531"):
        history.add(client_id="c1", item_name=f"Stavka {konto}", konto=konto, supplier_pib="999999999")

    assert history.lookup("c1", "Nova stavka", supplier_pib="999999999", supplier_name=None) is None


def test_history_is_isolated_per_client(history: HistoryStore):
    history.add(client_id="c1", item_name="Evrodizel", konto="513")
    assert history.lookup("c2", "Evrodizel", None, None) is None


def test_latest_confirmation_wins_after_correction(history: HistoryStore):
    history.add(client_id="c1", item_name="Monitor 27", konto="023")
    history.add(client_id="c1", item_name="Monitor 27", konto="103")

    match = history.lookup("c1", "Monitor 27", None, None)
    assert match.konto == "103"
    assert match.confidence < 0.95  # mixed past decisions lower the confidence


def test_add_records_correction_flag_and_list(history: HistoryStore):
    first = history.add(client_id="c1", item_name="A", konto="513", suggested_konto="513",
                        suggested_source=Source.RULE)
    second = history.add(client_id="c1", item_name="B", konto="533", suggested_konto="539",
                         suggested_source=Source.LLM)

    assert first.corrected is False
    assert second.corrected is True
    records = history.list("c1")
    assert [r.item_name for r in records] == ["B", "A"]  # newest first
    assert records[0].suggested_source is Source.LLM
    assert history.list("other") == []
