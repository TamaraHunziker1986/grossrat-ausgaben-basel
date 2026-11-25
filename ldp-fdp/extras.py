"""Zusätzliche Auswertungen FDP/LDP: Ausgaben, Interessenbindungen, Parolen, Wahlen,
Smartvote, Kommissionen, Wortmeldungen, Medien.

Jede Auswertung läuft für sich. Fällt eine Quelle aus, bleibt der Abschnitt leer und die
Prüfliste nennt den Grund. Rückgabe von alle(): (daten, prueftexte).
"""
import csv
import datetime as dt
import email.utils
import html
import json
import re
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
CACHE = HIER / "cache"
API = "https://data.bs.ch/api/explore/v2.1/catalog/datasets"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
START = "2021-02-01"
MON = {m: i + 1 for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                        "september", "oktober", "november", "dezember"])}

PRUEF = []


def log(*a):
    print(*a, file=sys.stderr)


def get(url, binary=False, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-CH,de;q=0.9"})
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
            return b if binary else b.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            log(f"  Fehler {url[:120]}: {e}")
            time.sleep(3 * 2 ** i)


def export(ds, where=None, select=None):
    q = {"lang": "de", "timezone": "Europe/Zurich"}
    if where:
        q["where"] = where
    if select:
        q["select"] = select
    rows = json.loads(get(f"{API}/{ds}/exports/json?" + urllib.parse.urlencode(q)))
    log(f"  {ds}: {len(rows)} Zeilen")
    return rows


def text_von(html_s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", html_s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</(p|div|li|h\d|span|a|td|tr)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s)


def mehrheit(z):
    j, n = z.get("J", 0), z.get("N", 0)
    if j == 0 and n == 0:
        return None
    return "J" if j > n else "N" if n > j else "geteilt"


# ---------------------------------------------------------------- 1 Ausgaben

def ausgaben(leg_von):
    pfad = ROOT / "docs" / "data.json"
    d = json.loads(pfad.read_text(encoding="utf-8"))
    out = []
    for a in d.get("ausgaben", []):
        ab = a.get("abstimmung") or {}
        par = ab.get("parteien") or {}
        f, l = mehrheit(par.get("FDP", {})), mehrheit(par.get("LDP", {}))
        out.append({"sig": a.get("signatur"), "datum": a.get("datum"), "leg": leg_von(a.get("datum")),
                    "titel": a.get("titel"), "einmalig": a.get("einmalig") or 0, "jaehrlich": a.get("jaehrlich") or 0,
                    "fdp": f, "ldp": l, "url": a.get("url")})
    kosten = []
    for v in d.get("vorstoesse", []):
        if v.get("partei") in ("FDP", "LDP") and (v.get("einmalig") or v.get("jaehrlich")):
            kosten.append({"sig": v.get("signatur"), "datum": v.get("datum"), "leg": leg_von(v.get("datum")),
                           "titel": v.get("titel"), "partei": v.get("partei"), "einmalig": v.get("einmalig") or 0,
                           "jaehrlich": v.get("jaehrlich") or 0})
    PRUEF.append(f"Ausgaben: {len(out)} Geschäfte aus docs/data.json, {sum(1 for x in out if x['fdp'])} mit Abstimmungsdaten")
    return {"geschaefte": [x for x in out if x["leg"]], "vorstoss_kosten": kosten}


# ---------------------------------------------------------------- 2 Interessenbindungen

BRANCHEN = [
    ("Gewerbe, KMU und Wirtschaftsverbände", r"gewerbe|kmu|handwerk|wirteverband|gastro|detaillist|arbeitgeber|handelskammer|"
                                             r"hev\b|hauseigentümer|baumeister|verband.*(unternehm|wirtschaft|meister)|pro innerstadt|innerstadt|"
                                             r"messe|tourismus|basel tourismus|wirtschaftsverband|unternehmerverband|branchenverband"),
    ("Finanz, Versicherung, Immobilien", r"bank|versicher|vermögen|treuhand|finanz|pensionskasse|immobili|liegenschaft|"
                                         r"invest|asset|wealth|revision|kantonalbank|bkb"),
    ("Stiftungen", r"stiftung|fondation|foundation"),
    ("Kultur und Fasnacht", r"museum|theater|kultur|musik|kunst|orchester|fasnacht|clique|zunft|zünfte|gesellschaft zu|"
                            r"verein.*(kunst|kultur)|festival|kino|chor|literatur|bibliothek"),
    ("Gesundheit und Soziales", r"spital|klinik|pflege|gesundheit|sozial|heim\b|altersheim|spitex|ärzte|apothek|"
                                r"behindert|familie|kinder|jugend|ggg|caritas|heks|rotes kreuz|pro senectute|pro infirmis"),
    ("Bildung und Forschung", r"schul|universit|hochschul|bildung|fhnw|gymnas|forschung|institut|akadem|lehr"),
    ("Sport", r"sport|fc |fussball|tennis|ruder|schwimm|turn|ski|golf|club.*(sport|hockey|basket)|eishockey|handball|basketball"),
    ("Verkehr und Infrastruktur", r"tcs|verkehr|aviati|schifffahrt|hafen|lötschberg|bahn|acs\b|astag|flughafen|euroairport"),
    ("Kirche", r"kirche|kirchgemeinde|reformiert|katholisch|pfarr|synode"),
    ("Partei und Politik", r"\bfdp\b|\bldp\b|freisinn|liberal|jungfreisinn|jungliberal|partei|quartierverein|neutrales quartier"),
    ("Staat und Gemeinden", r"bürgerrat|bürgergemeinde|gemeinderat|einwohnerrat|kommission|gericht|kanton|bund\b|amt\b"),
    ("Unternehmen (VR, GL, Inhaber)", r"\bag\b|gmbh|\bsa\b|holding|verwaltungsrat|geschäftsführ|inhaber|partner|ceo|"
                                      r"geschäftsleitung|unternehm|firma|consult"),
]
_BR = [(n, re.compile(r, re.I)) for n, r in BRANCHEN]


def branche(text, rubrik):
    for n, r in _BR:
        if r.search(text):
            return n
    if rubrik and "staatlich" in rubrik.lower():
        return "Staat und Gemeinden"
    if re.search(r"verein", text, re.I):
        return "Vereine und Quartier"
    return "Übrige"


def interessen(partei_von):
    rows = export("100309")
    leute = defaultdict(set)
    zaehl = {p: Counter() for p in ("FDP", "LDP")}
    eintraege = []
    for r in rows:
        p = r.get("partei_kname") or partei_von.get(str(r.get("uni_nr") or ""))
        p = {"FDP": "FDP", "LDP": "LDP"}.get((p or "").strip())
        if not p:
            continue
        txt = r.get("text") or f"{r.get('intr_bind')} ({r.get('funktion')})"
        b = branche(txt, r.get("rubrik"))
        zaehl[p][b] += 1
        leute[p].add(r.get("name_vorname"))
        eintraege.append({"partei": p, "name": r.get("name_vorname"), "text": txt, "branche": b, "rubrik": r.get("rubrik")})
    PRUEF.append(f"Interessenbindungen: FDP {sum(zaehl['FDP'].values())}, LDP {sum(zaehl['LDP'].values())} Einträge")
    unbek = [e for e in eintraege if e["branche"] == "Übrige"]
    PRUEF.append("Interessenbindungen ohne Branche: " + "; ".join(f"{e['partei']}: {e['text']}" for e in unbek[:60]))
    return {"zaehl": {p: dict(c) for p, c in zaehl.items()}, "personen": {p: len(v) for p, v in leute.items()},
            "eintraege": sorted(eintraege, key=lambda e: (e["partei"], e["branche"], e["name"] or ""))}


# ---------------------------------------------------------------- 3 Parolen

def _parteien_in(liste):
    out = set()
    if not liste:
        return out
    if isinstance(liste, str):
        liste = re.split(r"[;,]", liste)
    for x in liste:
        s = (x or "").lower()
        if re.search(r"\bfdp\b|freisinn", s) and "jung" not in s:
            out.add("FDP")
        if re.search(r"\bldp\b|liberal-demokrat", s) and "jung" not in s:
            out.add("LDP")
    return out


def parolen_kantonal(leg_von):
    rows = export("100518", f"date>=date'{START}'")
    out = []
    for r in rows:
        ja, nein, frei = (_parteien_in(r.get("parteiparolen_ja")), _parteien_in(r.get("parteiparolen_nein")),
                          _parteien_in(r.get("stimmfreigabe")))

        def par(p):
            return "Ja" if p in ja else "Nein" if p in nein else "Stimmfreigabe" if p in frei else None
        out.append({"datum": r.get("date"), "leg": leg_von(r.get("date")), "titel": r.get("title") or r.get("offizieller_titel"),
                    "ergebnis": r.get("abstimmungsergebnis"), "ja_anteil": r.get("ja_anteil"), "fdp": par("FDP"),
                    "ldp": par("LDP"), "link": r.get("link_auf_baselvotes"), "ebene": "kantonal"})
    if rows:
        r = rows[-1]
        PRUEF.append(f"baselvotes Beispiel Parolen: ja={r.get('parteiparolen_ja')} nein={r.get('parteiparolen_nein')}")
    return out


SV_CODE = {"1": "Ja", "2": "Nein", "3": "Stimmfreigabe", "4": "Leer", "5": "Ja", "6": "Nein"}


def _norm_titel(t):
    t = re.sub(r"[«»\"'()]", " ", (t or "").lower())
    return set(w for w in re.findall(r"[a-zäöüé]{4,}", t) if w not in {"volksinitiative", "initiative", "bundesgesetz",
                                                                         "bundesbeschluss", "änderung", "gesetz", "über", "vom",
                                                                         "für", "eine", "einen", "eines", "durch", "zugunsten", "dezember"})


def parolen_eidg(leg_von):
    """FDP BS aus Swissvotes (Parole der FDP Schweiz, ausser die Kantonalpartei weicht ab), LDP von ldp.ch."""
    import io
    txt = get("https://swissvotes.ch/page/dataset/swissvotes_dataset.csv").lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(txt), delimiter=";"))
    sv = []
    for r in rows:
        try:
            d = dt.datetime.strptime(r["datum"], "%d.%m.%Y").date().isoformat()
        except Exception:  # noqa: BLE001
            continue
        if d < START or d > dt.date.today().isoformat():
            continue
        code = (r.get("pdev-fdp_BS") or "").strip() or (r.get("p-fdp") or "").strip()
        sv.append({"datum": d, "titel": r.get("titel_kurz_d"), "titel_off": r.get("titel_off_d"), "fdp": SV_CODE.get(code),
                   "volk": {"1": "angenommen", "0": "abgelehnt"}.get((r.get("volk") or "").strip())})
    ldp = ldp_parolen_eidg()
    out = []
    for s in sv:
        kand = [l for l in ldp if l["datum"] == s["datum"]]
        tok = _norm_titel((s["titel"] or "") + " " + (s["titel_off"] or ""))
        best, score = None, 0
        for l in kand:
            sc = len(tok & _norm_titel(l["titel"]))
            if sc > score:
                best, score = l, sc
        out.append({"datum": s["datum"], "leg": leg_von(s["datum"]), "titel": s["titel"], "ergebnis": s["volk"],
                    "fdp": s["fdp"], "ldp": best["parole"] if best and score >= 1 else None, "ebene": "eidgenössisch"})
    PRUEF.append(f"Parolen eidg.: {len(sv)} Vorlagen seit {START}, LDP-Parolen gefunden {len(ldp)}, zugeordnet "
                 f"{sum(1 for o in out if o['ldp'])}")
    return out


def ldp_parolen_eidg():
    """Liest das Parolenarchiv der LDP (ldp.ch/parolen und /parolen/archiv, mit Seiten)."""
    gefunden, gesehen = [], set()
    urls = ["https://www.ldp.ch/parolen", "https://www.ldp.ch/parolen/archiv"]
    i = 0
    while i < len(urls) and i < 40:
        url = urls[i]
        i += 1
        try:
            h = get(url)
        except Exception as e:  # noqa: BLE001
            PRUEF.append(f"LDP-Parolen {url}: {e}")
            continue
        for m in re.findall(r'href="([^"]*parolen[^"]*(?:seite|page|jahr)=[^"]*)"', h):
            u = urllib.parse.urljoin(url, html.unescape(m))
            if u not in urls:
                urls.append(u)
        t = text_von(h)
        zeilen = [z.strip() for z in t.split("\n") if z.strip()]
        datum, eidg = None, False
        for k, z in enumerate(zeilen):
            m = re.match(r"^(\d{1,2})\.\s*(\w+)\s+(20\d\d)$", z)
            if m and m.group(2).lower() in MON and (k == 0 or not zeilen[k - 1].startswith("Parteiversammlung")):
                datum = f"{m.group(3)}-{MON[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
                eidg = False
                continue
            if z.startswith("Eidgenössische"):
                eidg = True
                continue
            if z.startswith("Kantonale"):
                eidg = False
                continue
            if eidg and datum and z in ("Ja", "Nein", "Stimmfreigabe", "Leer") and k + 2 < len(zeilen) \
                    and zeilen[k + 2] == z and len(zeilen[k + 1]) > 8:
                key = (datum, zeilen[k + 1])
                if key not in gesehen:
                    gesehen.add(key)
                    gefunden.append({"datum": datum, "titel": zeilen[k + 1], "parole": z})
    return gefunden


def parolen(leg_von):
    out = {"kantonal": [], "eidg": []}
    try:
        out["kantonal"] = parolen_kantonal(leg_von)
    except Exception as e:  # noqa: BLE001
        PRUEF.append(f"Parolen kantonal Fehler: {e!r}")
    try:
        pass  # eidgenössische Parolen nicht ausgewertet
    except Exception as e:  # noqa: BLE001
        PRUEF.append(f"Parolen eidg. Fehler: {e!r}")
    return out


# ---------------------------------------------------------------- 4 Wahlen

def _wahl_partei(kurz, name):
    s = f"{kurz} {name}".lower()
    if re.search(r"\bfdp\b|freisinn", s):
        return "FDP"
    if re.search(r"\bldp\b|liberal-demokrat", s):
        return "LDP"
    if "svp" in s:
        return "SVP"
    if "glp" in s or "grünlib" in s:
        return "GLP"
    if "mitte" in s or "cvp" in s:
        return "Mitte"
    if "evp" in s:
        return "EVP"
    if re.search(r"\bsp\b|sozialdem", s):
        return "SP"
    if "basta" in s and "grün" not in s:
        return "BastA!"
    if "grün" in s or re.search(r"\bgb\b", s):
        return "Grüne"
    return "Andere"


def wahlen():
    out = {}
    for jahr, ds in (("2020", "100101"), ("2024", "100399")):
        rows = export(ds)
        listen = {}
        quellen_spalten = [k for k in rows[0] if re.match(r"^\d\d_", k)] if rows else []
        spalte_partei = {}
        for r in rows:
            nr = str(r.get("listen_nr") or "").zfill(2)
            p = _wahl_partei(r.get("parteikurzbezeichnung"), r.get("parteibezeichnung"))
            for k in quellen_spalten:
                if k.startswith(nr + "_"):
                    spalte_partei[k] = p
        for k in quellen_spalten:
            spalte_partei.setdefault(k, _wahl_partei(k[3:], ""))
        stimmen = defaultdict(Counter)   # wahlkreis -> partei -> parteistimmen
        fremd = {p: Counter() for p in ("FDP", "LDP")}  # herkunftspartei -> stimmen
        gewaehlt = Counter()
        for r in rows:
            wk = (r.get("wahlkreisbezeichnung") or "").replace("Wahlkreis ", "")
            nr = str(r.get("listen_nr") or "").zfill(2)
            p = _wahl_partei(r.get("parteikurzbezeichnung"), r.get("parteibezeichnung"))
            key = (wk, nr)
            if key not in listen:
                listen[key] = p
                tot = sum(int(r.get(f) or 0) for f in ("kandidatenstimmen_unveranderte_wahlzettel", "zusatzstimmen_unveranderte_wahlzettel",
                                                        "kandidatenstimmen_veranderte_wahlzettel", "zusatzstimmen_veranderte_wahlzettel"))
                stimmen[wk][p] += tot
            if (r.get("gewahlt") or "").lower().startswith("gew"):
                gewaehlt[p] += 1
            if p in fremd:
                for k in quellen_spalten:
                    q = spalte_partei.get(k)
                    if k.startswith("00_") or q == p:
                        continue
                    fremd[p][q] += int(r.get(k) or 0)
        anteile = {}
        for wk, c in stimmen.items():
            tot = sum(c.values())
            anteile[wk] = {p: round(100 * v / tot, 2) for p, v in c.items() if tot}
        total = Counter()
        for c in stimmen.values():
            total.update(c)
        tt = sum(total.values())
        anteile["Kanton"] = {p: round(100 * v / tt, 2) for p, v in total.items() if tt}
        out[jahr] = {"anteile": anteile, "fremd": {p: dict(c) for p, c in fremd.items()}, "sitze": dict(gewaehlt)}
    PRUEF.append("Wahlen: " + "; ".join(f"{j}: FDP {o['anteile']['Kanton'].get('FDP')} %, LDP {o['anteile']['Kanton'].get('LDP')} %, "
                                          f"Sitze {o['sitze'].get('FDP')}/{o['sitze'].get('LDP')}" for j, o in out.items()))
    return out


# ---------------------------------------------------------------- 5 Smartvote

SMARTVOTE_ACHSEN = ["Offene Aussenpolitik", "Liberale Wirtschaftspolitik", "Restriktive Finanzpolitik", "Law & Order",
                    "Restriktive Migrationspolitik", "Ausgebauter Umweltschutz", "Ausgebauter Sozialstaat", "Liberale Gesellschaft"]


def smartvote():
    pfad = HIER / "smartvote.csv"
    werte = {}
    if pfad.exists():
        with pfad.open(encoding="utf-8") as f:
            for row in csv.DictReader(r for r in f if not r.startswith("#")):
                a = (row.get("achse") or "").strip()
                if a:
                    werte[a] = {p: (float(row[p]) if (row.get(p) or "").strip() else None) for p in ("FDP", "LDP")}
    return {"achsen": SMARTVOTE_ACHSEN, "werte": werte}


# ---------------------------------------------------------------- 6 Kommissionen

def kommissionen(partei_von, legislaturen):
    rows = export("100308", f"gremientyp=\"Kommission\" and (ende_mit>=date'{START}' or ende_mit is null)")
    out = {}
    for leg in legislaturen:
        stich = (dt.date.fromisoformat(leg["von"]) + dt.timedelta(days=120)).isoformat()
        heute = dt.date.today().isoformat()
        if stich > heute:
            stich = heute
        z = {}
        for r in rows:
            b, e = str(r.get("beginn_mit") or "")[:10], str(r.get("ende_mit") or "")[:10]
            if not (b <= stich and (not e or e >= stich)):
                continue
            p = r.get("partei_kname") or partei_von.get(str(r.get("uni_nr_adr") or ""))
            if p not in ("FDP", "LDP"):
                continue
            g = r.get("name_gre") or r.get("kurzname_gre")
            e = z.setdefault(g, {"kurz": r.get("kurzname_gre"), "FDP": [], "LDP": [], "praesidium": None})
            f = r.get("funktion_adr") or ""
            e[p].append(r.get("name_vorname") + (f" ({f})" if f else ""))
            if re.search(r"präsident", f, re.I) and not re.search(r"vize", f, re.I):
                e["praesidium"] = p
        out[leg["id"]] = z
    PRUEF.append("Kommissionen: " + "; ".join(f"{k}: {len(v)} Gremien mit FDP/LDP" for k, v in out.items()))
    return out


# ---------------------------------------------------------------- 7 Wortmeldungen

SPRECHER = re.compile(r"^[ \t]*([A-ZÄÖÜ][\w\-\.'éèàç]+(?:[ \t]+[A-ZÄÖÜ][\w\-\.'éèàç]+){0,4})[ \t]*"
                      r"\((FDP|LDP|SP|SVP|GLP|Grüne|GRÜNE|BastA!?|BastA|Mitte|EVP|Mitte-EVP|jgb|JGB|GAB|fraktionslos)\)[ \t]*:", re.M)
ZF_KOPF = re.compile(r"^[ \t]*Zwischenfragen?[ \t]*$")


def zerlege_protokoll(txt, partei_norm):
    """Liefert (partei, name, art) für jede Wortmeldung. art = 'wort' oder 'zf' (Zwischenfrage).
    Antworten des Redners auf Zwischenfragen werden nicht gezählt."""
    zeilen = txt.splitlines()
    eintraege = []  # (index, name, partei_roh, text)
    for k, z in enumerate(zeilen):
        if ZF_KOPF.match(z):
            eintraege.append((k, None, "ZF", ""))
            continue
        m = SPRECHER.match(z)
        if m:
            text = z[m.end():] + " " + " ".join(zeilen[k + 1:k + 4])
            eintraege.append((k, re.sub(r"\s+", " ", m.group(1)).strip(), m.group(2), text[:700]))
    out, block, redner = [], False, None
    for _, name, roh, text in eintraege:
        if roh == "ZF":
            block = True
            continue
        p = partei_norm(roh)
        if block:
            if name == redner:
                continue  # Antwort auf die Zwischenfrage
            if "?" in text:
                out.append((p, name, "zf"))
                continue
            block = False
        out.append((p, name, "wort"))
        redner = name
    return out


def wortmeldungen(legislaturen, partei_norm):
    cache = CACHE / "protokolle"
    cache.mkdir(parents=True, exist_ok=True)
    rows = export("100348", f"tag1>=date'{START}'", "tag1,url_vollprotokoll")
    mit_url = {str(r.get("tag1"))[:10]: r.get("url_vollprotokoll") for r in rows if r.get("url_vollprotokoll")}
    alle_tage = {str(r.get("tag1"))[:10] for r in rows if r.get("tag1")}
    for t in alle_tage - set(mit_url):
        mit_url[t] = f"https://grosserrat.bs.ch/media/files/ratsprotokolle/vollprotokoll_{t}.pdf"
    urls = sorted(mit_url.items())
    zaehl = defaultdict(lambda: defaultdict(lambda: {"wort": Counter(), "zf": Counter()}))
    tage = defaultdict(list)
    fehlend = []
    for datum, url in urls:
        if datum > dt.date.today().isoformat():
            continue
        f = cache / (datum + ".txt")
        if not f.exists():
            try:
                pdf = get(url, binary=True, tries=1)
            except Exception as e:  # noqa: BLE001
                fehlend.append(datum)
                log(f"  Protokoll {datum}: {e}")
                continue
            tmp = Path("/tmp/protokoll.pdf")
            tmp.write_bytes(pdf)
            txt = subprocess.run(["pdftotext", "-layout", str(tmp), "-"], capture_output=True, text=True).stdout
            if len(txt) < 2000:
                fehlend.append(datum)
                continue
            f.write_text(txt, encoding="utf-8")
        leg = next((l["id"] for l in legislaturen if l["von"] <= datum <= l["bis"]), None)
        if not leg:
            continue
        tage[leg].append(datum)
        for p, name, art in zerlege_protokoll(f.read_text(encoding="utf-8"), partei_norm):
            if p:
                zaehl[leg][p][art][name] += 1
    PRUEF.append(f"Wortmeldungen: {sum(len(v) for v in tage.values())} Protokolle gelesen, nicht verfügbar: {', '.join(fehlend) or 'keine'}")
    res = {"sitzungen": {l: len(v) for l, v in tage.items()},
           "zeitraum": {l: [min(v), max(v)] for l, v in tage.items() if v},
           "zaehl": {}}
    for l, d in zaehl.items():
        res["zaehl"][l] = {}
        for p, c in d.items():
            pers = Counter()
            pers.update(c["wort"]); pers.update(c["zf"])
            res["zaehl"][l][p] = {"total": sum(c["wort"].values()), "zf": sum(c["zf"].values()),
                                  "personen": {n: [c["wort"].get(n, 0), c["zf"].get(n, 0)] for n, _ in pers.most_common(25)}}
    return res


# ---------------------------------------------------------------- 8 Medien

def _datum_de(s):
    m = re.search(r"(\d{1,2})\s*\.\s*(\w+)\s+(20\d\d)", s)
    if m and m.group(2).lower() in MON:
        return f"{m.group(3)}-{MON[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(20\d\d)", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def mm_fdp():
    out, url, seiten = [], "https://www.fdp-bs.ch/aktuell/medienmitteilungen", 0
    while url and seiten < 80:
        seiten += 1
        h = get(url)
        for m in re.finditer(r'href="(/aktuell/medienmitteilungen/medienmitteilungen-detail/news/[^"]+)"', h):
            pass
        t = text_von(h)
        zeilen = [z.strip() for z in t.split("\n") if z.strip()]
        # Datum steht als «20», «. November 2026», danach der Titel
        k = 0
        while k < len(zeilen):
            z = zeilen[k]
            kombi = z + (" " + zeilen[k + 1] if k + 1 < len(zeilen) else "")
            d = _datum_de(kombi) if re.match(r"^\d{1,2}$", z) else None
            if d and k + 2 < len(zeilen):
                titel = zeilen[k + 2]
                out.append({"datum": d, "titel": titel})
                k += 3
                continue
            k += 1
        nxt = re.findall(rf'href="(/aktuell/medienmitteilungen\?[^"]*currentPage%5D={seiten + 1}[^"]*)"', h)
        url = "https://www.fdp-bs.ch" + html.unescape(nxt[0]) if nxt else None
        if out and min(o["datum"] for o in out) < START:
            break
    return out


def mm_ldp():
    out = []
    for jahr in range(int(START[:4]), dt.date.today().year + 1):
        for seite in range(1, 15):
            h = get(f"https://www.ldp.ch/medienmitteilungen?jahr={jahr}" + (f"&seite={seite}" if seite > 1 else ""))
            t = text_von(h)
            zeilen = [z.strip() for z in t.split("\n") if z.strip()]
            neu = 0
            for k, z in enumerate(zeilen):
                if z == "Medienmitteilung" and k + 2 < len(zeilen):
                    d = _datum_de(zeilen[k + 1])
                    titel = next((x for x in zeilen[k + 2:k + 6] if len(x) > 8 and not _datum_de(x)), None)
                    if d and titel:
                        out.append({"datum": d, "titel": titel})
                        neu += 1
            if not neu or f"seite={seite + 1}" not in h:
                break
    return out


GNEWS = {
    "FDP": '"FDP Basel" OR "Basler FDP" OR "FDP Basel-Stadt" OR "FDP-Grossrat" OR "FDP-Grossrätin" OR "Basler Freisinn"',
    "LDP": '"LDP Basel" OR "Basler LDP" OR "LDP Basel-Stadt" OR "LDP-Grossrat" OR "LDP-Grossrätin" OR "Basler Liberalen"',
}


def medien_news():
    pfad = CACHE / "medien.json"
    cache = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    heute = dt.date.today()
    monate = []
    d = dt.date(int(START[:4]), int(START[5:7]), 1)
    while d <= heute:
        monate.append(d)
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    for p, q in GNEWS.items():
        for m in monate:
            key = f"{p}:{m.isoformat()[:7]}"
            ende = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            # abgeschlossene Monate nur einmal holen, die letzten zwei jedes Mal neu
            if key in cache and ende < heute - dt.timedelta(days=45):
                continue
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": f"({q}) after:{m.isoformat()} before:{ende.isoformat()}", "hl": "de", "gl": "CH", "ceid": "CH:de"})
            try:
                x = get(url)
            except Exception as e:  # noqa: BLE001
                log(f"  News {key}: {e}")
                continue
            items = []
            for it in re.findall(r"<item>(.*?)</item>", x, re.S):
                t = re.search(r"<title>(.*?)</title>", it, re.S)
                s = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
                pd = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
                try:
                    datum = email.utils.parsedate_to_datetime(pd.group(1)).date().isoformat() if pd else None
                except Exception:  # noqa: BLE001
                    datum = None
                items.append({"t": html.unescape(t.group(1)) if t else "", "q": html.unescape(s.group(1)) if s else "", "d": datum})
            cache[key] = items
            time.sleep(1.2)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    pro_monat = {p: {} for p in GNEWS}
    quellen = {p: Counter() for p in GNEWS}
    titel = {p: [] for p in GNEWS}
    for key, items in cache.items():
        p, mon = key.split(":")
        pro_monat[p][mon] = len(items)
        for it in items:
            quellen[p][it["q"]] += 1
            titel[p].append(it)
    return {"pro_monat": pro_monat, "quellen": {p: dict(c.most_common(12)) for p, c in quellen.items()},
            "titel": {p: sorted(v, key=lambda x: x.get("d") or "", reverse=True)[:400] for p, v in titel.items()},
            "max_pro_monat": 100}


def medien(thema_von, leg_von):
    out = {"mm": {}, "news": None}
    for p, fn in (("FDP", mm_fdp), ("LDP", mm_ldp)):
        try:
            mm = [m for m in fn() if m["datum"] >= START]
            seen, uniq = set(), []
            for m in sorted(mm, key=lambda x: x["datum"], reverse=True):
                if (m["datum"], m["titel"]) not in seen:
                    seen.add((m["datum"], m["titel"]))
                    uniq.append({**m, "leg": leg_von(m["datum"]), "thema": thema_von(m["titel"])})
            out["mm"][p] = uniq
            PRUEF.append(f"Medienmitteilungen {p}: {len(uniq)} seit {START}; neueste: " + "; ".join(f"{m['datum']} {m['titel']}" for m in uniq[:4]))
        except Exception as e:  # noqa: BLE001
            PRUEF.append(f"Medienmitteilungen {p} Fehler: {e!r}")
    try:
        out["news"] = medien_news()
    except Exception as e:  # noqa: BLE001
        PRUEF.append(f"Google News Fehler: {e!r}")
    return out


# ---------------------------------------------------------------- alle

def alle(partei_von, legislaturen, leg_von, thema_von, partei_norm):
    res = {}
    schritte = [
        ("ausgaben", lambda: ausgaben(leg_von)),
        ("wahlen", wahlen),
        ("kommissionen", lambda: kommissionen(partei_von, legislaturen)),
        ("wortmeldungen", lambda: wortmeldungen(legislaturen, partei_norm)),
    ]
    for name, fn in schritte:
        log(f"Zusatz: {name}")
        try:
            res[name] = fn()
        except Exception as e:  # noqa: BLE001
            res[name] = None
            PRUEF.append(f"{name}: FEHLER {e!r}\n" + traceback.format_exc()[-1200:])
    return res, PRUEF
