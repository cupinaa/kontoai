from app.main import create_app
from fastapi.testclient import TestClient


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm"] == {"provider": "fake", "model": "fake-model"}
    assert body["accounts"] > 10
    assert body["chart_verified"] is False


def test_health_without_llm(settings):
    body = TestClient(create_app(settings, use_llm=False)).get("/health").json()
    assert body["llm"] is None


def test_accounts(client):
    accounts = client.get("/accounts").json()
    codes = {a["konto"] for a in accounts}
    assert {"513", "533", "023", "134"} <= codes
    assert all(len(c) == 3 for c in codes)


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "KontoAI" in response.text
    assert client.get("/static/app.js").status_code == 200


def test_logo_preview_and_static_assets(client):
    page = client.get("/logo-preview")
    assert page.status_code == 200 and "konto<b>ai</b>" in page.text
    for path in ("/static/brand/mascot_full.png", "/static/brand/mascot_head.png", "/static/brand/favicon-32.png",
                 "/static/brand/favicon-16.png", "/static/clients.json"):
        assert client.get(path).status_code == 200, path
    clients = client.get("/static/clients.json").json()
    assert clients[0]["id"] == "K001" and all(c["delatnost"] for c in clients)


def test_brand_assets_are_transparent_and_sized():
    from PIL import Image

    from app.config import BASE_DIR

    brand = BASE_DIR / "app" / "static" / "brand"
    for name in ("mascot_full.png", "mascot_head.png"):
        img = Image.open(brand / name)
        assert img.mode == "RGBA"
        assert img.getpixel((0, 0))[3] == 0  # corner is transparent background
        assert img.width >= 300
    assert Image.open(brand / "favicon-32.png").size == (32, 32)
    assert Image.open(brand / "favicon-16.png").size == (16, 16)


def test_index_has_no_developer_labels(client):
    html = client.get("/").text + client.get("/static/app.js").text
    for word in ("gemini", "LLM nije konfigurisan", "Jedina opcija", "tokens"):
        assert word not in html


def test_invoice_xml_upload(client, sample_bytes):
    response = client.post(
        "/invoices/xml",
        files={"file": ("f.xml", sample_bytes("03_zakup_poslovnog_prostora.xml"), "application/xml")},
        data={"client_activity": "Razvoj softvera po narudžbini"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_id"] == "102000002"  # defaults to buyer PIB
    assert body["invoice"]["number"] == "PCV-10/2026"
    assert len(body["items"]) == 4

    by_name = {r["item"]["name"]: r["suggestion"] for r in body["items"]}
    rent = by_name["Zakup poslovnog prostora za oktobar 2026"]
    assert rent["konto"] == "533" and rent["source"] == "rule"
    assert by_name["Električna energija - refakturisanje"]["konto"] == "513"
    assert by_name["Troškovi održavanja zajedničkih prostorija"]["source"] == "llm"
    for suggestion in by_name.values():
        assert set(suggestion) == {"konto", "konto_name", "source", "confidence", "explanation", "needs_review",
                                   "analytic", "given_konto", "given_konto_name", "given_check"}
        assert suggestion["analytic"] is None  # this sample client has no analytic plan
        assert suggestion["given_check"] is None  # no Iris account in this sample


def test_invoice_xml_explicit_client_id(client, sample_bytes):
    response = client.post(
        "/invoices/xml",
        files={"file": ("f.xml", sample_bytes("01_gorivo_kurirska_sluzba.xml"), "application/xml")},
        data={"client_activity": "Kurirske usluge", "client_id": "moj-klijent"},
    )
    assert response.json()["client_id"] == "moj-klijent"


def test_invoice_xml_rejects_bad_file(client):
    response = client.post(
        "/invoices/xml",
        files={"file": ("f.xml", b"<nope", "application/xml")},
        data={"client_activity": "IT"},
    )
    assert response.status_code == 400
    assert "XML" in response.json()["detail"]


def test_invoice_xml_requires_activity(client, sample_bytes):
    response = client.post(
        "/invoices/xml", files={"file": ("f.xml", sample_bytes("01_gorivo_kurirska_sluzba.xml"), "application/xml")}
    )
    assert response.status_code == 422


def test_invoice_json(client):
    response = client.post(
        "/invoices",
        json={
            "client_id": "c1",
            "client_activity": "Kurirske usluge",
            "supplier_name": "Benzinska stanica Kosmaj DOO",
            "supplier_pib": "201000011",
            "items": [{"name": "Evrodizel", "quantity": 100, "unit": "LTR", "amount": 17250}, {"name": "Nešto"}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"][0]["suggestion"]["konto"] == "513"
    assert body["items"][0]["item"]["supplier_pib"] == "201000011"  # inherited from the invoice level
    assert body["items"][1]["suggestion"]["source"] == "llm"


def test_invoice_json_validation(client):
    assert client.post("/invoices", json={"client_id": "c1", "client_activity": "IT", "items": []}).status_code == 422


def test_confirm_and_history_learning_loop(client, fake_llm):
    payload = {"client_id": "c1", "client_activity": "Pekara", "items": [{"name": "Kvasac svež 1kg"}]}
    first = client.post("/invoices", json=payload).json()["items"][0]["suggestion"]
    assert first["source"] == "llm" and first["konto"] == "539"

    confirm = client.post(
        "/confirm",
        json={"client_id": "c1", "item_name": "Kvasac svež 1kg", "konto": "101",
              "suggested_konto": first["konto"], "suggested_source": first["source"]},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "corrected"
    assert confirm.json()["record"]["konto_name"] == "Materijal"

    calls_before = len(fake_llm.requests)
    second = client.post("/invoices", json=payload).json()["items"][0]["suggestion"]
    assert second["source"] == "history"
    assert second["konto"] == "101"
    assert second["needs_review"] is False
    assert len(fake_llm.requests) == calls_before  # learned: no LLM call this time

    history = client.get("/history/c1").json()
    assert len(history) == 1
    assert history[0]["corrected"] is True and history[0]["suggested_source"] == "llm"
    assert client.get("/history/someone-else").json() == []


def test_confirm_accepts_matching_suggestion(client):
    response = client.post(
        "/confirm",
        json={"client_id": "c1", "item_name": "Evrodizel", "konto": "513", "suggested_konto": "513",
              "suggested_source": "rule"},
    )
    assert response.json()["status"] == "confirmed"


def test_confirm_rejects_unknown_account(client):
    response = client.post("/confirm", json={"client_id": "c1", "item_name": "X", "konto": "999"})
    assert response.status_code == 422
    assert client.post("/confirm", json={"client_id": "c1", "item_name": "X", "konto": "51"}).status_code == 422
