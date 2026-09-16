"""
Diagnostica AUTENTICAZIONE AT2.0/ELM.
Il token viene ottenuto correttamente ma tutti gli endpoint 'integrazione' danno 500:
questo script prova diverse combinazioni di posizionamento di access_token e apikey
(header vs query parameter) sullo stesso endpoint semplice, per capire quale accetta.

Uso:  python diag_auth.py
"""
import os
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from at20_elm_client import AT20Config, AT20ElmClient

cfg = AT20Config(
    api_key=os.environ.get("AT20_API_KEY"),
    username=os.environ.get("AT20_USER"),
    password=os.environ.get("AT20_PASS"),
)
client = AT20ElmClient(cfg)

try:
    tok = client._get_oauth_token()
    print("TOKEN: OK (", tok[:16], "... )")
except Exception as e:
    print("TOKEN: FALLITO ->", repr(e))
    raise SystemExit(1)

KEY = cfg.api_key
# Endpoint di lookup: nessun parametro, nessuna dipendenza dai dati.
PATH = "/api/med/integrazione/mp/frequenza/"
URL = cfg.base_url.rstrip("/") + PATH

# Ogni variante: (etichetta, headers, params-extra)
varianti = [
    ("1 Bearer header + apikey header",
     {"Authorization": f"Bearer {tok}", "apikey": KEY}, {}),
    ("2 apikey header + access_token query",
     {"apikey": KEY}, {"access_token": tok}),
    ("3 access_token query + apikey query (nessun header)",
     {}, {"access_token": tok, "apikey": KEY}),
    ("4 Bearer header + apikey query",
     {"Authorization": f"Bearer {tok}"}, {"apikey": KEY}),
    ("5 token header 'access_token' + apikey header",
     {"access_token": tok, "apikey": KEY}, {}),
    ("6 Authorization senza 'Bearer' + apikey header",
     {"Authorization": tok, "apikey": KEY}, {}),
]

for label, headers, params in varianti:
    try:
        r = requests.get(URL, headers=headers, params=params, timeout=30)
        body = (r.text or "").replace("\n", " ").strip()
        marca = "  <<< OK" if r.status_code == 200 else ""
        print(f"\n[{label}]")
        print(f"  status: {r.status_code} {r.reason}{marca}")
        if r.status_code != 200:
            print(f"  body  : {body[:180]}")
        else:
            print(f"  body  : {body[:300]}")
    except Exception as exc:
        print(f"\n[{label}] -> ERRORE DI RETE: {exc!r}")
    time.sleep(0.7)   # rate limit

print("\nFine. Se una variante ha dato 200, e' quella giusta: fammelo sapere.")
