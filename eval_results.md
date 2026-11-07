# KontoAI — evaluation results

- Date: 2026-11-07 10:57
- LLM: not used (history + rules only)
- Items: 50 (30 easy, 20 hard) from `data/eval/dataset.json`
- Review threshold: confidence < 0.75

> [!WARNING]
> **This dataset is synthetic and its expected accounts are not verified.** The items, the expected accounts and the keyword rules were all written by the same author, so a high score here is **not** a real accuracy measure — in particular, the 100% on easy history/rule items is true by construction. The expected accounts are pending verification by an accountant. A real measurement needs invoices and postings from an accounting office.

**Silent errors** are wrong accounts that were *not* flagged for review — the outcome that matters most, because nobody looks at them. A wrong suggestion that is flagged costs the accountant a click; a silent one ends up in the books.

## Easy vs. hard items

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| Easy (clear descriptions) | 30 | 18 | **60.0%** | 12 | 0 | 0.5 ms |
| Hard (ambiguous, abbreviations, activity-dependent, no rule) | 20 | 0 | **0.0%** | 20 | 0 | 0.4 ms |
| **All** | 50 | 18 | **36.0%** | 32 | 0 | 0.4 ms |

### Hard items by category

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| ambiguous description | 5 | 0 | **0.0%** | 5 | 0 | 0.4 ms |
| invoice abbreviation | 4 | 0 | **0.0%** | 4 | 0 | 0.4 ms |
| depends on client activity | 6 | 0 | **0.0%** | 6 | 0 | 0.4 ms |
| not covered by any rule | 5 | 0 | **0.0%** | 5 | 0 | 0.4 ms |

## By decision source

| Group | Items | Correct | Accuracy | Flagged for review | Silent errors | Avg time / item |
|---|---|---|---|---|---|---|
| history | 6 | 6 | **100.0%** | 0 | 0 | 0.8 ms |
| rules | 12 | 12 | **100.0%** | 0 | 0 | 0.4 ms |
| undecided | 32 | 0 | **0.0%** | 32 | 0 | 0.4 ms |

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
| 19 | Laptop Dell Latitude 5440 | easy | 023 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 20 | Komunalne usluge - odvoz smeća | easy | 539 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 21 | Gazirani sok kola 0,5L, pakovanje 12 kom | easy | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 22 | Prevoz robe kamionom Beograd - Kragujevac | easy | 531 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 23 | Evrodizel - nabavka za maloprodaju | easy | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 24 | Kvasac svež 1kg | easy | 101 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 25 | Popravka peći za pečenje | easy | 532 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 26 | Kurirska dostava dokumenata | easy | 531 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 27 | Godišnja članarina u udruženju IT kompanija | easy | 554 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 28 | Kafa i sokovi za poslovni sastanak sa partnerima | easy | 551 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 29 | Sredstva za čišćenje prostorija | easy | 512 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 30 | Advokatske usluge - izrada ugovora | easy | 550 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 31 | Usluga | hard (ambiguous description) | 539 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 32 | Materijal po ugovoru br. 14/2026 | hard (ambiguous description) | 101 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 33 | Usluge po ugovoru za oktobar | hard (ambiguous description) | 539 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 34 | Roba po otpremnici 4471 | hard (ambiguous description) | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 35 | Nabavka po porudžbenici 88 | hard (ambiguous description) | 101 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 36 | EURO DIZ. | hard (invoice abbreviation) | 513 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 37 | Usl. odrz. SW 10/26 | hard (invoice abbreviation) | 532 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 38 | Kom. usl. 10/2026 | hard (invoice abbreviation) | 539 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 39 | Tr. PP za 10/26 | hard (invoice abbreviation) | 553 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 40 | Motorno ulje 5W-30 4L | hard (depends on client activity) | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 41 | Laptop HP 250 G9 | hard (depends on client activity) | 023 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 42 | Laptop HP 250 G9 | hard (depends on client activity) | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 43 | Cement 25kg | hard (depends on client activity) | 101 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 44 | Brašno T-500 1kg | hard (depends on client activity) | 134 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 45 | Evrodizel - za službeno vozilo | hard (depends on client activity) | 513 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 46 | Podizvođački radovi - postavljanje keramike | hard (not covered by any rule) | 530 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 47 | Prevod ugovora na engleski jezik | hard (not covered by any rule) | 550 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 48 | Štand na sajmu Tech Expo 2026 | hard (not covered by any rule) | 534 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 49 | Revizija protivpožarnih aparata | hard (not covered by any rule) | 532 | — | undecided | 0.00 | yes | ⚠️ flagged |
| 50 | Obuka zaposlenih - kurs Kubernetes | hard (not covered by any rule) | 550 | — | undecided | 0.00 | yes | ⚠️ flagged |

## Mismatches and undecided items

- **#19 Laptop Dell Latitude 5440** — expected 023, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#20 Komunalne usluge - odvoz smeća** — expected 539, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#21 Gazirani sok kola 0,5L, pakovanje 12 kom** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#22 Prevoz robe kamionom Beograd - Kragujevac** — expected 531, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#23 Evrodizel - nabavka za maloprodaju** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#24 Kvasac svež 1kg** — expected 101, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#25 Popravka peći za pečenje** — expected 532, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#26 Kurirska dostava dokumenata** — expected 531, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#27 Godišnja članarina u udruženju IT kompanija** — expected 554, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#28 Kafa i sokovi za poslovni sastanak sa partnerima** — expected 551, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#29 Sredstva za čišćenje prostorija** — expected 512, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#30 Advokatske usluge - izrada ugovora** — expected 550, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#31 Usluga** — expected 539, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#32 Materijal po ugovoru br. 14/2026** — expected 101, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#33 Usluge po ugovoru za oktobar** — expected 539, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#34 Roba po otpremnici 4471** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#35 Nabavka po porudžbenici 88** — expected 101, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#36 EURO DIZ.** — expected 513, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#37 Usl. odrz. SW 10/26** — expected 532, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#38 Kom. usl. 10/2026** — expected 539, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#39 Tr. PP za 10/26** — expected 553, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#40 Motorno ulje 5W-30 4L** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#41 Laptop HP 250 G9** — expected 023, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#42 Laptop HP 250 G9** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#43 Cement 25kg** — expected 101, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#44 Brašno T-500 1kg** — expected 134, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#45 Evrodizel - za službeno vozilo** — expected 513, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#46 Podizvođački radovi - postavljanje keramike** — expected 530, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#47 Prevod ugovora na engleski jezik** — expected 550, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#48 Štand na sajmu Tech Expo 2026** — expected 534, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#49 Revizija protivpožarnih aparata** — expected 532, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
- **#50 Obuka zaposlenih - kurs Kubernetes** — expected 550, got no suggestion (flagged): Istorija i pravila nisu prepoznali stavku, a LLM nije konfigurisan.
