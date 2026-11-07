# Ručni test — faktura 07 (klijent K001)

Faktura: [`data/samples/07_test_dijetetika.xml`](../data/samples/07_test_dijetetika.xml). Dobavljač je izmišljen (Poslovni Park Morava DOO), ima 7 stavki, a svaka nosi Iris konto. Jedna stavka **namerno** ima pogrešan Iris konto: bankarska provizija sa 559 umesto 553.

Server radi na http://127.0.0.1:8000 sa Gemini ključem i tvrdim limitom poziva. Prvo ubacivanje troši oko 7 poziva, a ponovno ubacivanje iste fakture 0.

| # | Korak | Šta treba da vidiš |
|---|---|---|
| 1 | Otvori http://127.0.0.1:8000 i prevuci `07_test_dijetetika.xml` u zonu (ili klikni i izaberi fajl). | Za nekoliko sekundi kartica „Poslovni Park Morava DOO · Faktura PPM-2026-1107“ i tabela sa 7 stavki. Šest stavki u koloni **Konto** ima zelenu kvačicu, a **Provizija banke** žutu tačku sa kontom 559. |
| 2 | Klikni na red **Provizija banke za platni promet**. | Sa desne strane izlazi panel: **Iris 559** · **Sistem 553**, žuta tačka i „Razlikuje se od Iris-a“, sigurnost i obrazloženje (pravilo za bankarske provizije). Analitika: „Nema analitike ispod ovog konta“. |
| 3 | U panelu, u polju **Konto**, izaberi **553 Troškovi platnog prometa**. | U koloni Konto tog reda piše 553, a u polju **Analitika** se pojavljuje **5530 Troškovi bankarskih provizija**. Izaberi je. |
| 4 | Klikni **Potvrdi** u panelu. | Dugme u redu postaje zelena kvačica, a red blago izbledi. |
| 5 | Zatvori panel (×). Kod reda **Zakup poslovnog prostora** proveri padajući spisak **Analitika**. | Unapred je izabran **5330 Troškovi zakupa poslovnog prostora**; može se izabrati i 5331. Ako je neka zelena stavka bez izabrane analitike, izaberi je u spisku. |
| 6 | Klikni **Potvrdi sve usklađene (N)** gore desno. | Svi redovi sa zelenom kvačicom (koji imaju analitiku) postaju potvrđeni, a dole se nakratko pojavi poruka „Potvrđeno stavki: N“. |
| 7 | Klikni **Nova faktura** i ponovo ubaci isti fajl. | Svi redovi se pojavljuju odmah. Klikni na **Zakup poslovnog prostora**: u panelu je obrazloženje „Ista stavka istog dobavljača je kod ovog klijenta ranije potvrđena…“ (sigurnost 95%), a analitika je ona koju si potvrdio. Provizija banke i dalje ima žutu tačku, jer Iris i dalje kaže 559. U panelu sada piše **Sistem 553** sa obrazloženjem iz istorije. Analitika se traži ispod Iris konta (559), pa je za 5530 potrebno ponovo izabrati 553 u polju Konto. Iris konto je merodavan sve dok ga ne ispraviš u Iris-u. |

Napomene:
- Ponovno ubacivanje ne troši Gemini pozive. Potvrđene stavke dolaze iz istorije, a ostale iz keša servera.
- Ako se limit poziva potroši, stavke bez odgovora se jednostavno označe za proveru (žuta tačka) i ništa se ne šalje.
- Istorija potvrda se čuva u `kontoai.db` u folderu projekta.
