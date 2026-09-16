"""
sync.py — Scarica il parco apparecchiature da ELM e lo salva in cache su file.

Motivazione: l'endpoint ELM ha ~2,5s di overhead per richiesta e il parco conta
decine di migliaia di cespiti, quindi un caricamento completo richiede minuti. La
dashboard NON deve farlo a ogni avvio: gira questo script (a mano o schedulato),
che salva `parco.parquet`; la dashboard poi legge la cache in millisecondi.

Uso:
    python sync.py            # sincronizzazione completa (lenta, una tantum)
    python sync.py --incrementale   # solo i cespiti modificati dall'ultima sync

Le credenziali si leggono da .env / variabili d'ambiente, come per il resto.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

from at20_elm_client import AT20Config, AT20ElmClient
import data_source as ds

CACHE_PATH = Path(__file__).with_name("parco.parquet")
META_PATH = Path(__file__).with_name("parco.meta.json")


def _cfg() -> AT20Config:
    return AT20Config(
        base_url=os.environ.get("AT20_BASE_URL", "https://at20test.consorziometis.it/elm/rest"),
        token_url=os.environ.get("AT20_TOKEN_URL", "https://at20test.consorziometis.it/mgca/rest/v2/oauth/token"),
        codice_azienda=os.environ.get("AT20_CODICE_AZIENDA", "202"),
        api_key=os.environ.get("AT20_API_KEY"),
        username=os.environ.get("AT20_USER"),
        password=os.environ.get("AT20_PASS"),
    )


def _normalizza(righe_normalizzate: list[dict]) -> pd.DataFrame:
    """Rimappa righe già normalizzate (da AT20ElmClient.build_parco_apparecchiature,
    quindi con 'classe'/'unita_operativa'/'tipo_record' già valorizzati) sullo schema
    COLONNE, riusando data_source.mappa_cespiti_a_schema() — lo stesso punto di
    mappatura usato da carica_api(), per non duplicare (e disallineare) la
    corrispondenza dei campi. La sync in blocco non arricchisce per-cespite (rate
    limit): le scadenze restano non disponibili finché non verranno arricchite on-demand."""
    df = ds.mappa_cespiti_a_schema(pd.DataFrame(righe_normalizzate))
    for col in ("scadenza_contratto", "scadenza_vse", "scadenza_cq"):
        df[col] = pd.NaT
    return df.reindex(columns=ds.COLONNE)


def sincronizza(incrementale: bool = False) -> None:
    cfg = _cfg()
    client = AT20ElmClient(cfg)

    # Filtro grandi apparecchiature ESATTO: stesso meccanismo di data_source.carica_api()
    # (classi con flag grandeApparecchiatura=True da MgCA). Senza questo, get_cespiti()
    # scarica l'intero inventario elettromedicale aziendale (pompe, monitor, PC, ~56.000
    # record), non solo TAC/RM/mammografi/ecc. Se MgCA non risponde, il client ricade
    # sull'euristica per parola chiave.
    try:
        from mgca_client import MgcaClient
        codici = MgcaClient(cfg).codici_classe_grandi_apparecchiature()
        if codici:
            cfg.grandi_classi_codici = codici
            print(f"Filtro grandi apparecchiature: {len(codici)} classi da MgCA.")
        else:
            print("MgCA non ha restituito classi 'grandeApparecchiatura': uso l'euristica per parola chiave.")
    except Exception as exc:                                  # noqa: BLE001
        print(f"Attenzione: filtro MgCA non disponibile ({exc}); uso l'euristica per parola chiave.")

    data_da = None
    if incrementale and META_PATH.exists():
        data_da = json.loads(META_PATH.read_text()).get("ultima_sync")
        print(f"Sync incrementale dai record modificati dopo {data_da}")

    inizio = _dt.datetime.now(_dt.timezone.utc)
    print("Conteggio parco…")
    tot = client._get("/api/med/integrazione/cespite/", {"count": "true"})
    print("Cespiti totali dichiarati (intero inventario ELM, non filtrato):", tot)

    print("Scaricamento e filtro grandi apparecchiature (può richiedere alcuni minuti)…")
    righe = client.build_parco_apparecchiature(
        solo_grandi=True, arricchisci=False, data_da=data_da)
    print(f"Grandi apparecchiature trovate: {len(righe)}")

    df_nuovo = _normalizza(righe)

    if incrementale and CACHE_PATH.exists() and not df_nuovo.empty:
        vecchio = pd.read_parquet(CACHE_PATH)
        df = (pd.concat([vecchio, df_nuovo])
                .drop_duplicates(subset="n_inventario", keep="last"))
    else:
        df = df_nuovo

    df.to_parquet(CACHE_PATH, index=False)
    META_PATH.write_text(json.dumps({
        "ultima_sync": inizio.strftime("%Y-%m-%dT%H:%M:%S"),
        "righe": int(len(df)),
    }))
    print(f"Cache salvata: {CACHE_PATH.name} ({len(df)} righe).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sincronizza il parco ELM in cache su file.")
    ap.add_argument("--incrementale", action="store_true",
                    help="Scarica solo i cespiti modificati dall'ultima sincronizzazione.")
    args = ap.parse_args()
    sincronizza(incrementale=args.incrementale)
