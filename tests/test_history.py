from app.history import HistoryStore
from app.models import Source


def test_same_item_is_matched_with_high_confidence(history: HistoryStore):
    history.add(client_id="c1", item_name="Servis kombija", konto="532", supplier_pib="301000001")

    match = history.lookup("c1", "  SERVIS kombija ", supplier_pib=None, supplier_name=None)

    assert match is not None
    assert match.konto == "532"
    assert match.confidence >= 0.9


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
    match = history.lookup("c1", "Kukuruzno brašno", supplier_pib=None, supplier_name="MLIN ZITO doo")
    assert match is not None and match.konto == "101"


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
