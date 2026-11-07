# KontoAI

[![CI](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml/badge.svg)](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml)

KontoAI suggests an account from the Serbian chart of accounts (*kontni okvir*) for every line item of an incoming e-invoice. The accountant then confirms or corrects each suggestion, and the system learns from those decisions.

> ⚠️ **The chart of accounts in this repository has not been verified.** [`data/kontni_okvir.json`](data/kontni_okvir.json) is a hand-picked subset of 3-digit accounts from the *Pravilnik o kontnom okviru i sadržini računa u kontnom okviru za privredna društva, zadruge i preduzetnike* (Sl. glasnik RS 89/2020). A licensed accountant must review it before any real use. The same applies to the expected accounts in the evaluation dataset.

## The problem

Since the introduction of SEF (*Sistem e-faktura*), incoming invoices arrive as structured UBL 2.1 XML, so nobody has to retype them. Posting them still has to be done by hand. For every line (fuel, rent, a laptop, goods for resale…) the accountant decides which account it belongs to, and that decision depends on what the client's business does. Fuel is an expense (513) for a courier company, but it is goods for resale (134) for a petrol station.

Most of this work repeats: the same suppliers and the same items come in every month. KontoAI handles the repeated and obvious cases automatically. It sends only the genuinely new items to an LLM, and the accountant always makes the final call.

## How it works

```mermaid
flowchart LR
    A[SEF UBL 2.1 XML<br/>or JSON] --> B[Parse invoice<br/>items, supplier, PIB]
    B --> C{Client history<br/>same item / supplier?}
    C -- match --> R[Suggestion]
    C -- no --> D{Keyword rules<br/>fuel, rent, power, telecom...}
    D -- match --> R
    D -- no / ambiguous --> E[Mask identifying data<br/>supplier, PIB, MB, accounts, names]
    E --> F[LLM - Gemini<br/>structured JSON output]
    F --> G{Validate:<br/>account in chart?}
    G -- yes --> R
    G -- no --> H[Reject, flag for<br/>manual review]
    H --> R
    R --> I[Accountant confirms<br/>or corrects]
    I -- saved to history --> C
```

Every item goes through the stages in order and stops at the first one that decides:

| # | Stage | Confidence | Notes |
|---|---|---|---|
| 1 | **Client history** (SQLite) | 0.95 same item, 0.80–0.85 same supplier | Uses only decisions this client's accountant has already confirmed. A supplier that was posted to different accounts in the past (less than 80% agreement) is ignored. |
| 2 | **Keyword rules** ([`data/rules.json`](data/rules.json)) | 0.88–0.92 | Text is normalised (lowercase, no diacritics, Cyrillic converted to Latin). Rules can exclude keywords (*filter goriva*) and client activities (fuel at a petrol station). When two rules point to different accounts, the item goes to the LLM. |
| 3 | **LLM** (Gemini) | from the model | Gets only the masked item text, the client's activity and the list of allowed accounts. Output is constrained by a JSON schema. |
| 4 | **Validation** | — | An account that is not in the chart is rejected and the item is flagged. The schema `enum` already restricts the model; the validation is a second layer that applies to any provider. |

Every result contains `konto`, `konto_name`, `source` (`history` / `rule` / `llm` / `none`), `confidence`, `explanation` (in Serbian) and `needs_review`. `needs_review` is true when confidence is below `REVIEW_THRESHOLD` (default 0.75) or when there is no suggestion.

`POST /confirm` stores the accountant's decision. The next invoice with the same item or supplier is resolved from history, without an LLM call.

## Architecture

```
app/
  main.py          FastAPI app and endpoints (create_app factory)
  service.py       wiring: builds the classifier, runs whole invoices
  classifier.py    the pipeline: history -> rules -> masking -> LLM -> validation
  sef_parser.py    UBL 2.1 Invoice / CreditNote parser (defusedxml, XXE-safe)
  history.py       SQLite store of confirmed postings, per client
  rules.py         keyword rule engine
  masking.py       masking of identifying data before the LLM call
  chart.py         chart of accounts (the allowed list)
  text.py          normalisation (diacritics, Cyrillic -> Latin)
  llm/base.py      LLMProvider interface, prompt, structured output model
  llm/gemini.py    GeminiProvider (google-genai SDK)
  static/          web page (plain HTML/CSS/JS)
data/
  kontni_okvir.json   allowed accounts (UNVERIFIED)
  rules.json          keyword rules
  samples/            5 fictional SEF invoices
  eval/dataset.json   30 labelled fictional items
scripts/
  evaluate.py         evaluation report -> eval_results.md
  make_samples.py     regenerates data/samples
tests/                pytest suite, Gemini mocked
```

**Swappable model.** The application only uses the `LLMProvider` interface ([`app/llm/base.py`](app/llm/base.py)). Switching to another model or vendor means adding one subclass that implements `suggest()`. The rest of the code stays the same. The Gemini model name and API key come from `.env` (`GEMINI_MODEL`, `GEMINI_API_KEY`). The default is `gemini-3.6-flash`, the current stable Flash model listed in the Gemini API documentation.

## Data privacy

- Before the LLM call, [`app/masking.py`](app/masking.py) replaces identifying data with placeholders:
  - **Known entities from the invoice:** the supplier name (with and without the legal form, e.g. *Biroprom Plus DOO* / *Biroprom Plus*), PIB, matični broj and contact persons.
  - **Regex detection:** bank accounts and IBANs, JMBG, PIB, matični broj, e-mail addresses, phone numbers, and person names introduced by markers such as *kontakt:*, *n/r*, *vozač*, *za zaposlenog*.
- The model receives only the masked item description, the client's activity, quantity and amount. Supplier identity, the client's name and the client's PIB are never sent.
- The mapping from placeholder back to the real value stays in memory on our side. It is used only to unmask the model's explanation for the accountant.
- Example of what Gemini sees:
  `Laptop Lenovo ThinkPad E14 Gen 6, za zaposlenog [OSOBA_1]`
- XML is parsed with `defusedxml`, so DTD and entity attacks (XXE, "billion laughs") are rejected.
- `.env`, the SQLite database and local key files are listed in `.gitignore`.

Masking is pattern-based. It covers the identifiers listed above, but it cannot recognise every possible personal name in free text. This is listed under [limitations](#limitations).

## Evaluation

`scripts/evaluate.py` runs the 30 items in [`data/eval/dataset.json`](data/eval/dataset.json) through the full pipeline. History is seeded into a temporary database, so the real one is never touched. The script reports overall accuracy, accuracy by decision source, the number of items flagged for review and the average time per item. The full report is in [`eval_results.md`](eval_results.md).

Latest run (history + rules only, no LLM key configured):

| Source | Items | Accuracy |
|---|---|---|
| history | 6 | 100% |
| rules | 12 | 100% |
| not decided (would go to the LLM) | 12 | — (all 12 flagged for review) |
| **Overall** | **30** | **60%**, and 100% of the auto-accepted items were correct |

Average time per item without the LLM is about 0.5 ms.

How to read these numbers:
- The dataset is small and fictional. Its history and rule items were written together with the rules, so 100% on those paths shows that the pipeline is wired correctly. It does not measure real-world accuracy.
- The 12 LLM items are the hard cases. They include fuel bought by a petrol station (goods, not an expense), a laptop as a fixed asset, entertainment of business partners, and memberships.
- To measure the LLM path, set `GEMINI_API_KEY` and run `python scripts/evaluate.py`.

## Running locally (Windows / PowerShell)

Requires Python 3.12+ (developed and tested on 3.14).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env     # then put your GEMINI_API_KEY into .env
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the web page, or http://localhost:8000/docs for the interactive API docs. Without an API key the app still runs, using history and rules only; unresolved items are flagged for review.

Tests and evaluation:

```powershell
pytest
python scripts/evaluate.py            # add --no-llm to skip Gemini
```

## Running with Docker

```bash
docker build -t kontoai .
docker run --rm -p 8000:8000 --env-file .env -v kontoai-data:/data kontoai
```

The SQLite history is stored in the `/data` volume.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, configured LLM, number of accounts |
| GET | `/accounts` | Allowed chart of accounts |
| POST | `/invoices/xml` | Multipart upload of a SEF XML (`file`, `client_activity`, optional `client_id`; defaults to the buyer's PIB) |
| POST | `/invoices` | The same, with items as JSON |
| POST | `/confirm` | Confirm or correct the account for one item; saved to the client's history |
| GET | `/history/{client_id}` | Confirmed postings for a client, newest first |

Upload a SEF XML:

```bash
curl -F "file=@data/samples/01_gorivo_kurirska_sluzba.xml" \
     -F "client_activity=Kurirske usluge i dostava paketa" \
     http://localhost:8000/invoices/xml
```

JSON input:

```bash
curl -X POST http://localhost:8000/invoices -H "Content-Type: application/json" -d '{
  "client_id": "101000001",
  "client_activity": "Kurirske usluge i dostava paketa",
  "supplier_name": "Benzinska stanica Kosmaj DOO",
  "supplier_pib": "201000011",
  "items": [{"name": "Evrodizel", "quantity": 412.5, "unit": "LTR", "amount": 71156.25}]
}'
```

Response (shortened):

```json
{
  "client_id": "101000001",
  "items": [{
    "item": {"name": "Evrodizel", "quantity": 412.5, "amount": 71156.25, "supplier_pib": "201000011"},
    "suggestion": {
      "konto": "513",
      "konto_name": "Troškovi goriva i energije",
      "source": "rule",
      "confidence": 0.9,
      "explanation": "Pravilo 'gorivo' (ključna reč: 'evrodizel'). Gorivo za sopstvenu upotrebu knjiži se kao trošak goriva i energije.",
      "needs_review": false
    }
  }],
  "needs_review_count": 0
}
```

Confirm or correct:

```bash
curl -X POST http://localhost:8000/confirm -H "Content-Type: application/json" -d '{
  "client_id": "101000001", "item_name": "Evrodizel", "konto": "513",
  "supplier_pib": "201000011", "suggested_konto": "513", "suggested_source": "rule"
}'
```

The response `status` is `confirmed` if the accountant accepted the suggestion and `corrected` if they chose a different account.

## Tests

`pytest` runs 92 tests covering XML parsing (including XXE rejection), rules, history, masking, rejection of accounts outside the chart, the Gemini provider (against a fake SDK client) and all API endpoints, including the confirm-and-learn loop. Gemini is mocked everywhere: the tests need neither internet access nor an API key, and a fixture fails any test that tries to create a real client. GitHub Actions runs the suite on every push.

## Limitations

- **The chart of accounts must be verified.** It is a partial list of 3-digit accounts relevant to incoming invoices (classes 0, 1 and 5), taken from Sl. glasnik RS 89/2020. Intangible assets (e.g. software licences), 4+ digit analytic accounts and client-specific account plans are not included.
- **VAT is not handled.** The system suggests the cost/asset account for the net amount. Input VAT (*prethodni porez*, group 27), the supplier account (435) and the full posting entry are out of scope.
- **Accounting policy matters.** Whether a laptop is a fixed asset (023) or small inventory, and whether goods are booked at wholesale or retail, depends on the client's policy. The system cannot know this until the accountant confirms a few decisions.
- **Masking is pattern-based.** Names that appear without a marker word in free text may not be detected. In production this should be combined with an NER model and a review of what is sent.
- **Fictional evaluation data.** The 30-item dataset is small, fictional, and its expected accounts have not been verified by an accountant.
- **Prototype scope.** There is no authentication or multi-user access control, history matching is exact (no fuzzy matching), and items are sent to the LLM one at a time.

## Possible next steps

- Fuzzy and embedding-based history matching (e.g. "Brašno T-500" ↔ "Brašno T-400").
- Batch LLM calls per invoice; caching of identical masked items.
- Full posting proposal including VAT and the supplier account.
- Import of a client's own account plan and accounting policy (fixed-asset threshold).
- Authentication, audit log and an export for accounting software.
