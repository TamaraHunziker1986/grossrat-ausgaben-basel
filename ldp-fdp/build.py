#!/usr/bin/env python3
"""Vergleich FDP und LDP im Grossen Rat Basel-Stadt, Legislaturen 2021-2025 und 2025-2029.

Quellen (Open Data Basel-Stadt, data.bs.ch):
  100311 Grosser Rat: Geschäfte                -> Vorstösse, Urheber, Miturheber
  100314 Grosser Rat: Vorgänge von Geschäften  -> Überweisung oder Nichtüberweisung
  100186 Grosser Rat: Abstimmungsergebnisse    -> Stimmen der einzelnen Ratsmitglieder
  100307 Grosser Rat: Ratsmitgliedschaften     -> Sitze pro Partei
  100086 Grosser Rat: Geschäfte mit Themen     -> Themen des Parlamentsdienstes (bis 2024)

Die Themen werden zusätzlich per Stichwort aus dem Titel bestimmt (themen.py).
Falsch zugeordnete Geschäfte lassen sich in themen-korrekturen.csv richtigstellen.

Läuft mit der Python-Standardbibliothek. Aufruf: python ldp-fdp/build.py
"""
import csv
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from themen import THEMEN, thema_von  # noqa: E402

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
OUT = ROOT / "docs" / "ldp-fdp"
PRUEF = HIER / "pruefliste.md"
API = "https://data.bs.ch/api/explore/v2.1/catalog/datasets"
GR = "https://grosserrat.bs.ch"
UA = "grossrat-ausgaben-basel/ldp-fdp (GitHub Actions; FDP Basel-Stadt)"

LEGISLATUREN = [
    {"id": "2021", "label": "2021–2025", "von": "2021-02-01", "bis": "2025-01-31"},
    {"id": "2025", "label": "2025–2029", "von": "2025-02-01", "bis": "2029-01-31"},
]
START = LEGISLATUREN[0]["von"]
PARTEIEN = ["FDP", "LDP", "SVP", "Mitte", "EVP", "GLP", "SP", "Grüne", "BastA!"]
VORSTOSS_TYPEN = ["Motion", "Anzug", "Budgetpostulat", "Interpellation", "Schriftliche Anfrage",
                  "Planungsanzug", "Resolution", "Standesinitiative"]
TYP_RE = re.compile(r"^\s*(" + "|".join(VORSTOSS_TYPEN) + r")\b", re.I)

NAMEN = {}  # «Vorname Name» -> Partei, aus der Mitgliederliste
CO_TYPEN = ("Motion", "Anzug", "Planungsanzug", "Budgetpostulat", "Resolution", "Standesinitiative")

# Für Tests lässt sich export() ersetzen (siehe test_build.py)
EXPORT_HOOK = None


# ---------------------------------------------------------------- Hilfsfunktionen

def http(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  Fehler bei {url[:160]}: {e}, neuer Versuch", file=sys.stderr)
            time.sleep(min(60, 5 * 2 ** i))


def http_bin(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * 2 ** i)


def export(dataset, where, select=None):
    if EXPORT_HOOK:
        return EXPORT_HOOK(dataset, where, select)
    q = {"where": where, "lang": "de", "timezone": "Europe/Zurich"}
    if select:
        q["select"] = select
    url = f"{API}/{dataset}/exports/json?" + urllib.parse.urlencode(q)
    rows = json.loads(http(url))
    print(f"  {dataset}: {len(rows)} Zeilen ({where[:70]})", file=sys.stderr)
    return rows


def in_list(field, values):
    vals = ",".join('"' + v.replace('"', "") + '"' for v in values)
    return f"{field} in ({vals})"


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def day(value):
    return str(value or "")[:10]


def leg_von(datum):
    d = day(datum)
    for leg in LEGISLATUREN:
        if leg["von"] <= d <= leg["bis"]:
            return leg["id"]
    return None


def partei_norm(p):
    s = (p or "").strip().lower()
    if not s:
        return None
    if "glp" in s or "grünlib" in s or "gruenlib" in s:
        return "GLP"
    if "basta" in s:
        return "BastA!"
    if "jgb" in s or "junges grünes" in s or "grün" in s or "gruen" in s or s == "gab":
        return "Grüne"
    if s.startswith("sp") or "sozialdem" in s:
        return "SP"
    if "mitte" in s or "cvp" in s:
        return "Mitte"  # Fraktion Mitte-EVP wird als Mitte geführt
    if "evp" in s:
        return "EVP"
    if "fdp" in s or "freisinn" in s:
        return "FDP"
    if "ldp" in s or "liberal-demo" in s:
        return "LDP"
    if "svp" in s:
        return "SVP"
    return None


def fraktion_norm(f):
    """Fraktionen im Abstimmungsdatensatz. Grüne und BastA! werden getrennt geführt, wo möglich."""
    return partei_norm(f)


def zahl(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def lade_korrekturen():
    pfad = HIER / "themen-korrekturen.csv"
    k = {}
    if pfad.exists():
        with pfad.open(encoding="utf-8") as f:
            for row in csv.DictReader(r for r in f if not r.startswith("#")):
                sig, th = (row.get("signatur") or "").strip(), (row.get("thema") or "").strip()
                if sig and th:
                    k[sig] = th
    return k


# ---------------------------------------------------------------- Laden

def lade_themen_parlamentsdienst():
    """Themen, die der Parlamentsdienst selbst vergeben hat (Datensatz 100086)."""
    try:
        rows = export("100086", "signatur is not null", "signatur,thema_1,thema_2")
    except Exception as e:  # noqa: BLE001
        print(f"  Themen 100086 nicht verfügbar: {e}", file=sys.stderr)
        return {}
    return {r["signatur"].strip(): " / ".join(x for x in (r.get("thema_1"), r.get("thema_2")) if x)
            for r in rows if r.get("signatur") and r.get("thema_1")}


def lade_sitze():
    """Sitze pro Partei am ersten Tag jeder Legislatur."""
    rows = export("100307", f'gr_ende>="{START}" or gr_ende is null',
                  "uni_nr,name_vorname,partei_kname,partei,gr_beginn,gr_ende")
    sitze, partei_von = {}, {}
    for leg in LEGISLATUREN:
        stichtag = (dt.date.fromisoformat(leg["von"]) + dt.timedelta(days=14)).isoformat()
        c = Counter()
        gesehen = set()
        for m in rows:
            b, e = day(m.get("gr_beginn")), day(m.get("gr_ende"))
            if b and b <= stichtag and (not e or e >= stichtag) and m.get("uni_nr") not in gesehen:
                gesehen.add(m.get("uni_nr"))
                p = partei_norm(m.get("partei_kname") or m.get("partei"))
                if p:
                    c[p] += 1
        sitze[leg["id"]] = dict(c)
    for m in rows:
        p = partei_norm(m.get("partei_kname") or m.get("partei"))
        if p and m.get("uni_nr"):
            partei_von[str(m["uni_nr"])] = p
            nv = (m.get("name_vorname") or "").split(",", 1)
            if len(nv) == 2:
                NAMEN[re.sub(r"\s+", " ", f"{nv[1].strip()} {nv[0].strip()}")] = p
    return sitze, partei_von


def lade_vorstoesse(partei_von, themen_pd, korrekturen):
    rows = export("100311", f'beginn_ges>="{START}"',
                  "beginn_ges,signatur_ges,titel_ges,ga_rr_gr,status_ges,departement_ges,gremientyp_urheber,"
                  "name_vorname_urheber,vorname_urheber,partei_kname_urheber,nr_urheber,"
                  "name_vorname_miturheber,partei_kname_miturheber,nr_miturheber")
    ges = {}
    for g in rows:
        sig = g.get("signatur_ges")
        if not sig:
            continue
        titel = (g.get("titel_ges") or "").strip()
        typ = None
        for t in VORSTOSS_TYPEN:
            if (g.get("ga_rr_gr") or "").strip().lower() == t.lower():
                typ = t
        if not typ:
            m = TYP_RE.match(titel)
            typ = next((t for t in VORSTOSS_TYPEN if m and m.group(1).lower() == t.lower()), None)
        if not typ:
            continue
        if g.get("gremientyp_urheber") and g.get("gremientyp_urheber") not in ("Mitglied", ""):
            continue  # Vorstösse von Kommissionen
        e = ges.get(sig)
        if not e:
            partei = partei_norm(g.get("partei_kname_urheber")) or partei_von.get(str(g.get("nr_urheber") or ""))
            leg = leg_von(g.get("beginn_ges"))
            if not leg:
                continue
            e = ges[sig] = {
                "sig": sig, "titel": titel, "typ": typ, "datum": day(g.get("beginn_ges")), "leg": leg,
                "urheber": g.get("name_vorname_urheber") or g.get("vorname_urheber") or "",
                "partei": partei, "status": g.get("status_ges") or "", "dep": g.get("departement_ges") or "",
                "mit": [], "mit_parteien": [],
            }
        mn = g.get("name_vorname_miturheber")
        if mn and mn not in e["mit"]:
            e["mit"].append(mn)
            mp = partei_norm(g.get("partei_kname_miturheber")) or partei_von.get(str(g.get("nr_miturheber") or ""))
            if mp:
                e["mit_parteien"].append(mp)
    for e in ges.values():
        e["thema"] = korrekturen.get(e["sig"]) or thema_von(e["titel"], themen_pd.get(e["sig"]))
        e["thema_pd"] = themen_pd.get(e["sig"], "")
    return ges


UEBERWIESEN = re.compile(r"^(Teilweise )?Überweisung|^Umwandlung|^Stehenlassen|^Stehen lassen|^Zustimmung|^Erfüllt", re.I)
STELLUNGNAHME = re.compile(r"zur Stellungnahme", re.I)
ALS_ANZUG = re.compile(r"Umwandlung|als Anzug|in ANZ", re.I)
ABGELEHNT = re.compile(r"Nichtüberweisung|nicht überwiesen|^Ablehnung|nicht zugestimmt|abgelehnt", re.I)
ZURUECK = re.compile(r"zurückgezogen|Rückzug", re.I)


def ergebnis_motion(vs):
    """Motionen werden zweimal überwiesen: zuerst zur Stellungnahme an den Regierungsrat,
    danach definitiv (als Motion), umgewandelt in einen Anzug oder gar nicht."""
    schritt1 = None
    for _, txt in vs:
        if ZURUECK.search(txt):
            return "zurückgezogen", schritt1, None
        if schritt1 is None:
            if STELLUNGNAHME.search(txt):
                schritt1 = "überwiesen"
                continue
            if ABGELEHNT.search(txt):
                return "1. Überweisung abgelehnt", "abgelehnt", None
            if UEBERWIESEN.search(txt):
                schritt1 = "überwiesen"  # erster Schritt fehlt im Datensatz, zweiter folgt direkt
        if schritt1 == "überwiesen":
            if STELLUNGNAHME.search(txt):
                continue
            if ABGELEHNT.search(txt):
                return "2. Überweisung abgelehnt", schritt1, "abgelehnt"
            if ALS_ANZUG.search(txt):
                return "als Anzug überwiesen", schritt1, "als Anzug"
            if UEBERWIESEN.search(txt):
                return "definitiv überwiesen", schritt1, "als Motion"
    if schritt1 == "überwiesen":
        return "1. Überweisung, 2. Entscheid offen", schritt1, "offen"
    return "offen", None, None


def ergebnis_einfach(vs):
    for _, txt in vs:
        if ZURUECK.search(txt):
            return "zurückgezogen"
        if ABGELEHNT.search(txt):
            return "abgelehnt"
        if UEBERWIESEN.search(txt):
            return "überwiesen"
    return "offen"


def lade_ergebnisse(ges):
    """Ob Motionen, Anzüge und Budgetpostulate überwiesen wurden."""
    sigs = [s for s, e in ges.items() if e["typ"] in ("Motion", "Anzug", "Planungsanzug", "Budgetpostulat")]
    vermerke = defaultdict(list)
    for part in chunks(sorted(sigs), 80):
        for v in export("100314", in_list("signatur_ges", part), "siz_datum,signatur_ges,vermerk"):
            vermerke[v["signatur_ges"]].append((day(v.get("siz_datum")), (v.get("vermerk") or "").strip()))
    alle_vermerke = Counter()
    for s in sigs:
        vs = sorted(vermerke.get(s, []))
        for _, txt in vs:
            alle_vermerke[re.sub(r"\d{1,2}\.\d{1,2}\.\d{4}", "DATUM", txt)] += 1
        if ges[s]["typ"] == "Motion":
            erg, ges[s]["schritt1"], ges[s]["schritt2"] = ergebnis_motion(vs)
        else:
            erg = ergebnis_einfach(vs)
        ges[s]["ergebnis"] = erg
    return alle_vermerke


def lade_mitunterzeichnende(ges):
    """Liest die Unterzeichnenden aus dem PDF des Vorstosses (Datensatz 100313).
    Die offenen Geschäftsdaten führen Mitunterzeichnende nur bei wenigen Vorstössen."""
    import subprocess
    cache = HIER / "cache" / "vorstoesse"
    cache.mkdir(parents=True, exist_ok=True)
    sigs = sorted(s for s, e in ges.items() if e["partei"] in ("FDP", "LDP") and e["typ"] in CO_TYPEN)
    erstes = {}
    for part in chunks(sigs, 80):
        for d in export("100313", in_list("signatur_ges", part), "signatur_ges,dokudatum,titel_dok,url_dok"):
            k = (day(d.get("dokudatum")) or "9999", d.get("url_dok") or "")
            if d.get("url_dok") and (d["signatur_ges"] not in erstes or k < erstes[d["signatur_ges"]]):
                erstes[d["signatur_ges"]] = k
    namen = sorted(NAMEN, key=len, reverse=True)
    gelesen, ohne = 0, []
    for s in sigs:
        f = cache / (s + ".txt")
        if not f.exists() and s in erstes:
            try:
                pdf = http_bin(erstes[s][1])
                tmp = Path("/tmp/vorstoss.pdf")
                tmp.write_bytes(pdf)
                txt = subprocess.run(["pdftotext", str(tmp), "-"], capture_output=True, text=True).stdout
                if len(txt) > 200:
                    f.write_text(txt, encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                print(f"  PDF {s}: {e}", file=sys.stderr)
        if not f.exists():
            ohne.append(s)
            continue
        txt = re.sub(r"\s+", " ", f.read_text(encoding="utf-8"))
        schluss = txt[-1800:]
        e = ges[s]
        urheber = e["urheber"]
        if "," in urheber:
            n, v = urheber.split(",", 1)
            urheber = f"{v.strip()} {n.strip()}"
        mit, mp = [], []
        for n in namen:
            if n != urheber and re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", schluss):
                mit.append(n)
                mp.append(NAMEN[n])
        e["mit"], e["mit_parteien"], e["pdf"] = mit, mp, True
        gelesen += 1
    return gelesen, ohne

def lade_abstimmungen():
    rows = []
    heute = dt.date.today()
    for jahr in range(int(START[:4]), heute.year + 1):
        von = max(START, f"{jahr}-01-01")
        bis = f"{jahr}-12-31"
        rows += export("100186", f'datum>="{von}" and datum<="{bis}"',
                       "datum,abst_nr,signatur_ges,geschaeft,typ,anz_j,anz_n,anz_e,fraktion,entscheid_mitglied")
    return rows


# ---------------------------------------------------------------- Auswerten

def position(z):
    """Häufigste Stimme einer Fraktion: J, N oder E (Enthaltung); «geteilt» bei Gleichstand."""
    c = {k: z.get(k, 0) for k in ("J", "N", "E")}
    m = max(c.values())
    if m == 0:
        return None
    top = [k for k, v in c.items() if v == m]
    return top[0] if len(top) == 1 else "geteilt"


KLAR = ("J", "N", "E")


def werte_abstimmungen(rows, themen_pd, korrekturen):
    votes = {}
    for r in rows:
        typ = r.get("typ") or ""
        if re.search(r"Präsenz|Wahl", typ, re.I):
            continue
        key = (day(r.get("datum")), str(r.get("abst_nr")))
        v = votes.get(key)
        if not v:
            v = votes[key] = {"datum": key[0], "nr": key[1], "sig": r.get("signatur_ges") or "",
                              "titel": (r.get("geschaeft") or "").strip(), "typ": typ,
                              "ja": zahl(r.get("anz_j")), "nein": zahl(r.get("anz_n")),
                              "enth": zahl(r.get("anz_e")), "fr": defaultdict(Counter), "groesse": Counter()}
        f = fraktion_norm(r.get("fraktion"))
        k = r.get("entscheid_mitglied")
        if f:
            v["groesse"][f] += 1
        if f and k in ("J", "N", "E"):
            v["fr"][f][k] += 1

    stats = {}
    differenzen = []
    sitze = {}
    for leg in LEGISLATUREN:
        lid = leg["id"]
        vs = [v for v in votes.values() if leg_von(v["datum"]) == lid]
        if not vs:
            continue
        ueberein = {p: {q: [0, 0] for q in PARTEIEN} for p in ("FDP", "LDP")}
        geschlossen = {p: [0, 0] for p in PARTEIEN}
        gewinner = {p: [0, 0] for p in PARTEIEN}
        pro_thema = defaultdict(lambda: [0, 0])
        n_beide = 0
        for v in vs:
            pos = {p: position(v["fr"].get(p, {})) for p in PARTEIEN}
            ergebnis = "J" if v["ja"] > v["nein"] else "N"
            for p in PARTEIEN:
                z = v["fr"].get(p, {})
                if pos[p] in KLAR:
                    geschlossen[p][1] += 1
                    if sum(1 for k in KLAR if z.get(k, 0)) == 1:
                        geschlossen[p][0] += 1
                if pos[p] in ("J", "N"):
                    gewinner[p][1] += 1
                    if pos[p] == ergebnis:
                        gewinner[p][0] += 1
            for p in ("FDP", "LDP"):
                if pos[p] not in KLAR:
                    continue
                for q in PARTEIEN:
                    if q != p and pos[q] in KLAR:
                        ueberein[p][q][1] += 1
                        if pos[p] == pos[q]:
                            ueberein[p][q][0] += 1
            if pos["FDP"] in KLAR and pos["LDP"] in KLAR:
                n_beide += 1
                thema = korrekturen.get(v["sig"]) or thema_von(v["titel"], themen_pd.get(v["sig"]))
                pro_thema[thema][1] += 1
                if pos["FDP"] == pos["LDP"]:
                    pro_thema[thema][0] += 1
                else:
                    fz, lz = v["fr"]["FDP"], v["fr"]["LDP"]
                    marge = abs(v["ja"] - v["nein"])
                    sieger = "FDP" if pos["FDP"] == ergebnis else "LDP" if pos["LDP"] == ergebnis else None
                    # Hätte die siegreiche Fraktion wie die andere gestimmt, wäre das Resultat gekippt?
                    entscheidend = bool(sieger) and 2 * v["fr"][sieger].get(ergebnis, 0) >= marge
                    differenzen.append({
                        "leg": lid, "datum": v["datum"], "nr": v["nr"], "sig": v["sig"], "titel": v["titel"],
                        "typ": v["typ"], "thema": thema, "ja": v["ja"], "nein": v["nein"], "enth": v["enth"],
                        "angenommen": ergebnis == "J",
                        "fdp": {"J": fz.get("J", 0), "N": fz.get("N", 0), "E": fz.get("E", 0), "pos": pos["FDP"]},
                        "ldp": {"J": lz.get("J", 0), "N": lz.get("N", 0), "E": lz.get("E", 0), "pos": pos["LDP"]},
                        "gewinnt": sieger,
                        "enthaltung": "E" in (pos["FDP"], pos["LDP"]),
                        "knapp": entscheidend,
                    })
        # Sitze: häufigste Fraktionsgrösse in den ersten drei Monaten der Legislatur
        frueh = [v for v in vs if v["datum"] <= (dt.date.fromisoformat(leg["von"]) + dt.timedelta(days=90)).isoformat()] or vs
        sitze[lid] = {}
        for p in PARTEIEN:
            c = Counter(v["groesse"][p] for v in frueh if v["groesse"].get(p))
            if c:
                sitze[lid][p] = c.most_common(1)[0][0]
        stats[lid] = {
            "abstimmungen": len(vs),
            "beide": n_beide,
            # jeweils [übereinstimmend, total]; die Seite rechnet die Prozente
            "ueberein": ueberein,
            "geschlossen": geschlossen,
            "gewinner": gewinner,
            "pro_thema": {t: {"n": b, "einig": a} for t, (a, b) in pro_thema.items()},
        }
    differenzen.sort(key=lambda d: (d["datum"], zahl(d["nr"])), reverse=True)
    return stats, differenzen, sitze


def werte_vorstoesse(ges, sitze):
    zaehl = {}
    for leg in LEGISLATUREN:
        lid = leg["id"]
        z = {p: Counter() for p in PARTEIEN}
        for e in ges.values():
            if e["leg"] == lid and e["partei"] in z:
                z[e["partei"]][e["typ"]] += 1
        zaehl[lid] = {p: {"total": sum(c.values()), "typen": dict(c), "sitze": sitze.get(lid, {}).get(p)}
                      for p, c in z.items()}

    def fl(lid=None):
        return [e for e in ges.values() if e["partei"] in ("FDP", "LDP") and (lid is None or e["leg"] == lid)]

    zusammen = {}
    for lid in [None] + [l["id"] for l in LEGISLATUREN]:
        key = lid or "alle"
        d = {}
        for p in ("FDP", "LDP"):
            eig = [e for e in fl(lid) if e["partei"] == p]
            n = len(eig)
            mit = Counter()
            for e in eig:
                for q in set(e["mit_parteien"]):
                    if q != p:
                        mit[q] += 1
            erg = Counter(e.get("ergebnis") for e in eig if e["typ"] in ("Motion", "Anzug", "Planungsanzug"))
            d[p] = {"n": n, "mit": {q: mit.get(q, 0) for q in PARTEIEN if q != p},
                    "allein": sum(1 for e in eig if not [q for q in e["mit_parteien"] if q != p]),
                    "ergebnis": dict(erg)}
        zusammen[key] = d
    return zaehl, zusammen


# ---------------------------------------------------------------- Hauptprogramm

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    korrekturen = lade_korrekturen()
    print("Themen, Sitze und Ratsmitglieder", file=sys.stderr)
    themen_pd = lade_themen_parlamentsdienst()
    sitze, partei_von = lade_sitze()
    print("Vorstösse", file=sys.stderr)
    ges = lade_vorstoesse(partei_von, themen_pd, korrekturen)
    vermerke = lade_ergebnisse(ges)
    co_gelesen, co_ohne = lade_mitunterzeichnende(ges)
    print("Abstimmungen", file=sys.stderr)
    rows = lade_abstimmungen()
    abst, differenzen, sitze_fr = werte_abstimmungen(rows, themen_pd, korrekturen)
    # Fraktionsgrösse aus den Abstimmungen ist verlässlicher als die Mitgliederliste
    for lid, z in sitze_fr.items():
        sitze.setdefault(lid, {}).update(z)
    zaehl, zusammen = werte_vorstoesse(ges, sitze)

    print("Zusätzliche Auswertungen", file=sys.stderr)
    import extras
    zusatz, zusatz_pruef = extras.alle(partei_von, LEGISLATUREN, leg_von, thema_von, partei_norm)

    vorstoesse = sorted((e for e in ges.values() if e["partei"] in ("FDP", "LDP")),
                        key=lambda e: (e["datum"], e["sig"]), reverse=True)
    # Themenverteilung aller Parteien, damit FDP und LDP eingeordnet werden können
    themen_alle = {}
    for leg in LEGISLATUREN:
        c = {p: Counter() for p in PARTEIEN}
        for e in ges.values():
            if e["leg"] == leg["id"] and e["partei"] in c:
                c[e["partei"]][e["thema"]] += 1
        themen_alle[leg["id"]] = {p: dict(v) for p, v in c.items()}

    data = {
        "stand": dt.datetime.now(dt.timezone(dt.timedelta(hours=1))).strftime("%d.%m.%Y"),
        "letzte_abstimmung": max((day(r.get("datum")) for r in rows), default=""),
        "legislaturen": LEGISLATUREN,
        "parteien": PARTEIEN,
        "themen": [t["name"] for t in THEMEN] + ["Übriges"],
        "sitze": sitze,
        "abstimmungen": abst,
        "differenzen": differenzen,
        "vorstoss_zahlen": zaehl,
        "zusammenarbeit": zusammen,
        "themen_alle": themen_alle,
        "zusatz": zusatz,
        "vorstoesse": [{k: e.get(k) for k in ("sig", "titel", "typ", "datum", "leg", "urheber", "partei", "thema",
                                               "ergebnis", "schritt1", "schritt2", "mit_parteien", "mit", "pdf", "status", "dep")} for e in vorstoesse],
    }
    html = (HIER / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    import os
    # Eigenes Passwort (Secret LDP_FDP_PASSWORD); solange es fehlt, schützt das Passwort der Ausgaben-Seite
    passwort = os.environ.get("LDP_FDP_PASSWORD", "").strip() or os.environ.get("SITE_PASSWORD", "").strip()
    if passwort:
        import schutz
        (OUT / "index.html").write_text(schutz.verschluesseln(html, passwort), encoding="utf-8")
        (OUT / "data.json").unlink(missing_ok=True)
    else:
        (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        (OUT / "index.html").write_text(html, encoding="utf-8")
    logo = ROOT / "docs" / "fdp-logo.png"
    if logo.exists():
        (OUT / "fdp-logo.png").write_bytes(logo.read_bytes())

    # Prüfliste: Vermerke und unsicher zugeordnete Themen
    pruef = ["# Prüfliste FDP/LDP", "", f"Stand {data['stand']}", "",
             "## Vermerke zu Motionen, Anzügen und Budgetpostulaten (Häufigkeit)", ""]
    pruef += [f"- {k or '(leer)'}: {n}" for k, n in vermerke.most_common(40)]
    pruef += ["", "## Vorstösse von FDP und LDP ohne Themenzuordnung", ""]
    pruef += [f"- {e['sig']} ({e['partei']}): {e['titel']}" for e in vorstoesse if e["thema"] == "Übriges"]
    pruef += ["", "## Mitunterzeichnende aus PDFs", "", f"- gelesen: {co_gelesen}, ohne PDF: {', '.join(co_ohne) or 'keine'}"]
    pruef += [f"- {e['sig']} ({e['partei']}): {', '.join(e.get('mit') or []) or '(niemand)'}" for e in vorstoesse if e.get("pdf")][:80]
    pruef += ["", "## Zusätzliche Auswertungen", ""] + [f"- {z}" for z in zusatz_pruef]
    PRUEF.write_text("\n".join(pruef) + "\n", encoding="utf-8")
    print(f"Fertig: {len(vorstoesse)} Vorstösse FDP/LDP, {len(differenzen)} Abstimmungen mit Differenz",
          file=sys.stderr)


if __name__ == "__main__":
    main()
