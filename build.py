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
import base64
import json
import os
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
START = "2021-02-01"  # Beginn der Legislatur 2021-2025
API = "https://data.bs.ch/api/explore/v2.1/catalog/datasets"
GR = "https://grosserrat.bs.ch"
UA = "grossrat-ausgaben-basel (GitHub Actions; FDP Basel-Stadt)"

# Parteien, die auf der Seite einzeln ausgewiesen werden, in zwei Gruppen
GRUPPEN = [
    {"id": "links", "titel": "SP, Grüne und BastA!", "parteien": ["SP", "Grüne", "BastA!"]},
    {"id": "mitte", "titel": "GLP, Mitte und EVP", "parteien": ["GLP", "Mitte", "EVP"]},
    {"id": "buergerlich", "titel": "FDP, LDP und SVP", "parteien": ["FDP", "LDP", "SVP"]},
]
ALLE_PARTEIEN = ["SP", "Grüne", "BastA!", "GLP", "Mitte", "EVP", "FDP", "LDP", "SVP"]

# Geschäfte, die keine neuen Ausgaben bewilligen, sondern Budget, Rechnung usw. betreffen
NICHT_AUSGABEN = re.compile(
    r"\bBudget 20\d\d\b|Budgetbericht|Jahresbericht|Jahresrechnung|Rechnung 20\d\d|Geschäftsbericht|"
    r"Finanzplan|Investitionsübersicht|Nachtragskredit|Kreditübertragung|Wahl\b|Rücktritt|Petition|"
    r"Initiative|Gegenvorschlag|Begnadigung|Einbürgerung|Aufnahme von .*Schulden|Anleihe|Garantie|Bürgschaft",
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
    q = {"lang": "de", "timezone": "Europe/Zurich"}
    if where:
        q["where"] = where
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
    if s.startswith("sp") or "sozialdem" in s or "juso" in s:
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

SEP = "’'`‘´ "
NUM = r"(\d{1,3}(?:[" + SEP + r"]+\d{3})+|\d+)(?:[.,](\d{1,2})(?!\d))?"
AMT = re.compile(
    r"(?:(?:Fr\.|CHF)\s*" + NUM + r"(?:\s*\.[–-]+)?\s*(Mio\.?|Millionen|Mrd\.?|Milliarden)?"
    r"|" + NUM.replace("(\\d", "(?P<n2>\\d", 1).replace("(?:[.,](\\d", "(?:[.,](?P<f2>\\d", 1)
    + r"\s*(?P<u2>Mio\.?|Millionen)?\s*Franken)", re.I)
WIEDERKEHREND = re.compile(r"p\.\s?a\.|pro Jahr|jährlich|wiederkehrend|per annum", re.I)
TOTAL = re.compile(r"(total|insgesamt|gesamthaft|gesamt\w*)(\s+(von|in der Höhe von|in Höhe von))?\s*(Fr\.|CHF)?\s*$", re.I)
ERHOEHUNG = re.compile(r"\bum\s*(?:Fr\.|CHF)\s*$", re.I)
JAHRE = re.compile(r"(20\d\d)\s*(?:-|–|bis(?: und mit)?|und)\s*(20\d\d)")
KEINE_AUSGABE = re.compile(r"Einnahme|Mehrertr|Erlös|Rückzahlung|Rückerstattung|Kürzung|gekürzt|Verkauf", re.I)
DARLEHEN = re.compile(r"Darlehen", re.I)


def betrag(m):
    g = m.groupdict()
    raw, frac, unit = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (g["n2"], g["f2"], g["u2"])
    whole = int(re.sub("[" + SEP + "]", "", raw))
    value = float(f"{whole}.{frac}") if frac else float(whole)
    unit = (unit or "").lower()
    if unit.startswith("mio") or unit.startswith("million"):
        value *= 1_000_000
    elif unit.startswith("mrd") or unit.startswith("milliard"):
        value *= 1_000_000_000
    return round(value)


ENDE = re.compile(r"Dieser Beschluss|ist zu publizieren|Die gebundenen Ausgaben|unterliegt dem|Referendum", re.I)


def beschluss_bloecke(text):
    """Alle Beschlussteile ab «beschliesst» bis zur Publikationsklausel (ein PDF kann mehrere enthalten)."""
    t = text.replace("­", "").replace("\r", "").replace("\f", "\n")
    t = re.sub(r"-\n(?=[a-zäöü])", "", t)
    t = re.sub(r"(Fr\.|CHF)\s*\n\s*", r"\1 ", t)
    t = re.sub(r"\n\s*Grosser Rat des Kantons Basel-Stadt\s*\n", "\n", t)
    starts = [m.end() for m in re.finditer(r"beschliesst\s*:?|://:", t, re.I)] or [0]
    out = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else len(t)
        block = t[a:b]
        e = ENDE.search(block)
        if e and e.start() > 20:
            block = block[:e.start()]
        out.append(block)
    return out


NEUER_POSTEN = re.compile(r"^\s*(?:(?:\d{1,2}\.|[a-z][.)]|[IVX]+\.|[-–•])\s*$|(?:\d{1,2}\.|[a-z][.)]|[-–•])\s+\S|(?:Fr\.|CHF)\s*\d)")
AUSGABE_WORT = re.compile(r"bewillig|genehmig|gewährt|zu ?Lasten|zulasten|Ausgabe|Aufwend|Aufwand|Folgekosten|Globalbeitrag|"
                          r"Staatsbeitr|Finanzhilfe|Kredit|Beitrag (an|von|in)|Darlehen", re.I)
FREMDE_INVESTITION = re.compile(r"Investitionen der (IWB|BVB)|Investitionsrahmen|Gesamtinvestitionen|bikantonal|zur Kenntnis", re.I)


WEITER = re.compile(r"(\bvon|\bauf|\bum|total|insgesamt|gesamthaft|\bbis|\bund|\bje|Höhe|,|\(|\d{4}:|;)\s*$", re.I)


def segmente(block):
    block = re.sub(r";\s+([a-z])\.\s", r";\n\1. ", block)
    segs, cur = [], []
    for line in block.split("\n"):
        marker = re.match(r"^\s*(?:\d{1,2}\.|[a-z][.)]|[IVX]+\.|[-–•])(\s|$)", line)
        if NEUER_POSTEN.match(line) and cur and (marker or not WEITER.search(cur[-1])):
            segs.append(" ".join(cur))
            cur = []
        if line.strip() and not re.fullmatch(r"\s*(?:\d{1,2}\.|[a-z]\)|[IVX]+\.|[-–•])\s*", line):
            cur.append(line.strip())
    if cur:
        segs.append(" ".join(cur))
    out = []
    for seg in segs:
        seg = re.sub(r"\s+", " ", seg).strip()
        # mehrere Beschlussziffern in einem Block: an Satzgrenzen vor typischen Satzanfängen trennen
        out.extend(x for x in re.split(r"(?<=[a-zäöü\)»0-9]\.)\s+(?=(?:Für|Der Grosse Rat|Es wird|Es werden|Dem|Den|Ferner)\s)", seg) if x.strip())
    return out


def posten_aus_block(block):
    posten = []
    for satz in segmente(block):
        treffer = list(AMT.finditer(satz))
        if not treffer or KEINE_AUSGABE.search(satz) or FREMDE_INVESTITION.search(satz) \
                or re.search(r"Beschluss Nr\.|\bP\d{6}\b", satz):
            continue
        if ("§" in satz and not re.search(r"bewillig|zu ?Lasten|zulasten", satz, re.I)) or not AUSGABE_WORT.search(satz):
            continue
        werte = [betrag(m) for m in treffer]
        if max(werte) < 1000:
            continue
        total = erh = None
        for m, w in zip(treffer, werte):
            vor = satz[max(0, m.start() - 40):m.start() + (4 if m.group(0)[:3] in ("Fr.", "CHF") else 0)]
            if ERHOEHUNG.search(vor) and erh is None:
                erh = w
            elif TOTAL.search(vor) and total is None:
                total = w
        jahre = None
        j = JAHRE.search(satz)
        if j:
            a, b = int(j.group(1)), int(j.group(2))
            if 0 < b - a < 20:
                jahre = b - a + 1
        p = {"quelle": satz[:600]}
        haupt = erh if erh is not None else werte[0]
        if DARLEHEN.search(satz):
            p.update(art="darlehen", betrag=erh or total or haupt, jahresbetrag=None, jahre=None)
        elif WIEDERKEHREND.search(satz) and erh is None:
            jaehrlich = [w for m, w in zip(treffer, werte)
                         if re.match(r"\W{0,3}(p\.\s?a\.|pro Jahr|jährlich|per annum)(?!\s*(Fr\.|CHF|\d))", satz[m.end():m.end() + 30], re.I)]
            erst_total = (total is None and len(werte) > 1 and werte[0] == max(werte)
                          and (jahre or re.search(r"für die Jahre|Rahmenausgabe|Periode", satz, re.I)))
            if erst_total:
                total = werte[0]
            jb = jaehrlich[0] if jaehrlich else next((w for w in werte if w != total), werte[0])
            groesser = [w for w in werte if w > jb]
            gesamt = total if total and total != jb else (groesser[0] if groesser and jaehrlich else None)
            if gesamt:
                p.update(art="befristet", betrag=gesamt, jahresbetrag=jb, jahre=jahre)
            elif jahre and jahre > 1:
                p.update(art="befristet", betrag=jb * jahre, jahresbetrag=jb, jahre=jahre)
            else:
                p.update(art="wiederkehrend", betrag=jb, jahresbetrag=jb, jahre=None)
        else:
            p.update(art="einmalig", betrag=haupt if erh is not None else (total or haupt), jahresbetrag=None, jahre=None)
        posten.append(p)

    # Einleitender Sammelposten («… bewilligt. Diese Ausgaben teilen sich wie folgt auf»).
    # Stimmt die Summe der Einzelposten mit ihm überein, zählen die Einzelposten, sonst der Gesamtbetrag.
    if len(posten) > 1:
        leads = [p for p in posten if re.search(r"teil(en|t) sich|wie folgt|aufgeteilt", p["quelle"], re.I)]
        rest = [p for p in posten if p not in leads]
        if leads and rest:
            roh = lambda p: p["jahresbetrag"] if p["art"] == "wiederkehrend" else p["betrag"]
            lead_summe, rest_summe = sum(roh(p) for p in leads), sum(roh(p) for p in rest)
            posten = rest if abs(lead_summe - rest_summe) <= max(2, lead_summe * 0.005) else leads
    # Sammelposten weglassen, wenn er die Summe der übrigen ist
    while len(posten) > 1:
        roh = [p["jahresbetrag"] if p["art"] == "wiederkehrend" else p["betrag"] for p in posten]
        weg = None
        for i in range(len(posten)):
            rest = sum(r for k, r in enumerate(roh) if k != i)
            if rest and abs(roh[i] - rest) <= max(2, rest * 0.002):
                weg = i
                break
        if weg is None:
            break
        posten.pop(weg)
    gesehen, eindeutig = set(), []
    for p in posten:
        k = (p["art"], p["betrag"], p["quelle"][:80])
        if k not in gesehen:
            gesehen.add(k)
            eindeutig.append(p)
    return eindeutig


def gesamtbetraege(text):
    """Gesamtbeträge aus Einleitungssätzen («Gesamtbetrag von Fr. …, teilt sich wie folgt auf»)."""
    out = []
    for block in beschluss_bloecke(text):
        for satz in segmente(block):
            if re.search(r"teil(en|t) sich|wie folgt|aufgeteilt", satz, re.I) and not re.search(r"\bum\s*(Fr\.|CHF)", satz):
                m = AMT.search(satz)
                if m:
                    out.append(betrag(m))
    return out


def posten_aus_text(text):
    """Ausgabenposten aus einem Grossratsbeschluss.

    art = einmalig | befristet | wiederkehrend | darlehen; betrag = Gesamtbetrag
    (bei wiederkehrend: pro Jahr).
    """
    out = []
    for block in beschluss_bloecke(text):
        out.extend(posten_aus_block(block))
    return out


KOSTEN_WORT = re.compile(r"Kosten|kostet|kosten\b|Mehrkosten|Mehraufw|Aufwand|Aufwände|Ausgaben|Investition|Folgekosten|"
                         r"Personalkosten|Betriebskosten|Beitrag von|Mittel von|Kostenfolge", re.I)
SCHAETZUNG = re.compile(r"\brund\b|ca\.|circa|\betwa\b|geschätzt|Schätzung|voraussichtlich|ungefähr|bis zu|maximal|"
                        r"zwischen|grob|mindestens|Grössenordnung|dürften|würden|wäre", re.I)
NICHT_KOSTEN = re.compile(r"Einnahme|Ertrag|Erträge|Einsparung|spart|Erlös|Steuerertr|Budget der|Gesamtbudget|"
                          r"Umsatz|Vermögen|Lohn von|Einkommen|Miete von|pro Person|pro Kind|pro Platz|pro Monat|Gebühr", re.I)


def kosten_aus_text(text):
    """Sätze mit Kostenangaben (Betrag und Kostenwort) aus einem Vorstoss-Dokument."""
    t = re.sub(r"\s+", " ", text.replace("\u00ad", ""))
    t = re.sub(r"(Fr\.|CHF)\s+", r"\1 ", t)
    saetze = re.split(r"(?<=[a-zäöü\)»0-9]\.)\s+(?=[A-ZÄÖÜ])", t)
    out = []
    for satz in saetze:
        if len(satz) > 700 or not KOSTEN_WORT.search(satz) or NICHT_KOSTEN.search(satz):
            continue
        werte = [(m, betrag(m)) for m in AMT.finditer(satz)]
        werte = [(m, w) for m, w in werte if w >= 10000]
        if not werte:
            continue
        out.append({"satz": satz.strip(), "betrag": werte[0][1], "wiederkehrend": bool(WIEDERKEHREND.search(satz)),
                    "schaetzung": bool(SCHAETZUNG.search(satz))})
    return out


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


# ---------------------------------------------------------------- Passwortschutz

ITERATIONEN = 250_000

ANMELDUNG = """<!DOCTYPE html>
<html lang="de-CH"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Was der Grosse Rat ausgibt | FDP Kanton Basel-Stadt</title>
<link rel="icon" href="fdp-logo.png" type="image/png">
<link href="https://fonts.googleapis.com/css2?family=Jost:wght@700;800&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
body{margin:0;font-family:"Source Sans 3",Arial,sans-serif;color:#4b5261;background:#fff}
.kopf{background:#00a0e2;padding:16px 24px 22px}.kopf img{height:64px;display:block}
main{max-width:420px;margin:64px auto;padding:0 24px}
h1{font-family:Jost,Arial,sans-serif;font-weight:800;color:#414959;font-size:28px;margin:0 0 8px}
label{display:block;font-weight:600;margin:24px 0 6px}
input{font:inherit;width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d9dce1;border-radius:3px}
button{margin-top:14px;font-family:Jost,Arial,sans-serif;font-weight:700;font-size:16px;color:#fff;background:#074ea1;border:0;border-radius:3px;padding:11px 20px;cursor:pointer}
#fehler{color:#b4232a;min-height:1.5em;margin-top:10px}
</style></head><body>
<div class="kopf"><img src="fdp-logo.png" alt="FDP Kanton Basel-Stadt"></div>
<main><h1>Was der Grosse Rat ausgibt</h1><p>Interne Übersicht der FDP Basel-Stadt. Bitte Passwort eingeben.</p>
<form id="f"><label for="pw">Passwort</label><input id="pw" type="password" autocomplete="current-password" autofocus>
<button type="submit">Öffnen</button><div id="fehler" role="alert"></div></form></main>
<script>
const P = __PAYLOAD__;
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function oeffnen(pw, still){
  try {
    const basis = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey({name:"PBKDF2", salt:b64(P.salt), iterations:P.iter, hash:"SHA-256"},
      basis, {name:"AES-GCM", length:256}, false, ["decrypt"]);
    const klar = await crypto.subtle.decrypt({name:"AES-GCM", iv:b64(P.iv)}, key, b64(P.data));
    try { sessionStorage.setItem("gr-pw", pw); } catch(e) {}
    const html = new TextDecoder().decode(klar);
    document.open(); document.write(html); document.close();
  } catch(e) {
    if (!still) document.getElementById("fehler").textContent = "Das Passwort stimmt nicht.";
  }
}
document.getElementById("f").addEventListener("submit", e => { e.preventDefault(); oeffnen(document.getElementById("pw").value); });
try { const gespeichert = sessionStorage.getItem("gr-pw"); if (gespeichert) oeffnen(gespeichert, true); } catch(e) {}
</script></body></html>
"""


def verschluesseln(html, passwort):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salt, ITERATIONEN, dklen=32)
    data = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)
    payload = {"salt": base64.b64encode(salt).decode(), "iv": base64.b64encode(iv).decode(),
               "iter": ITERATIONEN, "data": base64.b64encode(data).decode()}
    return ANMELDUNG.replace("__PAYLOAD__", json.dumps(payload))


# ---------------------------------------------------------------- Hauptprogramm

def main():
    korrekturen = lade_korrekturen()
    heute = dt.date.today().isoformat()

    print("Vorgänge laden", file=sys.stderr)
    vorgaenge = export("100314", f'siz_datum>="{START}"',
                       "siz_datum,siz_nr,signatur_ges,titel_ges,ga_rr_gr,vermerk,url_ges")
    vorgaenge = [v for v in vorgaenge if v.get("siz_datum") and day(v["siz_datum"]) <= heute]
    sitzungen = sorted({day(v["siz_datum"]) for v in vorgaenge})

    ausgaben_v, postulat_v, vorstoss_v = {}, {}, {}
    for v in vorgaenge:
        typ, verm, titel = v.get("ga_rr_gr") or "", (v.get("vermerk") or "").strip(), v.get("titel_ges") or ""
        sig = v["signatur_ges"]
        if typ in ("Ratschlag", "Ausgabenbericht", "Bericht") and re.match(r"Zus?t?immung", verm, re.I):
            if not NICHT_AUSGABEN.search(titel):
                ausgaben_v[sig] = v
        elif "Budgetpostulat" in typ and re.match(
                r"(Zustimmung|(Vollständig |teilweise )?erfüllt|Vorgezogenes Budgetpostulat (teilweise )?erfüllt)", verm, re.I) \
                and not re.search(r"nicht erfüllt|abgelehnt|zurückgezogen", verm, re.I):
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

    def merke(name, p, ueberschreiben=False):
        k = name_key(name)
        if p and k and (ueberschreiben or k not in partei_von):
            partei_von[k] = p

    # Reihenfolge = Verlässlichkeit: zuerst Rückfallquellen, dann überschreiben mit genaueren
    # 1. Grossratswahlen 2020 (Liste GB = Grüne und BastA! gemeinsam: nicht eindeutig, wird ausgelassen)
    try:
        for m in export("100101", None, "name,vorname,parteikurzbezeichnung,gewahlt"):
            merke(f"{m.get('name')}, {m.get('vorname')}", partei_norm(m.get("parteikurzbezeichnung")),
                  ueberschreiben=(m.get("gewahlt") == "Gewählt"))
    except Exception as e:  # noqa: BLE001
        print(f"  Wahlen 2020 nicht geladen: {e}", file=sys.stderr)
    # 2. Kandidierende Grossratswahlen 2024
    try:
        for m in export("100385", None, "name_vorname,listenkurzbezeichnung"):
            merke(m.get("name_vorname"), partei_norm(m.get("listenkurzbezeichnung")), ueberschreiben=True)
    except Exception as e:  # noqa: BLE001
        print(f"  Kandidierende 2024 nicht geladen: {e}", file=sys.stderr)
    # 3. Fraktion in den Abstimmungen (nur Fraktionen aus einer Partei)
    try:
        url = f"{API}/100186/exports/json?" + urllib.parse.urlencode(
            {"where": f'datum>="{START}"', "group_by": "mitglied_name,fraktion", "select": "count(*) as n"})
        for m in json.loads(http(url)):
            if partei_norm(m.get("fraktion")) in ("SP", "BastA!", "GLP", "FDP", "LDP", "SVP"):
                merke(m.get("mitglied_name"), partei_norm(m.get("fraktion")), ueberschreiben=True)
    except Exception as e:  # noqa: BLE001
        print(f"  Fraktionen nicht geladen: {e}", file=sys.stderr)
    # 4. Ratsmitglieder: Parteiangabe des Grossen Rates
    for m in export("100307", None, "name_vorname,partei_kname,partei,uni_nr"):
        p = partei_norm(m.get("partei_kname") or m.get("partei"))
        if p:
            merke(m.get("name_vorname"), p, ueberschreiben=True)
            if m.get("uni_nr"):
                partei_von[str(m["uni_nr"])] = p
    # 5. Frühere Ratsmitglieder, die in keiner Quelle eindeutig sind (Liste GB 2020)
    for n, p in {"Lachenmeier, Michelle": "Grüne", "Stöcklin, Jürg": "Grüne", "Leuthardt, Beat": "BastA!",
                 "von Falkenstein, Patricia": "LDP"}.items():
        merke(n, p)
    print(f"  Parteizuordnung für {len(partei_von)} Namen", file=sys.stderr)

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
        # Der Beschluss wurde angenommen: nur Abstimmungen mit Ja-Mehrheit kommen in Frage
        angenommen = [n for n, rs in nrs.items() if (rs[0].get("anz_j") or 0) > (rs[0].get("anz_n") or 0)]
        if not angenommen:
            return None
        schluss = [n for n in angenommen if nrs[n][0].get("typ") == "Schlussabstimmung"]
        nr = max(schluss or angenommen, key=lambda n: int(re.sub(r"\D", "", str(n)) or 0))
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

    from collections import Counter
    bp_vermerke = Counter((v.get("ga_rr_gr"), re.sub(r"\d{1,2}\.\d{1,2}\.\d{4}", "DATUM", v.get("vermerk") or ""))
                          for v in vorgaenge if "Budgetpostulat" in (v.get("ga_rr_gr") or ""))
    # Vollständigkeit: alle Vermerke zu Vorstössen, die nach Überweisung klingen, aber nicht erfasst wurden
    typen = Counter(v.get("ga_rr_gr") for v in vorgaenge)
    nicht_erfasst = Counter()
    for v in vorgaenge:
        t, verm = v.get("ga_rr_gr") or "", v.get("vermerk") or ""
        if re.search(r"berw|überwies|stehen lassen", verm, re.I) and v["signatur_ges"] not in vorstoss_v \
                and v["signatur_ges"] not in postulat_v and t not in ("Ratschlag", "Bericht", "Ausgabenbericht"):
            nicht_erfasst[(t, re.sub(r"\d{1,2}\.\d{1,2}\.\d{4}", "DATUM", verm))] += 1
    alle_vorstoesse = {v["signatur_ges"] for v in vorgaenge if v.get("ga_rr_gr") in ("Motion", "Anzug", "Planungsanzug")}
    pruef_voll = ["## Vollständigkeit Vorstösse",
                  f"Geschäftstypen in den Vorgängen: " + "; ".join(f"{k} ({n})" for k, n in typen.most_common()),
                  f"Motionen/Anzüge mit Vorgang seit Start: {len(alle_vorstoesse)}, davon als überwiesen erfasst: "
                  f"{len(alle_vorstoesse & set(vorstoss_v))}",
                  "Nicht erfasste Vermerke mit Überweisung: " + "; ".join(f"{k[0]}: {k[1]} ({n})" for k, n in nicht_erfasst.most_common(80)),
                  ""]
    pruef = ["# Prüfliste", "", *pruef_voll, "Vermerke Budgetpostulate: " + "; ".join(f"{k[1]} ({n})" for k, n in bp_vermerke.most_common()), "",
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

    def darlehen(posten):
        return sum(p["betrag"] for p in posten if p["art"] == "darlehen")

    def urheber(g):
        if not g:
            return None, None, []
        name = g.get("name_vorname_urheber") or g.get("vorname_urheber")
        if g.get("gremientyp_urheber") and g.get("gremientyp_urheber") != "Mitglied":
            name = g.get("vorname_urheber") or name
        mit = [{"name": n, "partei": p or partei_von.get(name_key(n))} for n, p in g.get("miturheber", [])]
        partei = partei_norm(g.get("partei_kname_urheber")) or partei_von.get(name_key(name))
        return name, partei, mit

    print("Grossratsbeschlüsse lesen", file=sys.stderr)
    ausgaben, gesehene_beschluesse = [], {}
    for sig, v in sorted(ausgaben_v.items(), key=lambda x: x[1]["siz_datum"]):
        datum = day(v["siz_datum"])
        url = beschluss_pdf(sig, datum)
        posten = posten_aus_text(pdf_text(url)) if url else []
        posten, korr, bem = mit_korrektur(sig, posten)
        einm, jaehrl = summen(posten)
        g = geschaefte.get(sig, {})
        pruef.append(f"## {datum} {sig} {v['titel_ges']}")
        pruef.append(f"Beschluss: {url or 'nicht gefunden'}" + (" (korrigiert)" if korr else ""))
        if url and not korr:
            summe = sum(p["jahresbetrag"] if p["art"] == "wiederkehrend" else p["betrag"] for p in posten)
            for gb in gesamtbetraege(pdf_text(url)):
                if abs(gb - summe) > 2:
                    f1, f2 = f"{gb:,}".replace(",", "'"), f"{summe:,}".replace(",", "'")
                    pruef.append(f"**Achtung:** Gesamtbetrag laut Beschluss Fr. {f1}, Summe der gelesenen Posten Fr. {f2}")
        for p in posten:
            pruef.append(f"- {p['art']}: Fr. {p['betrag']:,}".replace(",", "'") + f"  \n  «{p['quelle'][:400]}»")
        if not posten:
            pruef.append("- keine Ausgaben erkannt (wird auf der Seite nicht gezählt)")
        pruef.append("")
        if not posten:
            continue
        fingerprint = (datum, tuple(sorted((p["art"], p["betrag"]) for p in posten)))
        abst = abstimmung(sig, datum)
        if fingerprint in gesehene_beschluesse:
            frueher = gesehene_beschluesse[fingerprint]
            pruef.append(f"(gleicher Beschluss wie {frueher['signatur']}, nicht doppelt gezählt)")
            if not frueher["abstimmung"] and abst:
                frueher["abstimmung"] = abst
            continue
        eintrag = {
            "signatur": sig, "datum": datum, "titel": v["titel_ges"], "typ": v.get("ga_rr_gr"),
            "departement": re.sub(r"^\d+\s*", "", g.get("departement_ges") or "") or None, "url": v.get("url_ges") or g.get("url_ges"),
            "beschluss": url, "posten": posten, "einmalig": einm, "jaehrlich": jaehrl, "darlehen": darlehen(posten),
            "korrigiert": korr, "bemerkung": bem, "abstimmung": abst,
        }
        gesehene_beschluesse[fingerprint] = eintrag
        ausgaben.append(eintrag)

    postulate = []
    for sig, v in sorted(postulat_v.items(), key=lambda x: x[1]["siz_datum"]):
        datum = day(v["siz_datum"])
        url = beschluss_pdf(sig, datum, auch_vorstoss=True)
        posten = posten_aus_text(pdf_text(url)) if url else []
        if not posten and url:
            # Budgetpostulate: Betrag steht oft im Fliesstext («um Fr. … erhöhen»)
            t = re.sub(r"\s+", " ", pdf_text(url))
            m = re.search(r"(?:um|zusätzlich)\s+((?:Fr\.|CHF)\s*" + NUM + r"\s*(Mio\.?)?)", t)
            if m:
                posten = [{"art": "einmalig", "betrag": betrag(AMT.search(m.group(1))), "jahresbetrag": None,
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

    print("Kostenfolgen der Vorstösse lesen", file=sys.stderr)
    vorstoesse = []
    for sig, v in sorted(vorstoss_v.items(), key=lambda x: x[1]["siz_datum"]):
        g = geschaefte.get(sig, {})
        name, partei, mit = urheber(g)
        k = korrekturen.get(sig)
        if k and (k.get("ausschliessen") or "").strip().lower() in ("ja", "x", "1"):
            continue
        titel = v["titel_ges"]
        kosten = {"einmalig": 0, "jaehrlich": 0, "status": "offen", "quelle": None, "quelle_url": None, "datum": None}
        # 1. Hat der Grosse Rat zur Umsetzung bereits Ausgaben bewilligt? Dann ist die Kostenfolge fix.
        thema = re.split(r"\bbetreffend\b", titel, 1)
        thema = thema[1].strip()[:45].lower() if len(thema) > 1 else None
        umsetzung = [a for a in ausgaben if thema and len(thema) > 15 and thema in a["titel"].lower()]
        if umsetzung:
            u = umsetzung[-1]
            kosten.update(einmalig=u["einmalig"], jaehrlich=u["jaehrlich"], status="bewilligt",
                          quelle=f"Ausgabenbewilligung {u['signatur']}: {u['titel']}", quelle_url=u["url"], datum=u["datum"])
        else:
            # 2. Sonst: Kostenangaben aus Stellungnahmen und Berichten der Regierung (neuestes Dokument zuerst)
            docs = sorted(dokumente.get(sig, []), key=lambda d: d.get("dokudatum") or "", reverse=True)
            for d in docs:
                url = d.get("url_dok")
                if not url:
                    continue
                try:
                    angaben = kosten_aus_text(pdf_text(url))
                except Exception as e:  # noqa: BLE001
                    print(f"  {sig}: {e}", file=sys.stderr)
                    continue
                if angaben:
                    # Automatisch gefundene Kostenangaben sind oft Kontext (Vergleichszahlen, frühere Beschlüsse).
                    # Sie erscheinen nur in der Prüfliste; auf die Seite kommen sie erst nach Prüfung via korrekturen.csv.
                    erst = angaben[0]
                    kosten.update(status="offen", quelle=erst["satz"], quelle_text=erst["satz"], quelle_url=url, datum=day(d.get("dokudatum")),
                                  kandidat=f"{erst['betrag']:,}".replace(",", "'") + (" pro Jahr" if erst["wiederkehrend"] else ""))
                    break
        if k:
            kosten.update(einmalig=zahl(k.get("einmalig")), jaehrlich=zahl(k.get("jaehrlich")),
                          status=(k.get("status") or "beziffert").strip() or "beziffert")
        elif kosten["status"] == "offen":
            kosten.update(quelle=None, quelle_url=kosten["quelle_url"] if kosten.get("kandidat") else None)
        if kosten.get("kandidat") and not k:
            pruef.append(f"## Vorstoss {sig} {titel[:120]} (Kostenhinweis prüfen: Fr. {kosten['kandidat']})")
            pruef.append(f"Quelle: {kosten['quelle_url']}  \n«{(kosten.get('quelle_text') or '')[:400]}»")
            pruef.append("")
            kosten["quelle_url"] = None
        elif kosten["status"] != "offen":
            pruef.append(f"## Vorstoss {sig} {titel[:120]}")
            pruef.append(f"Kosten: {kosten['status']}, einmalig {kosten['einmalig']:,}, pro Jahr {kosten['jaehrlich']:,}".replace(",", "'")
                         + (f"  \n  «{kosten['quelle'][:400]}» ({kosten['quelle_url']})" if kosten["quelle"] else ""))
            pruef.append("")
        vorstoesse.append({
            "signatur": sig, "datum": day(v["siz_datum"]), "titel": titel, "typ": v.get("ga_rr_gr"),
            "vermerk": re.sub(r"\s*Frist:.*", "", v.get("vermerk") or ""),
            "url": v.get("url_ges") or g.get("url_ges"), "urheber": name, "partei": partei, "miturheber": mit,
            "einmalig": kosten["einmalig"], "jaehrlich": kosten["jaehrlich"], "status": kosten["status"],
            "quelle": (kosten["quelle"] or "")[:500] or None, "quelle_url": kosten["quelle_url"],
            "bemerkung": (k or {}).get("bemerkung"),
        })
    # Budgetpostulate sind Vorstösse mit fixer Kostenfolge (Budgeterhöhung)
    for b in postulate:
        vorstoesse.append({
            "signatur": b["signatur"], "datum": b["datum"], "titel": b["titel"], "typ": "Budgetpostulat",
            "vermerk": "Budgeterhöhung bewilligt", "url": b["url"], "urheber": b["urheber"], "partei": b["partei"],
            "miturheber": b["miturheber"], "einmalig": b["betrag"] or 0, "jaehrlich": 0,
            "status": "bewilligt" if b["betrag"] else "offen", "quelle": None, "quelle_url": None, "bemerkung": None,
        })

    ohne_partei = [v for v in vorstoesse if not v["partei"]]
    pruef.insert(2, f"Vorstösse ohne Partei: {len(ohne_partei)} von {len(vorstoesse)} ("
                 + ", ".join(sorted({str(v['urheber']) for v in ohne_partei}))[:1500] + ")")
    pruef.insert(3, "")
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
    (ROOT / "pruefliste.md").write_text("\n".join(pruef) + "\n", encoding="utf-8")

    template = (ROOT / "template.html").read_text(encoding="utf-8")
    page = template.replace("/*__DATEN__*/null", json.dumps(daten, ensure_ascii=False).replace("</", "<\\/"))
    passwort = os.environ.get("SITE_PASSWORD", "").strip()
    if passwort:
        # Seite verschlüsselt ausliefern; ohne Passwort ist nur die Anmeldemaske lesbar
        (DOCS / "index.html").write_text(verschluesseln(page, passwort), encoding="utf-8")
        (DOCS / "data.json").unlink(missing_ok=True)
    else:
        (DOCS / "index.html").write_text(page, encoding="utf-8")
        (DOCS / "data.json").write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Fertig: {len(ausgaben)} Ausgaben, {len(postulate)} Budgetpostulate, {len(vorstoesse)} Vorstösse",
          file=sys.stderr)


if __name__ == "__main__":
    main()
