# Izveštaj provere knjigovođe

Datum uvoza: 2026-11-07

## 1. Kontni okvir

Konta: 25 — tačno (da): 22, netačno (ne): 0, nesigurno (?): 3, bez odgovora: 0.

| Konto | Naziv | Odgovor | Napomena |
|---|---|---|---|
| 134 | Roba u prometu na malo | ? |  |
| 551 | Troškovi reprezentacije | ? |  |
| 559 | Ostali nematerijalni troškovi | ? |  |

## 2. Slepa provera

Popunjeno: 19 od 50 stavki (8 označeno sa '?').

| Poređenje (stavke gde je knjigovođa upisao konto) | Slaže se | Udeo |
|---|---|---|
| Knjigovođa = očekivani konto iz dataseta | 7 / 11 | 64% |
| Knjigovođa = predlog sistema | 7 / 11 | 64% |
| — samo lake stavke: knjigovođa = sistem | 7 / 11 | 64% |

**Tihe greške sistema prema knjigovođi** (sistem pogrešio, a nije označio za proveru): 4
Od 8 stavki koje je knjigovođa označio sa '?', sistem je 1 takođe označio za ručnu proveru.
Popunjene stavke po težini: lake 14, teške 5 (od toga sa '?': lake 3, teške 5).

### Svi odgovori knjigovođe

| ID | Stavka | Težina | Knjigovođa (analitika) | Sintetika | Očekivano | Sistem | Sistem označio proveru |
|---|---|---|---|---|---|---|---|
| 2 | Usluga hostinga servera | laka | ? | ? | 539 | 539 | ne |
| 3 | Jogurt 1,5% 1kg | laka | ? | ? | 134 | 134 | ne |
| 5 | Brašno T-500 25kg | laka | ? | ? | 101 | 101 | ne |
| 12 | Internet 500 Mbps | laka | 5315 | 531 | 531 | 531 | ne |
| 14 | Provizija banke za platni promet | laka | 5530 | 553 | 553 | 553 | ne |
| 17 | Zakup magacinskog prostora | laka | 5331 | 533 | 533 | 533 | ne |
| 18 | Toner HP 85A | laka | 5112 | 511 | 512 | 512 | ne |
| 19 | Laptop Dell Latitude 5440 | laka | 5120 | 512 | 023 | 023 | ne |
| 20 | Komunalne usluge - odvoz smeća | laka | 5390 | 539 | 539 | 539 | ne |
| 23 | Evrodizel - nabavka za maloprodaju | laka | 5133 | 513 | 134 | 134 | ne |
| 24 | Kvasac svež 1kg | laka | 5110 | 511 | 101 | 101 | ne |
| 25 | Popravka peći za pečenje | laka | 5321 | 532 | 532 | 532 | ne |
| 28 | Kafa i sokovi za poslovni sastanak sa partnerima | laka | 5510 | 551 | 551 | 551 | ne |
| 30 | Advokatske usluge - izrada ugovora | laka | 5501 | 550 | 550 | 550 | ne |
| 31 | Usluga | teška | ? | ? | 539 | 539 | da |
| 38 | Kom. usl. 10/2026 | teška | ? | ? | 539 | 539 | ne |
| 43 | Cement 25kg | teška | ? | ? | 101 | 101 | ne |
| 47 | Prevod ugovora na engleski jezik | teška | ? | ? | 550 | 550 | ne |
| 49 | Revizija protivpožarnih aparata | teška | ? | ? | 532 | 532 | ne |

### Razlike

| ID | Stavka | Knjigovođa | Očekivano (dataset) | Sistem | Sistem označio proveru | Napomena |
|---|---|---|---|---|---|---|
| 2 | Usluga hostinga servera | ? | 539 | 539 | ne |  |
| 3 | Jogurt 1,5% 1kg | ? | 134 | 134 | ne |  |
| 5 | Brašno T-500 25kg | ? | 101 | 101 | ne |  |
| 18 | Toner HP 85A | 5112 | 512 | 512 | ne |  |
| 19 | Laptop Dell Latitude 5440 | 5120 | 023 | 023 | ne |  |
| 23 | Evrodizel - nabavka za maloprodaju | 5133 | 134 | 134 | ne |  |
| 24 | Kvasac svež 1kg | 5110 | 101 | 101 | ne |  |
| 31 | Usluga | ? | 539 | 539 | da |  |
| 38 | Kom. usl. 10/2026 | ? | 539 | 539 | ne |  |
| 43 | Cement 25kg | ? | 101 | 101 | ne |  |
| 47 | Prevod ugovora na engleski jezik | ? | 550 | 550 | ne |  |
| 49 | Revizija protivpožarnih aparata | ? | 532 | 532 | ne |  |

Očekivana konta u datasetu NISU automatski izmenjena — odluku o ispravci donosi autor uz knjigovođu.

## 3. Nove stavke

Uvezeno: 12 stavki; preskočeno: 0; čeka ispravku (izuzeto iz evaluacije): 1.
Kolona 'Delatnost klijenta' sadržala je delatnost DOBAVLJAČA — sačuvana je kao `delatnost_dobavljaca`; delatnost klijenta je postavljena prema data/review/odluke.json.

| # | Opis stavke | Delatnost dobavljača | Konto (knjigovođa) | Status |
|---|---|---|---|---|
| 1 | Troskovi postanski usluga | transport postanskih usluga | 5311 | aktivna |
| 2 | troskovi zakupa poslovnog prostora | javna uprava za gradjevinske objekte | 5330 | aktivna |
| 3 | potrsonja elektricne energije | distribucija elektricne energije | 5133 | aktivna |
| 4 | nabavka rezervnih delova za masinu | maloprodaja rezervnih delova | 5150 | aktivna |
| 5 | zakup sajamskog prostora | — | 5340 | aktivna |
| 6 | troskovi odvozenja smeca | javno preduzece za cistocu | 5390 | aktivna |
| 7 | usluge advokata | advokatska kancelarija | 5501 | aktivna |
| 8 | pruzanje zdravstvenih usluga | zdravstvena usluga | 5503 | aktivna |
| 9 | troskovi reprezentacije | ugostiteljske usluge | 5510 | aktivna |
| 10 | bankarske usluge | banka | 5530 | aktivna |
| 11 | oglasavnje u casopisu | oglasavanje sredstvima javnog informisanja | 5590 | čeka ispravku |
| 12 | nabavka maski i rukavica | maloprodaja | 5391 | aktivna |

Dataset: `data/eval/knjigovodja.json`. Evaluacija NIJE pokrenuta — traži posebno odobrenje.
