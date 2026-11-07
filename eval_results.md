# KontoAI — evaluation results

- Date: 2026-11-07 11:26
- LLM: Gemini `gemini-3.6-flash`
- Items: 50 (30 easy, 20 hard) from `data/eval/dataset.json`
- Review threshold: confidence < 0.75

> [!WARNING]
> **This dataset is synthetic and its expected accounts are not verified.** The items, the expected accounts and the keyword rules were all written by the same author, so a high score here is **not** a real accuracy measure — in particular, the 100% on easy history/rule items is true by construction. The expected accounts are pending verification by an accountant. A real measurement needs invoices and postings from an accounting office.

**Silent errors** are wrong accounts that were *not* flagged for review — the outcome that matters most, because nobody looks at them. A wrong suggestion that is flagged costs the accountant a click; a silent one ends up in the books.

## Easy vs. hard items

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| Easy (clear descriptions) | 30 | 30 | **100.0%** | 0 | 0 | 1839.0 ms |
| Hard (ambiguous, abbreviations, activity-dependent, no rule) | 20 | 19 | **95.0%** | 4 | 0 | 4985.6 ms |
| **All** | 50 | 49 | **98.0%** | 4 | 0 | 3097.6 ms |

### Hard items by category

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| ambiguous description | 5 | 4 | **80.0%** | 4 | 0 | 6119.7 ms |
| invoice abbreviation | 4 | 4 | **100.0%** | 0 | 0 | 4134.6 ms |
| depends on client activity | 6 | 6 | **100.0%** | 0 | 0 | 5067.0 ms |
| not covered by any rule | 5 | 5 | **100.0%** | 0 | 0 | 4434.6 ms |

## By decision source

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| history | 6 | 6 | **100.0%** | 0 | 0 | 0.8 ms |
| rules | 12 | 12 | **100.0%** | 0 | 0 | 0.4 ms |
| LLM | 32 | 31 | **96.9%** | 4 | 0 | 4839.8 ms |

## API usage

| Metric | Value |
|---|---|
| API requests sent (incl. retries) | 32 of max 40 |
| Successful responses | 32 |
| Answers served from cache | 0 |
| Prompt tokens | 42,202 |
| Output tokens | 2,741 |
| Thinking tokens | 21,558 |
| Estimated cost (paid tier, prices of 2026-11-07) | $0.123 |

## Per item

| # | Item | Difficulty | Expected | Predicted | Source | Confidence | Review | Result |
|---|---|---|---|---|---|---|---|---|
| 1 | Servis kombija - mali servis | easy | 532 | 532 | history | 0.95 |  | ✅ |
| 2 | Usluga hostinga servera | easy | 539 | 539 | history | 0.95 |  | ✅ |
| 3 | Jogurt 1,5% 1kg | easy | 134 | 134 | history | 0.85 |  | ✅ |
| 4 | Kiselo mleko 0,5L | easy | 134 | 134 | history | 0.85 |  | ✅ |
| 5 | Brašno T-500 25kg | easy | 101 | 101 | history | 0.95 |  | ✅ |
| 6 | Brašno T-400 25kg | easy | 101 | 101 | history | 0.80 |  | ✅ |
| 7 | Evrodizel | easy | 513 | 513 | rules | 0.90 |  | ✅ |
| 8 | BMB 95 | easy | 513 | 513 | rules | 0.90 |  | ✅ |
| 9 | Zakup poslovnog prostora za novembar | easy | 533 | 533 | rules | 0.90 |  | ✅ |
| 10 | Električna energija za oktobar | easy | 513 | 513 | rules | 0.90 |  | ✅ |
| 11 | Mobilna telefonija - mesečna pretplata | easy | 531 | 531 | rules | 0.88 |  | ✅ |
| 12 | Internet 500 Mbps | easy | 531 | 531 | rules | 0.88 |  | ✅ |
| 13 | Papir A4 80g, 500 listova | easy | 512 | 512 | rules | 0.88 |  | ✅ |
| 14 | Provizija banke za platni promet | easy | 553 | 553 | rules | 0.92 |  | ✅ |
| 15 | Polisa osiguranja imovine 2027 | easy | 552 | 552 | rules | 0.90 |  | ✅ |
| 16 | Knjigovodstvene usluge za oktobar | easy | 550 | 550 | rules | 0.90 |  | ✅ |
| 17 | Zakup magacinskog prostora | easy | 533 | 533 | rules | 0.90 |  | ✅ |
| 18 | Toner HP 85A | easy | 512 | 512 | rules | 0.88 |  | ✅ |
| 19 | Laptop Dell Latitude 5440 | easy | 023 | 023 | LLM | 0.95 |  | ✅ |
| 20 | Komunalne usluge - odvoz smeća | easy | 539 | 539 | LLM | 0.95 |  | ✅ |
| 21 | Gazirani sok kola 0,5L, pakovanje 12 kom | easy | 134 | 134 | LLM | 0.95 |  | ✅ |
| 22 | Prevoz robe kamionom Beograd - Kragujevac | easy | 531 | 531 | LLM | 0.95 |  | ✅ |
| 23 | Evrodizel - nabavka za maloprodaju | easy | 134 | 134 | LLM | 0.98 |  | ✅ |
| 24 | Kvasac svež 1kg | easy | 101 | 101 | LLM | 0.85 |  | ✅ |
| 25 | Popravka peći za pečenje | easy | 532 | 532 | LLM | 0.95 |  | ✅ |
| 26 | Kurirska dostava dokumenata | easy | 531 | 531 | LLM | 0.95 |  | ✅ |
| 27 | Godišnja članarina u udruženju IT kompanija | easy | 554 | 554 | LLM | 0.98 |  | ✅ |
| 28 | Kafa i sokovi za poslovni sastanak sa partnerima | easy | 551 | 551 | LLM | 0.95 |  | ✅ |
| 29 | Sredstva za čišćenje prostorija | easy | 512 | 512 | LLM | 0.95 |  | ✅ |
| 30 | Advokatske usluge - izrada ugovora | easy | 550 | 550 | LLM | 0.95 |  | ✅ |
| 31 | Usluga | hard (ambiguous description) | 539 | 539 | LLM | 0.40 | yes | ✅ |
| 32 | Materijal po ugovoru br. 14/2026 | hard (ambiguous description) | 101 | 101 | LLM | 0.65 | yes | ✅ |
| 33 | Usluge po ugovoru za oktobar | hard (ambiguous description) | 539 | 530 | LLM | 0.65 | yes | ⚠️ flagged |
| 34 | Roba po otpremnici 4471 | hard (ambiguous description) | 134 | 134 | LLM | 0.95 |  | ✅ |
| 35 | Nabavka po porudžbenici 88 | hard (ambiguous description) | 101 | 101 | LLM | 0.35 | yes | ✅ |
| 36 | EURO DIZ. | hard (invoice abbreviation) | 513 | 513 | LLM | 0.95 |  | ✅ |
| 37 | Usl. odrz. SW 10/26 | hard (invoice abbreviation) | 532 | 532 | LLM | 0.95 |  | ✅ |
| 38 | Kom. usl. 10/2026 | hard (invoice abbreviation) | 539 | 539 | LLM | 0.95 |  | ✅ |
| 39 | Tr. PP za 10/26 | hard (invoice abbreviation) | 553 | 553 | LLM | 0.90 |  | ✅ |
| 40 | Motorno ulje 5W-30 4L | hard (depends on client activity) | 134 | 134 | LLM | 0.95 |  | ✅ |
| 41 | Laptop HP 250 G9 | hard (depends on client activity) | 023 | 023 | LLM | 0.92 |  | ✅ |
| 42 | Laptop HP 250 G9 | hard (depends on client activity) | 134 | 134 | LLM | 0.95 |  | ✅ |
| 43 | Cement 25kg | hard (depends on client activity) | 101 | 101 | LLM | 0.85 |  | ✅ |
| 44 | Brašno T-500 1kg | hard (depends on client activity) | 134 | 134 | LLM | 0.95 |  | ✅ |
| 45 | Evrodizel - za službeno vozilo | hard (depends on client activity) | 513 | 513 | LLM | 0.95 |  | ✅ |
| 46 | Podizvođački radovi - postavljanje keramike | hard (not covered by any rule) | 530 | 530 | LLM | 0.95 |  | ✅ |
| 47 | Prevod ugovora na engleski jezik | hard (not covered by any rule) | 550 | 550 | LLM | 0.92 |  | ✅ |
| 48 | Štand na sajmu Tech Expo 2026 | hard (not covered by any rule) | 534 | 534 | LLM | 0.98 |  | ✅ |
| 49 | Revizija protivpožarnih aparata | hard (not covered by any rule) | 532 | 532 | LLM | 0.85 |  | ✅ |
| 50 | Obuka zaposlenih - kurs Kubernetes | hard (not covered by any rule) | 550 | 550 | LLM | 0.95 |  | ✅ |

## Mismatches and undecided items

- **#33 Usluge po ugovoru za oktobar** — expected 539, got 530 (flagged): Za delatnost kurirskih usluga, ugovorene usluge trećih lica se najčešće odnose na angažovanje podizvođača na poslovima dostave (konto 530). Zbog uopštenog opisa stavke, postoji mogućnost da se radi i o neproizvodnim uslugama.
