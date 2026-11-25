"""Einmaliger Erkundungslauf: legt Stichproben der Quellen in ldp-fdp/proben ab."""
import json, subprocess, sys, urllib.parse, urllib.request
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
        save(name, fn())
        print("ok", name)
    except Exception as e:
        save(name, f"FEHLER: {e!r}")
        print("fehler", name, e)

def recs(ds, where=None, limit=4):
    q = {"limit": limit}
    if where: q["where"] = where
    return get(f"{API}/{ds}/records?" + urllib.parse.urlencode(q))

for ds in ["100308", "100309", "100399", "100408", "100348", "100101"]:
    probe(f"{ds}.json", lambda ds=ds: recs(ds))
probe("100308_fdp.json", lambda: recs("100308", 'partei_kname="FDP"', 6))
probe("100309_ldp.json", lambda: recs("100309", 'partei_kname="LDP"', 10))
for s in ["Grossratswahlen", "Grosser Rat", "Wahlen 2020", "Panaschier", "Wortmeldung", "Ratsprotokoll"]:
    probe(f"katalog_{s.replace(' ','_')}.json", lambda s=s: json.dumps([(d["dataset_id"], d["metas"]["default"]["title"]) for d in json.loads(get(f"{API}?" + urllib.parse.urlencode({"where": f'search("{s}")', "limit": 60})))["results"]], ensure_ascii=False, indent=0))

def protokoll():
    rows = json.loads(get(f"{API}/100348/records?" + urllib.parse.urlencode({"where": "url_vollprotokoll is not null", "limit": 3, "order_by": "datum desc"})))["results"]
    url = rows[0]["url_vollprotokoll"]
    pdf = get(url, binary=True)
    Path("/tmp/p.pdf").write_bytes(pdf)
    txt = subprocess.run(["pdftotext", "-layout", "/tmp/p.pdf", "-"], capture_output=True, text=True).stdout
    return url + "\n\n" + "\n".join(txt.splitlines()[:700])
probe("protokoll.txt", protokoll)

def swissvotes():
    csv = get("https://swissvotes.ch/page/dataset/swissvotes_dataset.csv")
    head = csv.splitlines()[0]
    cols = head.split(";")
    return json.dumps({"n": len(cols), "bs_ldp": [c for c in cols if "bs" in c.lower() or "ldp" in c.lower() or "lps" in c.lower()], "alle": cols}, ensure_ascii=False)
probe("swissvotes.json", swissvotes)

for name, url in {
    "gnews_fdp.xml": "https://news.google.com/rss/search?q=%22FDP%22+Basel-Stadt&hl=de&gl=CH&ceid=CH:de",
    "gnews_ldp.xml": "https://news.google.com/rss/search?q=LDP+Basel&hl=de&gl=CH&ceid=CH:de",
    "fdp_mm.html": "https://www.fdp-bs.ch/aktuell/medienmitteilungen",
    "fdp_parolen.html": "https://www.fdp-bs.ch/aktuell/parolen",
    "ldp_mm.html": "https://www.ldp.ch/medienmitteilungen",
    "ldp_parolen.html": "https://www.ldp.ch/parolen",
    "smartvote_parteien.html": "https://smartvote.ch/de/elections/24_bs_leg/parties",
    "smartvote_api.json": "https://smartvote.ch/api/elections/24_bs_leg/parties",
}.items():
    probe(name, lambda url=url: get(url)[:250000])
