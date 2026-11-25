"""Einmaliger Erkundungslauf, Runde 2."""
import csv, io, json, re, subprocess, urllib.parse, urllib.request
from pathlib import Path
OUT = Path(__file__).resolve().parent / "proben"
OUT.mkdir(exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
API = "https://data.bs.ch/api/explore/v2.1/catalog/datasets"
def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-CH,de"})
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")
def save(name, text):
    (OUT / name).write_text(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1), encoding="utf-8")
def probe(name, fn):
    try:
        save(name, fn()); print("ok", name)
    except Exception as e:
        save(name, f"FEHLER: {e!r}"); print("fehler", name, e)

probe("100518.json", lambda: get(f"{API}/100518/records?limit=3&order_by=" + urllib.parse.quote("abstimmungsdatum desc")))
probe("100518b.json", lambda: get(f"{API}/100518/records?limit=3"))
probe("100518_meta.json", lambda: get(f"{API}/100518"))

def sv():
    rows = list(csv.DictReader(io.StringIO(get("https://swissvotes.ch/page/dataset/swissvotes_dataset.csv").lstrip("﻿")), delimiter=";"))
    keep = ["anr", "datum", "titel_kurz_d", "p-fdp", "pdev-fdp_BS", "p-lps", "pdev-lps_BS", "p-sps", "pdev-sps_BS", "bs-japroz", "volk"]
    out = [{k: r.get(k) for k in keep} for r in rows if (r.get("datum") or "")[-4:] >= "2021" or (r.get("datum") or "")[:4] >= "2021"]
    return json.dumps(out[-60:], ensure_ascii=False, indent=0)
probe("swissvotes_werte.json", sv)

def protokoll():
    rows = json.loads(get(f"{API}/100348/records?" + urllib.parse.urlencode({"where": 'tag1>="2026-01-01"', "limit": 3, "select": "tag1,url_vollprotokoll"})))["results"]
    url = rows[0]["url_vollprotokoll"]
    Path("/tmp/p.pdf").write_bytes(get(url, binary=True))
    txt = subprocess.run(["pdftotext", "-layout", "/tmp/p.pdf", "-"], capture_output=True, text=True).stdout
    lines = txt.splitlines()
    sprecher = [l for l in lines if re.search(r"\((FDP|LDP|SP|SVP|GLP)\)", l)]
    return url + f"\n{len(lines)} Zeilen\n\n" + "\n".join(lines[:250]) + "\n\n=== Zeilen mit Partei ===\n" + "\n".join(sprecher[:150])
probe("protokoll.txt", protokoll)

probe("ldp_mm_2025.html", lambda: get("https://www.ldp.ch/medienmitteilungen?jahr=2025")[:250000])
probe("ldp_mm_2025_s2.html", lambda: get("https://www.ldp.ch/medienmitteilungen?jahr=2025&seite=2")[:250000])
def fdp2():
    s = get("https://www.fdp-bs.ch/aktuell/medienmitteilungen")
    nxt = re.findall(r'href="(/aktuell/medienmitteilungen\?[^"]*currentPage%5D=2[^"]*)"', s)[0].replace("&amp;", "&")
    return get("https://www.fdp-bs.ch" + nxt)[:250000]
probe("fdp_mm_p2.html", fdp2)
probe("ldp_parolen_archiv.html", lambda: get("https://www.ldp.ch/parolen/archiv")[:250000])

def smartvote():
    from playwright.sync_api import sync_playwright
    got = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        def onresp(r):
            ct = r.headers.get("content-type", "")
            if "json" in ct:
                try:
                    got.append({"url": r.url, "body": r.text()[:6000]})
                except Exception as e:
                    got.append({"url": r.url, "err": str(e)})
        pg.on("response", onresp)
        for u in ["https://smartvote.ch/de/elections/24_bs_leg/smartmap", "https://smartvote.ch/de/smartspider?election_group_id=542"]:
            pg.goto(u, wait_until="networkidle", timeout=90000)
            pg.wait_for_timeout(4000)
        b.close()
    return json.dumps(got, ensure_ascii=False, indent=1)
probe("smartvote_netz.json", smartvote)
