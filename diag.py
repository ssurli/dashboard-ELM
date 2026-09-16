"""
Diagnostica connessione AT2.0/ELM.
Esegue il login (OAuth) e interroga alcuni endpoint 'integrazione' stampando
per ognuno lo stato HTTP e il corpo della risposta (utile per capire i 500).

Uso:
    python diag.py
(le credenziali vanno in .env o come variabili d'ambiente, come per il client)
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
    base_url=os.environ.get("AT20_BASE_URL", "https://at20test.consorziometis.it/elm/rest"),
    token_url=os.environ.get("AT20_TOKEN_URL", "https://at20test.consorziometis.it/mgca/rest/v2/oauth/token"),
    codice_azienda=os.environ.get("AT20_CODICE_AZIENDA", "202"),
    api_key=os.environ.get("AT20_API_KEY"),
    username=os.environ.get("AT20_USER"),
    password=os.environ.get("AT20_PASS"),
)

client = AT20ElmClient(cfg)

# --- 1) Token ---
try:
    tok = client._get_oauth_token()
    print("TOKEN: OK  (", tok[:16], "... )")
except Exception as e:
    print("TOKEN: FALLITO ->", repr(e))
    raise SystemExit(1)

headers = {"Authorization": f"Bearer {tok}", "apikey": cfg.api_key}


def probe(path, params=None):
    url = cfg.base_url.rstrip("/") + path
    try:
        r = requests.get(url, params=params or {}, headers=headers, timeout=30)
        body = (r.text or "").replace("\n", " ").strip()
        print(f"\n{path}  {params or ''}")
        print(f"  status : {r.status_code} {r.reason}")
        print(f"  body   : {body[:700]}")
    except Exception as exc:
        print(f"\n{path} -> ERRORE DI RETE: {exc!r}")
    time.sleep(0.6)   # rispetta il rate limit (2/s)


# --- 2) Endpoint di sola lettura, dal più semplice al più complesso ---
probe("/api/med/integrazione/mp/frequenza/")                    # lookup, nessun parametro
probe("/api/med/integrazione/mc/stato/")                        # lookup, nessun parametro
probe("/api/med/integrazione/cespite/", {"limit": 5, "offset": 0})
probe("/api/med/integrazione/cespite/", {"limit": 5, "offset": 0, "codiceAzienda": cfg.codice_azienda})
probe("/api/med/integrazione/cespite/", {"count": "true"})      # solo conteggio
probe("/api/med/integrazione/sistema/", {"limit": 5, "offset": 0})
probe("/api/med/integrazione/contratto/", {"limit": 5, "offset": 0})

print("\nFine diagnostica.")
