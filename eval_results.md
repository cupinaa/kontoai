# KontoAI — evaluation results

- Date: 2026-11-07 10:26
- LLM: not used (history + rules only)
- Items: 30 (fictional dataset `data/eval/dataset.json`)
- Review threshold: confidence < 0.75

> **The expected accounts in the dataset are not yet verified by an accountant.** Treat these numbers as a sanity check of the pipeline, not as a measured production accuracy.

## Summary

| Metric | Value |
|---|---|
| Overall accuracy | **60.0%** (18/30) |
| Accuracy of auto-accepted items (not flagged) | 100.0% (18/18) |
| Flagged for manual review | 12 of 30 |
| Average time per item | 0.5 ms |

## By decision source

| Source | Items | Correct | Accuracy | Flagged | Avg time / item |
|---|---|---|---|---|---|
| history | 6 | 6 | 100.0% | 0 | 0.8 ms |
| rules | 12 | 12 | 100.0% | 0 | 0.4 ms |
| undecided | 12 | 0 | 0.0% | 12 | 0.4 ms |

## Per item

| # | Item | Expected | Predicted | Source | Confidence | Review | Result |
|---|---|---|---|---|---|---|---|
| 1 | Servis kombija - mali servis | 532 | 532 | history | 0.95 |  | ✅ |
| 2 | Usluga hostinga servera | 539 | 539 | history | 0.95 |  | ✅ |
| 3 | Jogurt 1,5% 1kg | 134 | 134 | history | 0.85 |  | ✅ |
| 4 | Kiselo mleko 0,5L | 134 | 134 | history | 0.85 |  | ✅ |
| 5 | Brašno T-500 25kg | 101 | 101 | history | 0.95 |  | ✅ |
| 6 | Brašno T-400 25kg | 101 | 101 | history | 0.80 |  | ✅ |
| 7 | Evrodizel | 513 | 513 | rules | 0.90 |  | ✅ |
| 8 | BMB 95 | 513 | 513 | rules | 0.90 |  | ✅ |
| 9 | Zakup poslovnog prostora za novembar | 533 | 533 | rules | 0.90 |  | ✅ |
| 10 | Električna energija za oktobar | 513 | 513 | rules | 0.90 |  | ✅ |
| 11 | Mobilna telefonija - mesečna pretplata | 531 | 531 | rules | 0.88 |  | ✅ |
| 12 | Internet 500 Mbps | 531 | 531 | rules | 0.88 |  | ✅ |
| 13 | Papir A4 80g, 500 listova | 512 | 512 | rules | 0.88 |  | ✅ |
| 14 | Provizija banke za platni promet | 553 | 553 | rules | 0.92 |  | ✅ |
| 15 | Polisa osiguranja imovine 2027 | 552 | 552 | rules | 0.90 |  | ✅ |
| 16 | Knjigovodstvene usluge za oktobar | 550 | 550 | rules | 0.90 |  | ✅ |
| 17 | Zakup magacinskog prostora | 533 | 533 | rules | 0.90 |  | ✅ |
| 18 | Toner HP 85A | 512 | 512 | rules | 0.88 |  | ✅ |
| 19 | Laptop Dell Latitude 5440 | 023 | — | undecided | 0.00 | yes | ❌ |
| 20 | Komunalne usluge - odvoz smeća | 539 | — | undecided | 0.00 | yes | ❌ |
| 21 | Gazirani sok kola 0,5L, pakovanje 12 kom | 134 | — | undecided | 0.00 | yes | ❌ |
| 22 | Prevoz robe kamionom Beograd - Kragujevac | 531 | — | undecided | 0.00 | yes | ❌ |
| 23 | Evrodizel - nabavka za maloprodaju | 134 | — | undecided | 0.00 | yes | ❌ |
| 24 | Kvasac svež 1kg | 101 | — | undecided | 0.00 | yes | ❌ |
| 25 | Popravka peći za pečenje | 532 | — | undecided | 0.00 | yes | ❌ |
| 26 | Kurirska dostava dokumenata | 531 | — | undecided | 0.00 | yes | ❌ |
| 27 | Godišnja članarina u udruženju IT kompanija | 554 | — | undecided | 0.00 | yes | ❌ |
| 28 | Kafa i sokovi za poslovni sastanak sa partnerima | 551 | — | undecided | 0.00 | yes | ❌ |
| 29 | Sredstva za čišćenje prostorija | 512 | — | undecided | 0.00 | yes | ❌ |
| 30 | Advokatske usluge - izrada ugovora | 550 | — | undecided | 0.00 | yes | ❌ |
