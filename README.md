# KontoAI

[![CI](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml/badge.svg)](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml)

KontoAI helps an accountant post incoming e-invoices. For every line item it proposes the **analytic account** (the 4th digit and beyond) from the client's own chart of accounts. If needed, it also proposes the 3-digit synthetic account from the Serbian chart of accounts (*kontni okvir*). The accountant confirms or corrects each suggestion with one click, and the system learns from those confirmations.

> ⚠️ **Two data files in this repository are not verified and are temporary.**
> - [`data/kontni_okvir.json`](data/kontni_okvir.json) is a hand-picked subset of 3-digit accounts from the *Pravilnik o kontnom okviru* (Sl. glasnik RS 89/2020), and it still needs an accountant's sign-off.
> - [`data/analiticki_plan.json`](data/analiticki_plan.json) is a **trial analytic plan**. It was built from the accountant's own review answers and **will be replaced by the export from the accounting software (Iris)**.

## The problem

Since the introduction of SEF (*Sistem e-faktura*), incoming invoices arrive as structured UBL 2.1 XML, so nobody has to retype them. The accountant's software (in our case Iris) already proposes the **3-digit synthetic account** for each line.

**The hard part is the analytic level.** The fourth digit (e.g. 533**0** office rent vs. 533**1** warehouse rent) is not prescribed by the Pravilnik. Every company defines its own analytic chart of accounts, so a generic rule cannot know it. Choosing the analytic account means remembering how *this* client posts *this* supplier and *this* kind of item. The accountant does it by hand, line by line, every month.

KontoAI focuses on that step:
- **Learning from confirmations.** An analytic account the accountant confirmed once is suggested again for the same item or the same supplier.
- **Offering only valid choices.** It offers only the analytic accounts that exist in the client's plan below the chosen 3-digit account.
- **LLM only where needed.** It asks an LLM only when there is no history and the plan has several options.
- **The accountant decides.** When it is not sure, it preselects nothing and leaves the choice to the accountant.

The synthetic step (history → rules → LLM) is still available. It is used when the 3-digit account is not supplied with the item, for example for invoices coming directly from SEF.

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
    A -. 3-digit account given<br/>e.g. by Iris .-> R
    R[3-digit account] --> P{Client's analytic plan:<br/>accounts below it}
    P -- none --> X[Flag: no analytic<br/>below this account]
    P -- options --> AH{History: same item<br/>or same supplier?}
    AH -- match --> S[Analytic suggestion]
    AH -- no --> AO{Only one option?}
    AO -- yes --> S
    AO -- no --> AL[LLM chooses from<br/>the offered list only]
    AL --> AV{In the list and<br/>confident enough?}
    AV -- yes --> S
    AV -- no --> AK[Nothing preselected:<br/>accountant chooses]
    S --> I[Accountant confirms<br/>or corrects - one click]
    AK --> I
    I -- saved to history --> AH
    I -- saved to history --> C
```

### Synthetic (3-digit) account

If the item already carries a 3-digit account (`given_konto`, e.g. proposed by Iris), this step is skipped and the account is used as given (`source: input`). Otherwise every item goes through the stages in order and stops at the first one that decides:

| # | Stage | Confidence | Notes |
|---|---|---|---|
| 1 | **Client history** (SQLite) | 0.95 same item, 0.80–0.85 same supplier | Uses only decisions this client's accountant has already confirmed. A supplier that was posted to different accounts in the past (less than 80% agreement) is ignored. |
| 2 | **Keyword rules** ([`data/rules.json`](data/rules.json)) | 0.88–0.92 | Text is normalised (lowercase, no diacritics, Cyrillic converted to Latin). Rules can exclude keywords (*filter goriva*) and client activities (fuel at a petrol station). When two rules point to different accounts, the item goes to the LLM. |
| 3 | **LLM** (Gemini) | from the model | Gets only the masked item text, the client's activity and the list of allowed accounts. Output is constrained by a JSON schema. |
| 4 | **Validation** | — | An account that is not in the chart is rejected and the item is flagged. The schema `enum` already restricts the model; the validation is a second layer that applies to any provider. |

Every result contains these fields:
- `konto`, `konto_name`;
- `source`: `input`, `history`, `rule`, `llm` or `none`;
- `confidence`, `explanation` (in Serbian) and `needs_review`.

`needs_review` is true when confidence is below `REVIEW_THRESHOLD` (default 0.75) or when there is no suggestion.

### Analytic (4th-digit) account

After the 3-digit account is known, KontoAI looks only at the client's analytic accounts below it. For example, for 533 it offers 5330 and 5331, and never 5340. Then:

| # | Step | Confidence | Notes |
|---|---|---|---|
| 1 | **Client history** | 0.95 same item, 0.80–0.85 same supplier | A confirmed analytic account counts only for the same 3-digit account. |
| 2 | **Only one option** | 0.90 | The plan has exactly one analytic account below the 3-digit one, so there is nothing to choose and no LLM call is made. |
| 3 | **LLM** | from the model | Gets the masked item text, the client's activity and *only the offered options*; the JSON schema `enum` contains just those codes. |
| 4 | **Validation** | — | An answer outside the offered list is rejected. If the model's confidence is below the threshold, nothing is preselected; the model's closest guess appears in the explanation. |

The result is in `suggestion.analytic`: `konto`, `naziv`, `source` (`history` / `only_option` / `llm` / `none`), `confidence`, `explanation`, `needs_review` and `options`, the full list for the dropdown. If the client has no analytic plan, `suggestion.analytic` is `null`.

`POST /confirm` stores the accountant's decision at both levels. The next invoice with the same item or supplier gets the correct 3-digit and analytic accounts straight from history, without an LLM call.

## Architecture

```
app/
  main.py          FastAPI app and endpoints (create_app factory)
  service.py       wiring: builds the classifier, runs whole invoices
  classifier.py    the pipeline: synthetic (history -> rules -> LLM) and analytic (history -> only option -> LLM)
  analytic.py      per-client analytic plan and the CSV/XLSX importer
  sef_parser.py    UBL 2.1 Invoice / CreditNote parser (defusedxml, XXE-safe)
  history.py       SQLite store of confirmed postings (3-digit and analytic), per client
  rules.py         keyword rule engine
  masking.py       masking of identifying data before the LLM call
  chart.py         chart of accounts (the allowed list)
  text.py          normalisation (diacritics, Cyrillic -> Latin)
  llm/base.py      LLMProvider interface, prompt, structured output model
  llm/gemini.py    GeminiProvider (google-genai SDK)
  static/          web page (plain HTML/CSS/JS)
data/
  kontni_okvir.json     allowed 3-digit accounts (UNVERIFIED)
  analiticki_plan.json  per-client analytic plan (TRIAL, to be replaced by the Iris export)
  rules.json            keyword rules
  samples/              5 fictional SEF invoices
  eval/                 dataset.json (50 synthetic items), knjigovodja.json (accountant's items)
  review/               Excel files for the accountant, her answers, import report, decisions
scripts/
  evaluate.py             evaluation report -> eval_results.md
  review.py               accountant review: generate / import / predictions
  import_analytic_plan.py import a client's analytic plan from CSV/XLSX
  make_samples.py         regenerates data/samples
tests/                  pytest suite, Gemini mocked
```

**Swappable model.** The application only uses the `LLMProvider` interface ([`app/llm/base.py`](app/llm/base.py)). Switching to another model or vendor means adding one subclass that implements `suggest()` and, for the analytic step, `choose_analytic()`. The rest of the code stays the same. The Gemini model name and API key come from `.env` (`GEMINI_MODEL`, `GEMINI_API_KEY`). The default is `gemini-3.6-flash`, the current stable Flash model listed in the Gemini API documentation.

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

## Analytic chart of accounts

> [!IMPORTANT]
> **The analytic plan in this repository is a temporary trial version.** [`data/analiticki_plan.json`](data/analiticki_plan.json) contains client `K001` (*proizvodnja dijetetskih proizvoda*) with 17 analytic accounts:
> - Every account is one that the accountant wrote in the two review files. The account names were derived from her item descriptions and notes.
> - Every entry is marked `"probni": true`, and the web page shows a notice for this client.
> - Account 5590 was left out, because that item is waiting for her correction.
> - The real analytic plan will come as an export from the accounting software (Iris), and the trial version will then be replaced.

Import a plan from CSV or XLSX:

```powershell
python scripts/import_analytic_plan.py plan.xlsx --client-id K001 --dry-run
python scripts/import_analytic_plan.py plan.csv --client-id K001 `
    --konto-column "Šifra" --naziv-column "Naziv" --encoding cp1250 --delimiter ";"
```

The Iris export format is not known yet, so the importer does **not** assume one.

How the importer reads the file:
- **Columns:** the account and name columns can be given by header name or by column number (`--konto-column 2`). You can also set the header row, the sheet, the CSV delimiter and the encoding.
- **Skipped rows:** rows with fewer than four digits (synthetic accounts), rows without a name and duplicates are skipped and listed.
- **Unknown 3-digit accounts:** if a 3-digit parent account is not in the chart, the importer prints a warning.
- **Replacing a plan:** the client's plan is replaced, and other clients are kept. Always run `--dry-run` first.

**No accuracy number is published for the analytic step.** The trial plan was built from the same answers of the accountant that an evaluation would compare against, so it would be grading itself. The real evaluation of the analytic step will be done when the Iris plan arrives, on postings that were not used to build the plan.

## Evaluation

The numbers below are for the **synthetic (3-digit) step**.

> [!WARNING]
> **The evaluation dataset is synthetic, and its expected accounts are not verified.** I wrote the 50 items, their expected accounts and the keyword rules myself. A high score on this dataset is therefore **not** a measure of real accuracy. In particular, the 100% on the easy history and rule items is true by construction. The expected accounts still need to be verified by an accountant. A real measurement needs invoices and confirmed postings from an accounting office.

`scripts/evaluate.py` runs [`data/eval/dataset.json`](data/eval/dataset.json) through the full pipeline. History is seeded into a temporary database, so the real one is never touched. The full report is in [`eval_results.md`](eval_results.md). The dataset has two parts:

- **30 easy items.** The descriptions are clear. Their history and rule items were written together with the rules.
- **20 hard items.** These were written after the rules, and the rules were not changed to fit them. There are four kinds:
  - ambiguous descriptions (*"Usluga"*, *"Materijal po ugovoru br. 14/2026"*, *"Roba po otpremnici 4471"*);
  - abbreviations as they appear on invoices (*"EURO DIZ."*, *"Usl. odrz. SW 10/26"*, *"Tr. PP za 10/26"*);
  - items whose account depends on the client's activity. For example, the same *"Laptop HP 250 G9"* is a fixed asset (023) for a grocery store but goods for resale (134) for a computer shop. Fuel for a petrol station's own car is an expense (513), not goods;
  - items that no rule covers (subcontracted works, trade-fair stand, translation, training).

Besides accuracy, the report counts **silent errors**: wrong accounts that were *not* flagged for review. This is the number that matters most. A flagged mistake costs the accountant one click, but a silent one ends up in the books.

### Results

The run was made once, on `gemini-3.6-flash`, for all 50 items (2026-11-07, paid tier, `--max-calls 40`):

| Group | Items | Correct | Flagged for review | Silent errors |
|---|---|---|---|---|
| Easy | 30 | 30 (100%) | 0 | 0 |
| Hard | 20 | 19 (95%) | 4 | 0 |
| **All** | **50** | **49 (98%)** | **4** | **0** |

Hard items by category:

| Category | Items | Correct | Flagged |
|---|---|---|---|
| Ambiguous description | 5 | 4 | 4 |
| Invoice abbreviation | 4 | 4 | 0 |
| Depends on client activity | 6 | 6 | 0 |
| Not covered by any rule | 5 | 5 | 0 |

By decision source: history decided 6/6 items correctly, rules 12/12, and the LLM 31/32.

What the numbers show, within the limits of a synthetic dataset:
- **No silent errors.** The only wrong suggestion was flagged for review. That item was #33 *"Usluge po ugovoru za oktobar"*: the expected account was 539, Gemini proposed 530 with confidence 0.65 and explained that the description is too general.
- **The model is uncertain where it should be.** Four of the five ambiguous items received a confidence of 0.35–0.65 and went to manual review. The exception was *"Roba po otpremnici 4471"*, which got 0.95. The answer was right, but such a vague description deserved a lower confidence.
- **Activity-dependent items were all correct.** These items are the main reason for using an LLM here. Examples:
  - the same laptop is a fixed asset (023) for a grocery store but goods for resale (134) for a computer shop;
  - motor oil is goods (134) for a petrol station;
  - the petrol station's own fuel is an expense (513).
- **The easy 100% is true by construction.** The history and rule items were written together with the rules.

API usage and cost:

| | |
|---|---|
| API requests | 32 (limit 40; no retries, no errors) |
| Tokens | 42,202 prompt, 2,741 output, 21,558 thinking |
| Cost | **≈ $0.12** at $0.75 / $3.75 per 1M input / output tokens (thinking is billed as output) |
| Latency | ~4.8 s per LLM item; under 1 ms for history and rule items |

Without the LLM (history and rules only), 18 of the 50 items are decided, all correctly. The other 32 go to manual review, and there are no silent errors. No rule caught a hard item by mistake.

To reproduce:

```powershell
python scripts/evaluate.py --dry-run          # plan: calls needed and estimated tokens, sends nothing
python scripts/evaluate.py --max-calls 40     # the real run; stops sending at the limit
```

Successful answers are cached in `.eval_cache/`, so running the evaluation again does not spend quota on items that already have an answer. `--rpm 4` keeps a free-tier key under its limit of 5 requests per minute.

### Accountant review

The chart of accounts and the expected accounts need an accountant's check. [`data/review/`](data/review) contains three Excel files for that:

| File | What the accountant does |
|---|---|
| `kontni_okvir_provera.xlsx` | Marks each account in the chart as correct or not (da/ne), adds notes, and lists missing accounts on a second sheet. |
| `slepa_provera.xlsx` | **Blind check** of all 50 items. The file shows only the ID, the item description and the client's activity, in shuffled order. It does not show the expected account or the system's suggestion. The accountant writes the account they would use, or `?` if the description is not enough to decide. |
| `nove_stavke.xlsx` | A template for new real-world items: description, client activity and correct account. There are two example rows. The note at the top asks for no client, supplier or person names. |

After the files are filled in:

```powershell
python scripts/review.py import
```

The command writes `data/review/izvestaj_provere.md`. It compares the accountant's answers with the dataset's expected accounts and with the system's suggestions, for easy and hard items separately, and counts the system's silent errors against the accountant's answers. It also converts the new items into [`data/eval/knjigovodja.json`](data/eval). Before converting, it runs the masking check: rows that look like they contain a PIB, a name or an account number are skipped and listed in the report.

Some details:
- The system's suggestions come from [`data/eval/system_predictions.json`](data/eval/system_predictions.json). That file was rebuilt from the cached answers of the approved run with `python scripts/review.py predictions`; **none of the review commands call the Gemini API**.
- Running the evaluation on the accountant's items is a separate step that needs approval: `python scripts/evaluate.py --dataset data/eval/knjigovodja.json --dry-run` first.
- Expected accounts in the dataset are never changed automatically.
- Decisions made after the review are stored in [`data/review/odluke.json`](data/review/odluke.json), not in code:
  - the activity column of `nove_stavke.xlsx` held the **supplier's** activity, so it is kept as `delatnost_dobavljaca`, and the client activity is set to *proizvodnja dijetetskih proizvoda*;
  - the item *"oglasavnje u casopisu"* (5590) is marked as waiting for correction and is excluded from every evaluation.

**Results of the first review** (full report in [`data/review/izvestaj_provere.md`](data/review/izvestaj_provere.md)):

- **Chart of accounts:** 22 of 25 accounts were confirmed. The accountant was unsure (`?`) about 134, 551 and 559.
- **Blind check:** 19 of 50 items were filled in. 11 have an account, all written as analytic accounts, and 8 are marked `?`.
  - On the 3-digit level, the accountant agreed with the dataset and with the system on 7 of the 11 items.
  - The 4 differences are all cases where the system was confident (not flagged), so by her answers they count as **silent errors**:

    | Item | Accountant | Dataset and system |
    |---|---|---|
    | Laptop | 5120 (other material) | 023 (fixed asset) |
    | Toner | 5112 | 512 |
    | Yeast at a bakery | 5110 (direct expense) | 101 (inventory) |
    | Diesel bought by a petrol station | 5133 (expense) | 134 (goods) |

  - The internet item (5315) agrees on the 3-digit level (531). The fourth digit comes from the client's own plan.
  - Of the 8 items she marked `?`, the system flagged only 1 for review. On those items the system was **more confident than the accountant**.
- **What this means:** most differences come from accounting policy, for example whether to expense directly or put on stock, or what the fixed-asset threshold is. They do not come from misreading the item. The synthetic dataset's "expected" accounts encode one policy, and this accountant's client uses another. That is one more reason the synthetic 98% is not a real accuracy, and why learning from each client's confirmations matters more than a generic rule.

## Running locally (Windows / PowerShell)

Requires Python 3.12+ (developed and tested on 3.14).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env     # then put your GEMINI_API_KEY into .env
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the web page, or http://localhost:8000/docs for the interactive API docs. Without an API key the app still runs, using history, rules and the analytic plan only; unresolved items are flagged for review.

> **Cost note:** with `GEMINI_API_KEY` set, every uploaded invoice sends real LLM requests. That is up to one request per unresolved item for the 3-digit account, plus one per item whose analytic account needs choosing. On a paid key this costs money. Leave the key empty for demos.

To try the analytic dropdown, upload a sample invoice with client ID `K001` and activity *proizvodnja dijetetskih proizvoda*. That is the client with the trial plan.

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
| POST | `/invoices` | The same, with items as JSON; an item may carry `given_konto` (3-digit account already chosen, e.g. by Iris) |
| POST | `/confirm` | Confirm or correct the account for one item, optionally with `analytic_konto`; saved to the client's history |
| GET | `/history/{client_id}` | Confirmed postings for a client, newest first |
| GET | `/analytic-plan/{client_id}` | The client's analytic accounts (empty if none) |

Only the analytic account, with the 3-digit account coming from Iris:

```bash
curl -X POST http://localhost:8000/invoices -H "Content-Type: application/json" -d '{
  "client_id": "K001", "client_activity": "proizvodnja dijetetskih proizvoda",
  "items": [{"name": "Zakup magacina za gotove proizvode", "given_konto": "533", "supplier_pib": "203000033"}]
}'
```

The response has `suggestion.source = "input"`. `suggestion.analytic.options` lists 5330 and 5331, with the suggested one in `suggestion.analytic.konto`. To confirm:

```bash
curl -X POST http://localhost:8000/confirm -H "Content-Type: application/json" -d '{
  "client_id": "K001", "item_name": "Zakup magacina za gotove proizvode", "konto": "533",
  "analytic_konto": "5331", "supplier_pib": "203000033"
}'
```

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

`pytest` runs 151 tests covering:
- XML parsing, including XXE rejection;
- rules, history and masking;
- rejection of accounts outside the chart;
- the Gemini provider against a fake SDK client, including retries on rate limits and server errors;
- all API endpoints, including the confirm-and-learn loop;
- the evaluation script's `--max-calls` guard, cache and `--dry-run`;
- generation and import of the accountant review files, including the decisions file;
- the analytic step:
  - options only below the 3-digit account;
  - history by item and by supplier;
  - the single option;
  - LLM rejection and low confidence;
  - masking;
  - a migration for older databases;
- the analytic plan importer: CSV with `;` and cp1250, XLSX by column number, a dry run.

Gemini is mocked everywhere. The tests need neither internet access nor an API key, and a fixture fails any test that tries to create a real client.

GitHub Actions runs two jobs on every push. The first runs the test suite. The second builds the Docker image, starts the container, checks `/health` and classifies a sample invoice.

## Limitations

- **The chart of accounts must be verified.** It is a partial list of 3-digit accounts relevant to incoming invoices (classes 0, 1 and 5), taken from Sl. glasnik RS 89/2020. Intangible assets (e.g. software licences) are not included.
- **The analytic plan is a trial version.** It has one client, and it was built from the accountant's answers in the review files. It will be replaced by the Iris export. There is no accuracy measurement for the analytic step yet, and there cannot be a fair one until a plan and postings that were not used to build it are available.
- **Single option = no question asked.** If the plan has only one analytic account below a 3-digit account, it is preselected without an LLM call. With an incomplete plan, that may hide the fact that a better analytic account is missing.
- **VAT is not handled.** The system suggests the cost/asset account for the net amount. Input VAT (*prethodni porez*, group 27), the supplier account (435) and the full posting entry are out of scope.
- **Accounting policy matters.** Whether a laptop is a fixed asset (023) or small inventory, and whether goods are booked at wholesale or retail, depends on the client's policy. The system cannot know this until the accountant confirms a few decisions.
- **Masking is pattern-based.** Names that appear without a marker word in free text may not be detected. In production this should be combined with an NER model and a review of what is sent.
- **Synthetic evaluation data.** The 50-item dataset is small and fictional. Its items, expected accounts and rules were written by the same author, and the expected accounts have not been verified by an accountant.
- **Free-tier API limits.** The Gemini free tier (5 requests/minute, 20 requests/day per model) is enough for a demo, not for production volumes. The provider retries on rate limits and transient 5xx errors; items it still cannot get an answer for are flagged for review.
- **Prototype scope.** There is no authentication or multi-user access control, history matching is exact (no fuzzy matching), and items are sent to the LLM one at a time.

## Possible next steps

- Fuzzy and embedding-based history matching (e.g. "Brašno T-500" ↔ "Brašno T-400").
- Batch LLM calls per invoice; caching of identical masked items.
- Full posting proposal including VAT and the supplier account.
- Replace the trial analytic plan with the Iris export, then evaluate the analytic step on postings that were not used to build the plan.
- Client accounting policy (fixed-asset threshold, direct expensing vs. stock). The first review showed that these choices cause most of the differences.
- Authentication, audit log and an export for accounting software.
