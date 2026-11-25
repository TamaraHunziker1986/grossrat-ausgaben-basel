"""Testlauf mit erfundenen Daten: python ldp-fdp/test_build.py (schreibt nach /tmp/ldp-fdp-test)."""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build

random.seed(1)
P = {"FDP": 7, "LDP": 14, "SVP": 11, "Mitte": 8, "GLP": 8, "SP": 30, "Grüne": 14, "BastA!": 5, "EVP": 3}
members = []
n = 1
for p, k in P.items():
    for i in range(k):
        members.append({"uni_nr": str(n), "name_vorname": f"Muster{n}, Hans", "partei_kname": p, "partei": p,
                        "gr_beginn": "2017-02-01", "gr_ende": None}); n += 1
TIT = ["betreffend Parkplätze für das Gewerbe", "betreffend Steuersenkung für Familien", "betreffend Velostrassen",
       "betreffend mehr Polizei im Kleinbasel", "betreffend Kulturförderung Museen", "betreffend Wohnschutz",
       "betreffend Solaranlagen", "betreffend Schulhaus Neubau", "betreffend Spitalplanung", "betreffend Digitalisierung der Verwaltung",
       "betreffend Zusammenarbeit mit Baselland", "betreffend Fasnacht"]
TYP = ["Motion", "Anzug", "Interpellation", "Schriftliche Anfrage", "Budgetpostulat"]

def hook(ds, where, select):
    if ds == "100307":
        return members
    if ds == "100086":
        return [{"signatur": "22.5001", "thema_1": "Verkehr", "thema_2": ""}]
    if ds == "100311":
        rows = []
        for i in range(600):
            m = random.choice(members); t = random.choice(TYP)
            sig = f"{random.choice([21,22,23,24,25,26])}.{5000+i}"
            d = f"20{sig[:2]}-0{random.randint(2,9)}-1{random.randint(0,9)}"
            base = {"beginn_ges": d, "signatur_ges": sig, "titel_ges": f"{t} {m['name_vorname']} und Konsorten {random.choice(TIT)}",
                    "ga_rr_gr": t, "status_ges": "B", "departement_ges": "BVD", "gremientyp_urheber": None,
                    "name_vorname_urheber": m["name_vorname"], "partei_kname_urheber": m["partei_kname"], "nr_urheber": m["uni_nr"]}
            for k in range(random.randint(0, 4)):
                mm = random.choice(members)
                rows.append({**base, "name_vorname_miturheber": mm["name_vorname"], "partei_kname_miturheber": mm["partei_kname"], "nr_miturheber": mm["uni_nr"]})
            if not rows or rows[-1]["signatur_ges"] != sig:
                rows.append(base)
        return rows
    if ds == "100314":
        import re
        sigs = re.findall(r'"([\d.]+)"', where)
        return [{"siz_datum": "2023-05-05", "signatur_ges": s, "vermerk": random.choice(["Überweisung als Motion an RR", "Nichtüberweisung", "Überweisung an RR zur Stellungnahme", "Stehenlassen"])} for s in sigs]
    if ds == "100186":
        import re
        jahr = re.search(r'(\d{4})-12-31', where).group(1)
        rows = []
        for a in range(150):
            datum = f"{jahr}-0{random.randint(1,9)}-1{random.randint(0,9)}"
            if datum < "2021-02-01": continue
            frak_pos = {p: random.random() for p in P}
            votes = []
            for m in members:
                pj = frak_pos[m["partei"]]
                votes.append("J" if random.random() < (0.9 if pj > .5 else 0.1) else ("N" if random.random() < .95 else "E"))
            j, nn, e = votes.count("J"), votes.count("N"), votes.count("E")
            t = random.choice(TIT)
            for m, v in zip(members, votes):
                rows.append({"datum": datum, "abst_nr": str(a), "signatur_ges": f"23.{a}", "geschaeft": "Ratschlag " + t,
                             "typ": random.choice(["Abstimmung", "Schlussabstimmung"]), "anz_j": j, "anz_n": nn, "anz_e": e,
                             "fraktion": {"Grüne": "GRÜNE/jgb", "Mitte": "Mitte-EVP", "EVP": "Mitte-EVP"}.get(m["partei"], m["partei"]),
                             "entscheid_mitglied": v})
        return rows
    raise ValueError(ds)

build.EXPORT_HOOK = hook
import extras
def fake_alle(partei_von, legs, leg_von, thema_von, partei_norm):
    return ({
     "ausgaben": {"geschaefte": [{"sig":"23.1","datum":"2023-05-01","leg":"2021","titel":"Ausgabenbericht Testkredit","einmalig":5000000,"jaehrlich":200000,"fdp":"N","ldp":"J","url":"#"}],
                  "vorstoss_kosten": [{"sig":"24.5","datum":"2024-01-01","leg":"2021","titel":"Anzug","partei":"FDP","einmalig":100000,"jaehrlich":0}]},
     "parolen": {"kantonal": [{"datum":"2024-03-03","leg":"2021","titel":"Wohnschutz","ergebnis":"Angenommen","ja_anteil":55.2,"fdp":"Nein","ldp":"Ja","link":"#","ebene":"kantonal"}],
                 "eidg": [{"datum":"2025-09-28","leg":"2025","titel":"E-ID","ergebnis":"angenommen","fdp":"Ja","ldp":"Ja","ebene":"eidgenössisch"}]},
     "kommissionen": {"2025": {"Finanzkommission": {"kurz":"FKom","FDP":["Muster, A (Präsident)"],"LDP":["Beispiel, B"],"praesidium":"FDP"}}},
     "wortmeldungen": {"sitzungen":{"2021":40,"2025":20},"zaehl":{"2021":{"FDP":{"total":300,"personen":{"Luca Urgese":120}},"LDP":{"total":500,"personen":{"Raoul Furlano":90}}}}},
     "interessen": {"zaehl":{"FDP":{"Stiftungen":4,"Gewerbe, KMU und Wirtschaftsverbände":6},"LDP":{"Stiftungen":12,"Kultur und Fasnacht":5}},"personen":{"FDP":7,"LDP":13},
                    "eintraege":[{"partei":"FDP","name":"Muster, A","text":"Gewerbeverband (Vorstand)","branche":"Gewerbe, KMU und Wirtschaftsverbände","rubrik":""}]},
     "wahlen": {"2020":{"anteile":{"Grossbasel Ost":{"FDP":7.1,"LDP":15.0},"Kanton":{"FDP":6.9,"LDP":14.2}},"fremd":{"FDP":{"LDP":400,"SVP":200,"SP":100},"LDP":{"FDP":300,"SVP":150}},"sitze":{}},
                "2024":{"anteile":{"Grossbasel Ost":{"FDP":8.0,"LDP":13.1},"Kanton":{"FDP":7.9,"LDP":12.0}},"fremd":{"FDP":{"LDP":500,"SVP":210,"GLP":80},"LDP":{"FDP":350,"SVP":180}},"sitze":{}}},
    }, ["test"])
extras.alle = fake_alle
build.OUT = Path("/tmp/ldp-fdp-test")
build.PRUEF = Path("/tmp/ldp-fdp-test/pruefliste.md")
build.main()
