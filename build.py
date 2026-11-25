#!/usr/bin/env python3
"""Baut die Übersicht «Was der Grosse Rat ausgibt» für die FDP Basel-Stadt.

Quellen (Open Data Basel-Stadt, data.bs.ch):
  100314 Grosser Rat: Vorgänge von Geschäften   -> was in welcher Sitzung beschlossen wurde
  100311 Grosser Rat: Geschäfte                  -> Urheber, Partei, Departement
  100313 Grosser Rat: Dokumente                  -> Link auf den Grossratsbeschluss (PDF)
  100186 Grosser Rat: Abstimmungsergebnisse      -> Stimmen der einzelnen Ratsmitglieder
  100307 Grosser Rat: Ratsmitgliedschaften       -> Partei der Ratsmitglieder

Die Frankenbeträge stehen in den Grossratsbeschlüssen (PDF). Das Skript liest sie
mit pdftotext aus. Was falsch gelesen wird, lässt sich in korrekturen.csv von Hand
richtigstellen. pruefliste.md zeigt zu jedem Geschäft die Textstellen, aus denen
die Beträge stammen.

Läuft mit der Python-Standardbibliothek und pdftotext (poppler-utils).
"""
import csv
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
CACHE = ROOT / "cache"
START = "2026-01-01"
API = "https://data.bs.ch/api/explore/v2.1/catalog/datasets"
GR = "https://grosserrat.bs.ch"
UA = "grossrat-ausgaben-basel (GitHub Actions; FDP Basel-Stadt)"

# Parteien, die auf der Seite einzeln ausgewiesen werden, in zwei Gruppen
GRUPPEN = [
    {"id": "links", "titel": "SP, Grüne und BastA!", "parteien": ["SP", "Grüne", "BastA!"]},
    {"id": "mitte", "titel": "GLP, Mitte und EVP", "parteien": ["GLP", "Mitte", "EVP"]},
]
ALLE_PARTEIEN = ["SP", "Grüne", "BastA!", "GLP", "Mitte", "EVP", "FDP", "LDP", "SVP"]

# Geschäfte, die keine neuen Ausgaben bewilligen, sondern Budget, Rechnung usw. betreffen
NICHT_AUSGABEN = re.compile(
    r"\bBudget 20\d\d\b|Budgetbericht|Jahresbericht|Jahresrechnung|Rechnung 20\d\d|Geschäftsbericht|"
    r"Finanzplan|Investitionsübersicht|Nachtragskredit|Kreditübertragung|Wahl\b|Rücktritt|Petition|"
    r"Initiative|Gegenvorschlag|Begnadigung|Einbürgerung",
    re.I,
)


# ---------------------------------------------------------------- Hilfsfunktionen

def http(url, binary=False, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            return data if binary else data.decode("utf-8")
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  Fehler bei {url}: {e}, neuer Versuch", file=sys.stderr)
            time.sleep(min(60, 5 * 2 ** i))


def export(dataset, where, select=None):
    q = {"where": where, "lang": "de", "timezone": "Europe/Zurich"}
    if select:
        q["select"] = select
    url = f"{API}/{dataset}/exports/json?" + urllib.parse.urlencode(q)
    rows = json.loads(http(url))
    print(f"  {dataset}: {len(rows)} Zeilen", file=sys.stderr)
    return rows


def in_list(field, values):
    vals = ",".join('"' + v.replace('"', "") + '"' for v in values)
    return f"{field} in ({vals})"


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def day(value):
    return (value or "")[:10]


def partei_norm(p):
    """Vereinheitlicht Partei- und Fraktionsnamen."""
    s = (p or "").strip().lower()
    if not s:
        return None
    if "glp" in s or "grünlib" in s or "gruenlib" in s:
        return "GLP"
    if "basta" in s:
        return "BastA!"
    if "jgb" in s or "junges grünes" in s:
        return "Grüne"  # junges grünes bündnis gehört zur Grünen-Familie (Fraktion GRÜNE/jgb)
    if "grün" in s or "gruen" in s:
        return "Grüne"
    if s.startswith("sp") or "sozialdem" in s:
        return "SP"
    if "evp" in s:
        return "EVP"
    if "mitte" in s or "cvp" in s:
        return "Mitte"
    if "fdp" in s or "freisinn" in s:
        return "FDP"
    if "ldp" in s or "liberal-demo" in s:
        return "LDP"
    if "svp" in s:
        return "SVP"
    return None


def name_key(name):
    s = re.sub(r"\s+", " ", (name or "").strip().lower())
    if "," in s:  # "Name, Vorname" -> "vorname name"
        a, b = [x.strip() for x in s.split(",", 1)]
        s = f"{b} {a}"
    return " ".join(sorted(s.split()))


# ---------------------------------------------------------------- Beträge lesen

NUM = r"(\d{1,3}(?:[’'` ]\d{3})+|\d+)(?:[.,](\d{1,2})(?!\d))?"
AMT = re.compile(r"(?:Fr\.|CHF|Franken)\s*" + NUM + r"(?:\s*\.[–-]+)?\s*(Mio\.?|Millionen|Mrd\.?|Milliarden)?", re.I)
WIEDERKEHREND = re.compile(r"p\.\s?a\.|pro Jahr|jährlich|wiederkehrend|jährliche|per annum", re.I)
TOTAL = re.compile(r"(total|insgesamt|gesamthaft|gesamt)\W{0,3}(von\s+)?(Fr\.|CHF)\s*$", re.I)
JAHRE = re.compile(r"(20\d\d)\s*(?:-|–|bis(?: und mit)?)\s*(20\d\d)")
KEINE_AUSGABE = re.compile(r"Einnahme|Mehrertr|Erlös|Rückzahlung|Rückerstattung|Kürzung|gekürzt|Verkauf", re.I)


def betrag(m):
    whole = int(re.sub(r"[’'` ]", "", m.group(1)))
    frac = m.group(2)
    value = float(f"{whole}.{frac}") if frac else float(whole)
    unit = (m.group(3) or "").lower()
    if unit.startswith("mio") or unit.startswith("million"):
        value *= 1_000_000
    elif unit.startswith("mrd") or unit.startswith("milliard"):
        value *= 1_000_000_000
    return round(value)


def beschluss_teil(text):
    """Nur den eigentlichen Beschluss ab «beschliesst» bis zur Publikationsklausel."""
    t = text.replace("­", "").replace("\r", "")
    t = re.sub(r"-\n(?=[a-zäöü])", "", t)
    m = re.search(r"beschliesst\s*:?", t, re.I)
    if m:
        t = t[m.end():]
    e = re.search(r"Dieser Beschluss|Publikation|ist zu publizieren|unterliegt dem|Referendum", t, re.I)
    if e and e.start() > 40:
        t = t[:e.start()]
    return t


def posten_aus_text(text):
    """Liest Ausgabenposten aus einem Grossratsbeschluss.

    Gibt eine Liste von Posten zurück: art = einmalig | befristet | wiederkehrend,
    betrag (für einmalig/befristet: Gesamtbetrag; für wiederkehrend: pro Jahr),
    jahresbetrag, jahre, quelle (Textstelle).
    """
    t = beschluss_teil(text)
    teile = re.split(r"\n\s*(?=(?:\d{1,2}\.|[a-z]\)|[IVX]+\.)\s)", "\n" + t)
    posten = []
    for teil in teile:
        satz = re.sub(r"\s+", " ", teil).strip()
        treffer = list(AMT.finditer(satz))
        if not treffer or KEINE_AUSGABE.search(satz):
            continue
        werte = [betrag(m) for m in treffer]
        if max(werte) < 1000:
            continue
        total = None
        for m, w in zip(treffer, werte):
            if TOTAL.search(satz[max(0, m.start() - 30):m.start() + len(m.group(0).split()[0])]):
                total = w
        jahre = None
        j = JAHRE.search(satz)
        if j:
            a, b = int(j.group(1)), int(j.group(2))
            if 0 < b - a < 20:
                jahre = b - a + 1
        wk = bool(WIEDERKEHREND.search(satz))
        p = {"quelle": satz[:600]}
        if wk:
            jahresbetrag = werte[0]
            if total and total != jahresbetrag:
                p.update(art="befristet", betrag=total, jahresbetrag=jahresbetrag, jahre=jahre)
            elif jahre:
                p.update(art="befristet", betrag=jahresbetrag * jahre, jahresbetrag=jahresbetrag, jahre=jahre)
            else:
                p.update(art="wiederkehrend", betrag=jahresbetrag, jahresbetrag=jahresbetrag, jahre=None)
        else:
            p.update(art="einmalig", betrag=total or max(werte), jahresbetrag=None, jahre=None)
        posten.append(p)

    # Sammelposten weglassen, wenn er die Summe der übrigen ist (z. B. «insgesamt …, aufgeteilt in …»)
    if len(posten) > 1:
        roh = [p["jahresbetrag"] if p["art"] == "wiederkehrend" else p["betrag"] for p in posten]
        for i, p in enumerate(posten):
            rest = sum(r for k, r in enumerate(roh) if k != i)
            if rest and abs(roh[i] - rest) <= max(2, rest * 0.001):
                posten.pop(i)
                break
    # Gleiche Posten nicht doppelt zählen
    gesehen, eindeutig = set(), []
    for p in posten:
        k = (p["art"], p["betrag"])
        if k not in gesehen:
            gesehen.add(k)
            eindeutig.append(p)
    return eindeutig


def pdf_text(url):
    CACHE.mkdir(exist_ok=True)
    (CACHE / "pdf").mkdir(exist_ok=True)
    f = CACHE / "pdf" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")
    if f.exists():
        return f.read_text(encoding="utf-8")
    data = http(url, binary=True)
    if not data[:5] == b"%PDF-":
        print(f"  kein PDF: {url}", file=sys.stderr)
        text = ""
    else:
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", "-", "-"], input=data, capture_output=True, check=False)
        text = r.stdout.decode("utf-8", "replace")
    f.write_text(text, encoding="utf-8")
    time.sleep(0.5)
    return text


def lade_korrekturen():
    f = ROOT / "korrekturen.csv"
    out = {}
    if not f.exists():
        return out
    with f.open(encoding="utf-8") as fh:
        for row in csv.DictReader((l for l in fh if not l.startswith("#")), delimiter=";"):
            sig = (row.get("signatur") or "").strip()
            if sig:
                out[sig] = row
    return out


def zahl(s):
    s = re.sub(r"[’'` ]", "", (s or "").strip())
    return int(float(s)) if s else 0


# ---------------------------------------------------------------- Hauptprogramm

def main():
    korrekturen = lade_korrekturen()
    heute = dt.date.today().isoformat()

    print("Vorgänge laden", file=sys.stderr)
    vorgaenge = export("100314", f'siz_datum>="{START}"',
                       "siz_datum,siz_nr,signatur_ges,titel_ges,ga_rr_gr,vermerk,url_ges")
    sitzungen = sorted({day(v["siz_datum"]) for v in vorgaenge if v.get("siz_datum")})

    ausgaben_v, postulat_v, vorstoss_v = {}, {}, {}
    for v in vorgaenge:
        typ, verm, titel = v.get("ga_rr_gr") or "", (v.get("vermerk") or "").strip(), v.get("titel_ges") or ""
        sig = v["signatur_ges"]
        if typ in ("Ratschlag", "Ausgabenbericht", "Bericht") and re.match(r"Zus?t?immung", verm, re.I):
            if not NICHT_AUSGABEN.search(titel):
                ausgaben_v[sig] = v
        elif "Budgetpostulat" in typ and re.search(r"Zustimmung zur Budgeterhöhung", verm, re.I):
            postulat_v[sig] = v
        elif typ in ("Motion", "Anzug") and re.match(
                r"(Teilweise )?Überweisung (als (Motion|Anzug)|an (den )?RR(?! zur Stellungnahme))", verm, re.I):
            vorstoss_v[sig] = v

    alle_sig = set(ausgaben_v) | set(postulat_v) | set(vorstoss_v)
    print(f"  Ausgaben {len(ausgaben_v)}, Budgetpostulate {len(postulat_v)}, Vorstösse {len(vorstoss_v)}",
          file=sys.stderr)

    print("Geschäfte und Dokumente laden", file=sys.stderr)
    geschaefte, dokumente = {}, {}
    for part in chunks(sorted(alle_sig), 80):
        for g in export("100311", in_list("signatur_ges", part)):
            e = geschaefte.setdefault(g["signatur_ges"], {**g, "miturheber": []})
            mp = g.get("name_vorname_miturheber")
            if mp and mp not in [m[0] for m in e["miturheber"]]:
                e["miturheber"].append((mp, partei_norm(g.get("partei_kname_miturheber"))))
        for d in export("100313", in_list("signatur_ges", part), "dokudatum,titel_dok,url_dok,signatur_ges"):
            dokumente.setdefault(d["signatur_ges"], []).append(d)

    def beschluss_pdf(sig, datum, auch_vorstoss=False):
        docs = sorted(dokumente.get(sig, []), key=lambda d: d.get("dokudatum") or "")
        besch = [d for d in docs if re.search(r"Beschluss", d.get("titel_dok") or "", re.I)]
        gleich = [d for d in besch if day(d.get("dokudatum")) == datum]
        danach = [d for d in besch if day(d.get("dokudatum")) >= datum]
        wahl = gleich or danach or besch[-1:]
        if not wahl and auch_vorstoss and docs:
            wahl = docs[:1]
        return wahl[0]["url_dok"] if wahl else None

    print("Ratsmitglieder und Abstimmungen laden", file=sys.stderr)
    partei_von = {}
    for m in export("100307", f'gr_ende>="{START}" or gr_ende is null', "name_vorname,partei_kname,partei,uni_nr"):
        p = partei_norm(m.get("partei_kname") or m.get("partei"))
        if p:
            partei_von[name_key(m.get("name_vorname"))] = p
            if m.get("uni_nr"):
                partei_von[str(m["uni_nr"])] = p

    stimmen = {}
    abst_sig = sorted(ausgaben_v) + sorted(postulat_v)
    for part in chunks(abst_sig, 40):
        rows = export("100186", f'datum>="{START}" and ' + in_list("signatur_ges", part),
                      "datum,signatur_ges,abst_nr,typ,anz_j,anz_n,anz_e,fraktion,mitglied_name,gr_uni_nr,entscheid_mitglied")
        for r in rows:
            stimmen.setdefault(r["signatur_ges"], []).append(r)

    def abstimmung(sig, datum):
        rows = [r for r in stimmen.get(sig, []) if day(r.get("datum")) == datum and r.get("typ") != "Eventual Abstimmung"]
        if not rows:
            return None
        nrs = {}
        for r in rows:
            nrs.setdefault(r["abst_nr"], []).append(r)
        schluss = [n for n, rs in nrs.items() if rs[0].get("typ") == "Schlussabstimmung"]
        nr = max(schluss or nrs, key=lambda n: int(re.sub(r"\D", "", str(n)) or 0))
        rs = nrs[nr]
        proPartei = {}
        for r in rs:
            p = (partei_von.get(str(r.get("gr_uni_nr") or "")) or partei_von.get(name_key(r.get("mitglied_name")))
                 or partei_norm(r.get("fraktion")))
            if r.get("fraktion") and partei_norm(r["fraktion"]) in ("SP", "BastA!", "GLP", "FDP", "LDP", "SVP"):
                # bei Fraktionen aus einer einzigen Partei gilt die Fraktion
                p = p or partei_norm(r["fraktion"])
            if not p:
                continue
            e = proPartei.setdefault(p, {"J": 0, "N": 0, "E": 0})
            k = r.get("entscheid_mitglied")
            if k in e:
                e[k] += 1
        r0 = rs[0]
        return {"nr": str(nr), "typ": r0.get("typ"), "ja": r0.get("anz_j"), "nein": r0.get("anz_n"),
                "enthaltung": r0.get("anz_e"), "parteien": proPartei}

    pruef = ["# Prüfliste", "",
             "Automatisch gelesene Beträge mit der Textstelle aus dem Grossratsbeschluss. "
             "Falsches in korrekturen.csv richtigstellen.", ""]

    def mit_korrektur(sig, posten):
        k = korrekturen.get(sig)
        if not k:
            return posten, False, None
        if (k.get("ausschliessen") or "").strip().lower() in ("ja", "x", "1"):
            return [], True, k.get("bemerkung")
        neu = []
        if zahl(k.get("einmalig")):
            neu.append({"art": "einmalig", "betrag": zahl(k["einmalig"]), "jahresbetrag": None, "jahre": None,
                        "quelle": "korrigiert"})
        if zahl(k.get("jaehrlich")):
            jahre = zahl(k.get("jahre")) or None
            jb = zahl(k["jaehrlich"])
            neu.append({"art": "befristet" if jahre else "wiederkehrend", "betrag": jb * jahre if jahre else jb,
                        "jahresbetrag": jb, "jahre": jahre, "quelle": "korrigiert"})
        return neu, True, k.get("bemerkung")

    def summen(posten):
        einm = sum(p["betrag"] for p in posten if p["art"] in ("einmalig", "befristet"))
        jaehrl = sum(p["betrag"] for p in posten if p["art"] == "wiederkehrend")
        return einm, jaehrl

    def urheber(g):
        if not g:
            return None, None, []
        name = g.get("name_vorname_urheber") or g.get("vorname_urheber")
        if g.get("gremientyp_urheber") and g.get("gremientyp_urheber") != "Mitglied":
            name = g.get("vorname_urheber") or name
        mit = [{"name": n, "partei": p} for n, p in g.get("miturheber", [])]
        return name, partei_norm(g.get("partei_kname_urheber")), mit

    print("Grossratsbeschlüsse lesen", file=sys.stderr)
    ausgaben = []
    for sig, v in sorted(ausgaben_v.items(), key=lambda x: x[1]["siz_datum"]):
        datum = day(v["siz_datum"])
        url = beschluss_pdf(sig, datum)
        posten = posten_aus_text(pdf_text(url)) if url else []
        posten, korr, bem = mit_korrektur(sig, posten)
        einm, jaehrl = summen(posten)
        g = geschaefte.get(sig, {})
        pruef.append(f"## {datum} {sig} {v['titel_ges']}")
        pruef.append(f"Beschluss: {url or 'nicht gefunden'}" + (" (korrigiert)" if korr else ""))
        for p in posten:
            pruef.append(f"- {p['art']}: Fr. {p['betrag']:,}".replace(",", "'") + f"  \n  «{p['quelle'][:400]}»")
        if not posten:
            pruef.append("- keine Ausgaben erkannt (wird auf der Seite nicht gezählt)")
        pruef.append("")
        if not posten:
            continue
        ausgaben.append({
            "signatur": sig, "datum": datum, "titel": v["titel_ges"], "typ": v.get("ga_rr_gr"),
            "departement": g.get("departement_ges"), "url": v.get("url_ges") or g.get("url_ges"),
            "beschluss": url, "posten": posten, "einmalig": einm, "jaehrlich": jaehrl,
            "korrigiert": korr, "bemerkung": bem, "abstimmung": abstimmung(sig, datum),
        })

    postulate = []
    for sig, v in sorted(postulat_v.items(), key=lambda x: x[1]["siz_datum"]):
        datum = day(v["siz_datum"])
        url = beschluss_pdf(sig, datum, auch_vorstoss=True)
        posten = posten_aus_text(pdf_text(url)) if url else []
        if not posten and url:
            # Budgetpostulate: Betrag steht oft im Fliesstext («um Fr. … erhöhen»)
            t = re.sub(r"\s+", " ", pdf_text(url))
            m = re.search(r"um\s+(?:Fr\.|CHF)\s*" + NUM + r"\s*(Mio\.?)?", t)
            if m:
                posten = [{"art": "einmalig", "betrag": betrag(AMT.search(m.group(0)[3:])), "jahresbetrag": None,
                           "jahre": None, "quelle": t[max(0, m.start() - 200):m.end() + 100]}]
        posten, korr, bem = mit_korrektur(sig, posten)
        einm, _ = summen(posten)
        g = geschaefte.get(sig, {})
        name, partei, mit = urheber(g)
        pruef.append(f"## {datum} {sig} {v['titel_ges']} (Budgetpostulat)")
        pruef.append(f"Dokument: {url or 'nicht gefunden'}")
        for p in posten:
            pruef.append(f"- Fr. {p['betrag']:,}".replace(",", "'") + f"  \n  «{p['quelle'][:400]}»")
        if not posten:
            pruef.append("- kein Betrag erkannt")
        pruef.append("")
        postulate.append({
            "signatur": sig, "datum": datum, "titel": v["titel_ges"], "url": v.get("url_ges") or g.get("url_ges"),
            "urheber": name, "partei": partei, "miturheber": mit, "betrag": einm or None,
            "korrigiert": korr, "abstimmung": abstimmung(sig, datum),
        })

    vorstoesse = []
    for sig, v in sorted(vorstoss_v.items(), key=lambda x: x[1]["siz_datum"]):
        g = geschaefte.get(sig, {})
        name, partei, mit = urheber(g)
        k = korrekturen.get(sig)
        if k and (k.get("ausschliessen") or "").strip().lower() in ("ja", "x", "1"):
            continue
        vorstoesse.append({
            "signatur": sig, "datum": day(v["siz_datum"]), "titel": v["titel_ges"], "typ": v.get("ga_rr_gr"),
            "vermerk": re.sub(r"\s*Frist:.*", "", v.get("vermerk") or ""),
            "url": v.get("url_ges") or g.get("url_ges"), "urheber": name, "partei": partei, "miturheber": mit,
            "einmalig": zahl(k.get("einmalig")) if k else 0, "jaehrlich": zahl(k.get("jaehrlich")) if k else 0,
            "bemerkung": (k or {}).get("bemerkung"),
        })

    daten = {
        "stand": heute,
        "start": START,
        "letzte_sitzung": sitzungen[-1] if sitzungen else None,
        "sitzungen": sitzungen,
        "gruppen": GRUPPEN,
        "parteien": ALLE_PARTEIEN,
        "ausgaben": ausgaben,
        "budgetpostulate": postulate,
        "vorstoesse": vorstoesse,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "pruefliste.md").write_text("\n".join(pruef) + "\n", encoding="utf-8")

    template = (ROOT / "template.html").read_text(encoding="utf-8")
    page = template.replace("/*__DATEN__*/null", json.dumps(daten, ensure_ascii=False).replace("</", "<\\/"))
    (DOCS / "index.html").write_text(page, encoding="utf-8")
    print(f"Fertig: {len(ausgaben)} Ausgaben, {len(postulate)} Budgetpostulate, {len(vorstoesse)} Vorstösse",
          file=sys.stderr)


if __name__ == "__main__":
    main()
