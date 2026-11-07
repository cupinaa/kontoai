from app.classifier import Classifier, ItemContext
from app.llm.base import LLMError
from app.models import InvoiceItem, Source
from tests.conftest import FakeLLM


def ctx(name: str, activity: str = "Razvoj softvera", supplier_pib: str | None = None, **item) -> ItemContext:
    return ItemContext(
        client_id="c1",
        client_activity=activity,
        item=InvoiceItem(name=name, supplier_pib=supplier_pib, **item),
    )


def make(chart, history, rules, llm) -> Classifier:
    return Classifier(chart=chart, history=history, rules=rules, llm=llm, review_threshold=0.75)


def test_history_has_priority_over_rules(classifier, history, fake_llm):
    history.add(client_id="c1", item_name="Evrodizel", konto="134")  # e.g. accountant decided it's goods
    result = classifier.classify(ctx("Evrodizel"))
    assert result.source is Source.HISTORY
    assert result.konto == "134"
    assert fake_llm.requests == []


def test_rule_is_used_before_llm(classifier, fake_llm):
    result = classifier.classify(ctx("Zakup poslovnog prostora"))
    assert result.source is Source.RULE
    assert result.konto == "533"
    assert result.konto_name == "Troškovi zakupnina"
    assert result.needs_review is False
    assert fake_llm.requests == []


def test_llm_is_called_only_for_unresolved_items(classifier, fake_llm):
    result = classifier.classify(ctx("Komunalne usluge - odvoz smeća"))
    assert result.source is Source.LLM
    assert result.konto == "539"
    assert result.confidence == 0.8
    assert result.needs_review is False
    assert len(fake_llm.requests) == 1
    request = fake_llm.requests[0]
    assert request.client_activity == "Razvoj softvera"
    assert {a.konto for a in request.accounts} >= {"513", "533", "539"}


def test_llm_account_outside_chart_is_rejected(chart, history, rules):
    llm = FakeLLM(konto="999", sigurnost=0.99)
    result = make(chart, history, rules, llm).classify(ctx("Nešto neobično"))
    assert result.konto is None
    assert result.source is Source.LLM
    assert result.confidence == 0.0
    assert result.needs_review is True
    assert "999" in result.explanation and "odbačen" in result.explanation


def test_llm_four_digit_subaccount_is_rejected(chart, history, rules):
    result = make(chart, history, rules, FakeLLM(konto="5130")).classify(ctx("Nešto"))
    assert result.konto is None and result.needs_review


def test_low_llm_confidence_is_flagged(chart, history, rules):
    result = make(chart, history, rules, FakeLLM(konto="512", sigurnost=0.4)).classify(ctx("Nešto"))
    assert result.konto == "512"
    assert result.needs_review is True


def test_confidence_is_clamped(chart, history, rules):
    result = make(chart, history, rules, FakeLLM(konto="512", sigurnost=1.7)).classify(ctx("Nešto"))
    assert result.confidence == 1.0


def test_llm_failure_flags_item(chart, history, rules):
    llm = FakeLLM(error=LLMError("timeout"))
    result = make(chart, history, rules, llm).classify(ctx("Nešto"))
    assert result.konto is None
    assert result.needs_review is True
    assert "timeout" in result.explanation


def test_without_llm_unresolved_items_need_review(chart, history, rules):
    result = make(chart, history, rules, None).classify(ctx("Nešto neobično"))
    assert result.source is Source.NONE
    assert result.konto is None
    assert result.needs_review is True


def test_llm_explanation_is_unmasked_for_the_accountant(chart, history, rules):
    llm = FakeLLM(konto="532", obrazlozenje="Usluga koju pruža [DOBAVLJAC_1] je održavanje.")
    result = make(chart, history, rules, llm).classify(
        ctx("Servis klima uređaja - Klima Tim", supplier_name="Klima Tim DOO")
    )
    assert "[DOBAVLJAC_1]" in llm.requests[0].item_text
    assert "Klima Tim" not in llm.requests[0].item_text
    assert "Klima Tim DOO" in result.explanation
