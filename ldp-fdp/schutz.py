"""Passwortschutz wie auf der Ausgaben-Seite: AES-GCM, Schlüssel per PBKDF2 aus dem Passwort.
Das Passwort kommt aus dem GitHub-Secret SITE_PASSWORD (gleiches Passwort für beide Seiten)."""
import base64
import hashlib
import json
import os
import re

ITERATIONEN = 250_000

ANMELDUNG = """<!DOCTYPE html>
<html lang="de-CH"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>FDP und LDP im Grossen Rat | FDP Kanton Basel-Stadt</title>
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
<main><h1>FDP und LDP im Grossen Rat</h1><p>Interne Analyse der FDP Basel-Stadt. Bitte Passwort eingeben.</p>
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


def entschluesseln(seite, passwort):
    """Gibt das HTML einer verschlüsselten Seite zurück (für die Daten der Ausgaben-Seite)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    m = re.search(r"const P = (\{.*?\});", seite, re.S)
    p = json.loads(m.group(1))
    key = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), base64.b64decode(p["salt"]), p["iter"], dklen=32)
    return AESGCM(key).decrypt(base64.b64decode(p["iv"]), base64.b64decode(p["data"]), None).decode("utf-8")


def daten_aus_seite(html, marke="const D = "):
    i = html.index(marke) + len(marke)
    obj, _ = json.JSONDecoder().raw_decode(html[i:])
    return obj
