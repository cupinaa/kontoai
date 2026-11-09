# KontoAI

[![CI](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml/badge.svg)](https://github.com/cupinaa/kontoai/actions/workflows/ci.yml)

**KontoAI helps Serbian accountants post incoming e-invoices. For every invoice line it suggests the client-specific analytic account (the 4th digit), checks the 3-digit account from the accounting software, and learns from every confirmation.**

![KontoAI: an invoice with suggested accounts and the detail panel](docs/screenshots/kontoai.png)

*Invoice from a supplier the accountant has posted before. Six lines match the accounting software (green check) and can be confirmed in one click. The bank fee does not: the software says 559, the system says 553. The panel offers the accountant's own earlier decision, 553 · 5530.*

> **Status: prototype.**
> - The chart of accounts and the analytic plan in this repository still need an accountant's sign-off.
> - The 50-item evaluation set is synthetic; the evaluation against the client's real plan has only 23 items.
> - All invoices, companies, tax IDs and people in the repository are invented.

## The problem

Since SEF (*Sistem e-faktura*), incoming invoices arrive as structured UBL 2.1 XML. The accountant's software (here Iris) already proposes the **3-digit synthetic account** for each line.

The slow part is the **analytic account**: the fourth digit, e.g. 533**0** office rent vs. 533**1** warehouse rent. It is not prescribed by the *Pravilnik o kontnom okviru*. Every company defines its own analytic chart, so choosing it means remembering how *this* client books *this* supplier and *this* kind of item. Accountants do it line by line, every month.

KontoAI focuses on that step:
- It suggests the analytic account only from the client's own plan.
- It reuses the accountant's earlier decisions.
- It asks an LLM only when there is nothing to learn from.
- It cross-checks the 3-digit account against the accounting software.
- The accountant always makes the final call.

## How it works

```mermaid
flowchart LR
    A[SEF UBL XML] --> B[Parse lines,<br/>supplier, Iris account]
    B --> C[Own 3-digit suggestion:<br/>item history -> rules -><br/>supplier history -> LLM]
    C --> D{Same as Iris?}
    D -- yes --> E[green]
    D -- no --> F[yellow: review]
    E --> G[Analytic account below<br/>the Iris account:<br/>history -> only option -> LLM]
    F --> G
    G --> H[Accountant confirms<br/>or corrects]
    H -- saved --> I[(Client history)]
    I --> C
    I --> G
```

**3-digit account.** The system always computes its own suggestion and compares it with the account from the accounting software:

| Step | Source | Notes |
|---|---|---|
| 1 | **Item history** | The same supplier and the same or a similar description were confirmed before for this client. |
| 2 | **Keyword rules** ([`data/rules.json`](data/rules.json)) | Fuel, energy, rent, trade fairs, telecom, office supplies, bank fees, insurance, accounting services, advertising. They are activity-aware: fuel bought by a petrol station is goods, not an expense. A more specific rule wins over a general one (*zakup sajamskog prostora* is a trade-fair cost, not rent); rules of equal weight that disagree leave the line to the LLM. |
| 3 | **Supplier history** | Used only if **all** confirmed items of that supplier are on one account and there are at least two. |
| 4 | **LLM** (Gemini) | Gets masked text only, and a JSON schema restricts it to the allowed accounts. |

The result is shown as a **green check** (matches Iris) or a **yellow dot** (differs, so it needs review). The Iris account stays authoritative for the next step.

**Analytic account.** It is chosen only among the client's analytic accounts below the 3-digit account:

| Step | Source | Notes |
|---|---|---|
| 1 | **The accountant's earlier decision** | Same item and supplier, and the same Iris account as last time: her account and analytic account are preselected. The panel says *"Prošli put ste izabrali 553 · 5530"*. |
| 2 | **History** | Item, then supplier, but always below the current 3-digit account. |
| 3 | **Only one option** | No LLM call is needed. |
| 4 | **LLM** | Chooses from the offered list. An answer outside the list is rejected. When another candidate is about as good (it fits the description equally, or the model picked a less used account while a more used one has a similar name), the choice stays preselected but is flagged for review. |

Analytic accounts may have 4 or more digits (5330, 53301); the first three digits are the parent account. When the plan carries posting counts (this year + last year), candidates are ranked by them and the LLM sees a usage label next to each one (*"često (46 knjiženja)"*, *"nije korišćen"*). Accounts that were never used are kept, just ranked last.

Something is **always preselected**, so the accountant only confirms or changes it:
- An unsure suggestion is preselected but stays yellow and is not part of *Potvrdi sve usklađene*.
- When no offered analytic fits, the closest one is preselected. The panel says *"Nijedna analitika ne odgovara dobro"* and offers a better 3-digit account if the model names one.
- Without a usable LLM answer (no key, an error, or the call limit reached), the option whose name shares most words with the line is preselected and flagged.

**Questions.** In the side panel the accountant can ask about the line (*Pitaj o ovoj stavci*). Each question is one LLM call and counts against the same server-wide call limit. The model gets only the masked line, the question, the suggested accounts, the candidates from the client's plan and the 3-digit chart, and answers in 2–4 sentences. A recommended account is accepted only if it exists in the client's plan, and off-topic questions are declined. Questions and answers live only in the open page; nothing is stored.

Every confirmation is stored in the client's history (SQLite). The next invoice from the same supplier is mostly answered from history, without LLM calls.

## Privacy

- **Masking.** Before any LLM call, [`app/masking.py`](app/masking.py) replaces identifying data with placeholders:
  - the supplier name, PIB and matični broj;
  - bank accounts and IBANs, JMBG, e-mail addresses and phone numbers;
  - person names introduced by words such as *kontakt:* or *za zaposlenog*.
- **What the model sees.** Only the masked line text, the client's activity and the list of allowed accounts. Supplier identity and the client's name are never sent. The placeholder mapping stays on the server and is used only to unmask the model's explanation.
- **XML parsing** uses `defusedxml`, so XXE and entity-expansion attacks are rejected.
- **Cost and call control.**
  - Identical masked requests are answered from an in-memory cache.
  - A server-wide hard limit on LLM calls is available (`KONTOAI_MAX_LLM_CALLS`).
  - `KONTOAI_DISABLE_LLM=1` runs the app with no LLM at all.

## Results (read with care)

> [!WARNING]
> **The evaluation dataset is synthetic, and I wrote it.** The 50 items, their expected accounts and the keyword rules were all written by the same person. The numbers below show that the pipeline works as designed. They are **not** a measure of real-world accuracy.

[`scripts/evaluate.py`](scripts/evaluate.py) runs [`data/eval/dataset.json`](data/eval/dataset.json) through the 3-digit pipeline. The dataset has 30 easy items and 20 hard ones: ambiguous descriptions, invoice abbreviations, activity-dependent items and items no rule covers. The model answers come from one run on `gemini-3.6-flash` (2026-11-07); the score was recomputed on 2026-11-09 from the same cached answers (no new calls) after one expected account changed and a trade-fair rule was added (see below). Full report in [`eval_results.md`](eval_results.md):

| | Items | Matched the expected account | Flagged for review | Wrong and *not* flagged |
|---|---|---|---|---|
| Easy | 30 | 29 | 0 | 1 |
| Hard | 20 | 19 | 4 | 0 |

- The easy score is high by construction, because the rules were written with those items in mind.
- The hard miss was an ambiguous line, and it was flagged for review. The easy miss is yeast for a bakery: the system books it as stock (101), the accountant as raw-material expense (511), and her answer now counts as correct.
- History (6) and rules (13) decided 19 of the 50 items without the LLM, all of them correctly. The other 31 went to the LLM. One of the rule items is a hard one (a stand at a trade fair): it is covered by the trade-fair rule added after a real-plan error, so the hard items are no longer fully independent of the rules.

**A practising accountant reviewed the material blind**, without seeing the expected account or the system's suggestion ([`data/review/`](data/review)). She confirmed 22 of the 25 accounts of the chart and was unsure about 3. Of the 50 items she answered 19: 11 with an account, 8 with a `?` (the description was not enough). Of her 8 `?` items, the system had flagged only 1, so it is more confident than it should be on vague lines.

### Against the client's real analytic plan

Later the client's real analytic plan became available (an export from the accounting software; it is confidential and kept outside this repository). It is now the reference:

- Where the accountant's account exists in the plan **with the same meaning**, her answer is kept: source **`knjigovodja`** (9 items).
- Where it does not (she answered from memory, and several of her analytic numbers mean something else in this client's plan), the account was **chosen from the plan by name**, the more used one when two fit equally: source **`izvedeno_iz_plana`** (14 items). These were chosen by me, not confirmed by her.

The 23 items are her 12 example items plus the 11 blind-check items she gave an account for. Each item gets the expected 3-digit account as the accounting software's account, as it would in practice. The 3-digit columns score the system's *own* suggestion; the analytic step chooses below the given account. Model answers from one run on `gemini-3.6-flash` (2026-11-09), re-scored the same day from cached answers (no new calls) after the two fixes below ([`eval_results_real_plan.md`](eval_results_real_plan.md), aggregate numbers only):

| Source of the expected account | Items | 3-digit correct | Flagged | Silent errors | Analytic correct | Flagged | Silent errors |
|---|---|---|---|---|---|---|---|
| `knjigovodja` (her answer, matches the plan) | 9 | 7 | 1 | 1 | 9 | 0 | 0 |
| `izvedeno_iz_plana` (chosen from the plan by name) | 14 | 14 | 0 | 0 | 13 | 3 | 0 |
| all | 23 | 21 | 1 | 1 | 22 | 3 | 0 |

- Read the `izvedeno_iz_plana` row with care: the expected account and the system's answer were both chosen by matching the item to the plan's account names, so agreement there is easier than on her own answers.
- **Two fixes after the first run.** (1) A trade-fair rental was caught by the general *rent* rule; a more specific rule now wins over a general one, and the same was done for advertising and insurance lines that mention rent. (2) The only analytic error was a line where two accounts fit about equally and the model picked the less used one, with full confidence. Close candidates are now flagged.
- Before the fixes: 3-digit 20/23 with 2 silent errors; analytic 22/23 with 1 silent error and nothing flagged.
- The remaining 3-digit silent error is yeast booked as stock instead of expense (a policy question). The flagged one is a spare part she books as a one-off write-off of tools.
- The analytic step now flags 3 of 23 items: the wrong one and two correct ones whose candidates really are close (warehouse vs. business premises; two sub-accounts of the same material account).
- 23 items are far too few for a reliable accuracy figure, and the fixes were made after looking at these items, so the re-scored numbers are optimistic.

The main lesson stays the same: a generic model encodes *one* accounting policy, while each client has its own. That is why KontoAI learns per client, chooses only from the client's own plan, and treats its suggestions as proposals.

**Questions** (*Pitaj o ovoj stavci*) were checked with four fixed questions ([`scripts/check_questions.py`](scripts/check_questions.py), 4 calls). The model corrected a wrong analytic account to the right one from the plan, chose a sensible candidate for package delivery, said plainly that none of the offered candidates fit when the line belonged under another 3-digit account (without inventing one), and declined an off-topic question.

## Running it

Requires Python 3.12+ (developed on 3.14).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env        # optional: put GEMINI_API_KEY into .env
```

**Without an LLM.** History, rules and the analytic plan still work, and nothing is sent anywhere:

```powershell
$env:KONTOAI_DISABLE_LLM = "1"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

**With Gemini.** This uses the key from `.env`. Every uploaded invoice can make paid API calls, so optionally cap them:

```powershell
$env:KONTOAI_MAX_LLM_CALLS = "20"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000 and drop [`data/samples/07_test_dijetetika.xml`](data/samples/07_test_dijetetika.xml) on the page. That invoice belongs to the demo client `K001`, who has the trial analytic plan. A step-by-step manual test (in Serbian) is in [`docs/RUCNI_TEST.md`](docs/RUCNI_TEST.md).

To disable the LLM, use `KONTOAI_DISABLE_LLM=1`. Do not try `$env:GEMINI_API_KEY = ""`: in PowerShell that deletes the variable, and the key from `.env` is then loaded again.

**Docker:**

```bash
docker build -t kontoai .
docker run --rm -p 8000:8000 --env-file .env -v kontoai-data:/data kontoai
```

**Tests and evaluation:**

```powershell
pytest                                   # no network and no API key needed: Gemini is mocked
python scripts/evaluate.py --dry-run     # plan an evaluation: calls needed, nothing sent
python scripts/evaluate.py --max-calls 40
python scripts/check_questions.py --dry-run   # the fixed question check: masked prompts, nothing sent
python scripts/evaluate_real_plan.py --dataset <private>.json --forbidden <private>.txt --dry-run
```

GitHub Actions runs the tests and builds and smoke-tests the Docker image on every push.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/invoices/xml` | Upload a SEF XML (`file`, `client_activity`, optional `client_id`) and get suggestions |
| POST | `/invoices` | The same with JSON lines; a line may carry `given_konto`, the account from the accounting software |
| POST | `/ask` | The accountant's question about one line (one LLM call); the answer may recommend an account from the client's plan |
| POST | `/confirm` | Confirm or correct a line (3-digit and analytic account); stored in the client's history |
| GET | `/history/{client_id}` | Confirmed postings |
| GET | `/analytic-plan/{client_id}` | The client's analytic accounts |
| GET | `/accounts`, `/health` | Chart of accounts; status, LLM calls and token usage |

Interactive docs are at `/docs`.

## Data in this repository

| Path | What it is |
|---|---|
| [`data/kontni_okvir.json`](data/kontni_okvir.json) | 25 three-digit accounts from the *Pravilnik o kontnom okviru* (Sl. glasnik RS 89/2020) that are relevant to incoming invoices. A demonstration subset that is **not verified**. |
| [`data/analiticki_plan.json`](data/analiticki_plan.json) | **Trial** analytic plan for the demo client `K001` (17 accounts), built from the accountant's review answers. A client's real plan is confidential and is **never** stored in this repository: [`scripts/import_pdf_plan.py`](scripts/import_pdf_plan.py) reads the accounting software's *Konta: Lista* PDF (only current accounts of classes 01, 02, 10, 13 and 5, with posting counts), refuses to write inside the repository, and the app loads the result from `KONTOAI_ANALYTIC_PLAN_PATH`. CSV/XLSX exports go through [`scripts/import_analytic_plan.py`](scripts/import_analytic_plan.py). |
| [`data/samples/`](data/samples) | Invented SEF invoices. In invoices 06 and 07 the accounting-software account is carried in `cbc:AccountingCost` **for the demo only**. In practice Iris does not write it into the supplier's XML; the accounts would come from an Iris export and be sent as `given_konto`. |
| [`data/eval/`](data/eval) | The synthetic evaluation dataset, the accountant's own example items, and the suggestions from the evaluation run. Items the accountant answered carry `izvor`: `knjigovodja` or `izvedeno_iz_plana`. Only 3-digit accounts are public; the expected analytic accounts depend on the client's confidential plan and are kept outside the repository. |
| [`data/review/`](data/review) | The Excel files the accountant filled in, the decisions taken after her review, and the comparison report. [`scripts/review.py`](scripts/review.py) generates and imports them. |

## Project structure

```
app/            FastAPI app, pipeline (classifier, history, rules, masking), LLM provider, web page
  llm/          LLMProvider interface, Gemini implementation, in-memory cache
  static/       single-page UI (plain HTML/CSS/JS) and brand assets
scripts/        evaluation, accountant review, analytic-plan import, sample and brand-asset generators
data/           chart of accounts, rules, analytic plan, samples, evaluation and review data
tests/          pytest suite (Gemini always mocked)
docs/           screenshots, mascot source, manual test
```

The model can be swapped. The rest of the app only uses the `LLMProvider` interface ([`app/llm/base.py`](app/llm/base.py)), and the Gemini model is set by `GEMINI_MODEL`, by default `gemini-3.6-flash`.

## Limitations

- **Unverified reference data.** The 3-digit chart in this repository is a partial, unverified list, and the public analytic plan is a trial version for the demo.
- **Small evaluation.** The 50-item set is synthetic and close to the rules; the real-plan evaluation has 23 items, 14 of them with an expected account chosen from the plan by name rather than confirmed by the accountant.
- **One accounting policy.** Fixed-asset thresholds and expense-vs-stock decisions differ between clients. The system learns them only from confirmations, and a generic LLM tends to be overconfident about them.
- **Simple history matching.** Text similarity is word overlap, so rewordings such as *"zakup kancelarije"* vs. *"zakup poslovnog prostora"* are not recognised as the same item.
- **Questions answer from a narrow context.** The model sees the line and the plan candidates, not the client's postings, so it cannot know the client's own policy unless the accountant says it in the question.
- **Pattern-based masking.** It covers the identifiers listed above but cannot recognise every personal name in free text.
- **Out of scope:** VAT, the supplier account and the full posting entry.
- **Prototype operations.** There is no authentication or multi-user access control, SQLite is the store, and lines are sent to the LLM one at a time.
- **Logo as PNG.** The mascot is a PNG, because the SVG tracer (vtracer) crashes on Python 3.14.

## Next steps

1. Have the accountant confirm the 14 accounts chosen from the plan by name, and get real, already-booked invoices to measure on.
2. Import the accounting software's 3-digit proposals through its export instead of the demo `AccountingCost` field.
3. Per-client accounting policy (fixed-asset threshold, expense vs. stock) as explicit settings.
4. Better item matching (embeddings), batching LLM calls per invoice, and the full posting entry including VAT.
