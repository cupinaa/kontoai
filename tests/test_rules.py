import pytest

from app.config import DATA_DIR
from app.rules import RuleEngine
from app.text import normalize


@pytest.mark.parametrize(
    "text, konto",
    [
        ("Evrodizel", "513"),
        ("BMB 95", "513"),
        ("Gorivo za službeno vozilo", "513"),
        ("Električna energija za oktobar", "513"),
        ("Elektricna energija", "513"),
        ("Електрична енергија", "513"),  # Cyrillic
        ("Zakup poslovnog prostora", "533"),
        ("Zakupnina za magacin", "533"),  # stem match
        ("Mobilna telefonija - pretplata", "531"),
        ("Internet 500 Mbps", "531"),
        ("Toner HP 85A", "512"),
        ("Kancelarijski materijal", "512"),
        ("Provizija banke za platni promet", "553"),
        ("Polisa osiguranja vozila", "552"),
        ("Knjigovodstvene usluge", "550"),
        ("Reklamni bilbordi", "535"),
    ],
)
def test_obvious_items_match_rule(rules, text, konto):
    match = rules.match(text, "Razvoj softvera")
    assert match is not None, text
    assert match.rule.konto == konto
    assert match.explanation


@pytest.mark.parametrize("text", ["Laptop Dell Latitude", "Kvasac svež 1kg", "Popravka peći", "Kafa u zrnu"])
def test_unknown_items_do_not_match(rules, text):
    assert rules.match(text, "Proizvodnja hleba") is None


def test_activity_exclusion_fuel_for_petrol_station(rules):
    # For a petrol station fuel is goods for resale, not an expense: the rule must step aside.
    assert rules.match("Evrodizel", "Kurirske usluge").rule.konto == "513"
    assert rules.match("Evrodizel", "Trgovina na malo motornim gorivima") is None


def test_exclude_keywords(rules):
    assert rules.match("Filter goriva", "Kurirske usluge") is None
    assert rules.match("Mobilni telefon uređaj", "IT") is None
    assert rules.match("Lizing - zakup vozila", "IT") is None


def test_conflicting_rules_are_left_to_llm(rules):
    assert rules.match("Zakup prostora i električna energija", "IT") is None


def test_same_account_from_two_rules_is_not_a_conflict(rules):
    match = rules.match("Gorivo i električna energija", "IT")
    assert match is not None and match.rule.konto == "513"


def test_keywords_match_only_at_word_start(rules):
    # 'tng' must not match inside another word
    assert rules.match("Ekstenger kabl", "IT") is None


def test_normalize():
    assert normalize("  Električna ENERGIJA, 1kW!  ") == "elektricna energija 1kw"
    assert normalize("Ђурђевак") == "djurdjevak"
    assert normalize(None) == ""


# ---------------------------------------------------------------- a specific rule wins over a general one

@pytest.mark.parametrize("text, rule_id, konto", [
    ("zakup sajamskog prostora", "sajam", "534"),
    ("Zakup štanda na sajmu hrane", "sajam", "534"),
    ("Zakup reklamnog bilborda za oktobar", "reklama", "535"),
    ("Osiguranje zakupljenog magacina", "osiguranje", "552"),
    ("Zakup poslovnog prostora", "zakup", "533"),
])
def test_specific_rule_wins_over_general_rent_rule(text, rule_id, konto):
    match = RuleEngine.load(DATA_DIR / "rules.json").match(text)
    assert match is not None and (match.rule.id, match.rule.konto) == (rule_id, konto)


def test_equally_specific_rules_that_disagree_still_go_to_the_llm():
    engine = RuleEngine.load(DATA_DIR / "rules.json")
    assert engine.match("Zakup poslovnog prostora i struja") is None
    assert engine.match("Polisa osiguranja i reklama") is None


def test_trade_fair_organiser_is_not_caught_by_the_fair_rule():
    match = RuleEngine.load(DATA_DIR / "rules.json").match("Zakup sajamskog prostora", "organizacija sajmova")
    assert match is not None and match.rule.id == "zakup"  # for a fair organiser it is ordinary rent
