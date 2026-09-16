"""
Layer sorgente dati del cruscotto Grandi Apparecchiature.

Due sorgenti, stesso schema di uscita (DataFrame normalizzato):
  - "nsis": estrazione Excel NSIS (fallback offline, funziona subito);
  - "api" : API AT2.0/ELM tramite at20_elm_client (quando l'ambiente sarà attivo).

La UII (app.py) lavora solo su questo schema, così passare da NSIS ad API non
richiede modifiche all'interfaccia.
"""
from __future__ import annotations

import datetime as _dt
import pandas as pd

import config


# Colonne del DataFrame normalizzato prodotto da entrambe le sorgenti.
COLONNE = [
    "n_inventario", "descrizione", "tipologia", "fabbricante", "modello",
    "zona", "sede", "data_collaudo", "anno_collaudo", "anzianita_anni",
    "soglia_vetusta", "vetusto", "stato_vetusta", "modalita_acquisizione", "pnrr", "note",
    "valore_economico", "scadenza_contratto", "scadenza_vse", "scadenza_cq",
    "tipo_record", "ha_padre", "componente",
]


# --------------------------------------------------------------------------- #
# Helper di normalizzazione
# --------------------------------------------------------------------------- #
def _norm_fabbricante(v) -> str:
    s = str(v or "").strip()
    low = s.lower()
    for chiave, nome in config.ALIAS_FABBRICANTE.items():
        if chiave in low:
            return nome
    return s.title() if s else "n.d."


def _modalita_da_note(note) -> str | None:
    t = str(note or "").lower()
    if not t.strip():
        return None
    if "riscatt" in t:
        return "Proprietà (riscattata)"
    if "locazione" in t:
        return "Locazione"
    if "noleggio" in t:
        return "Noleggio"
    if "service" in t:
        return "Service"
    return None


def _soglia(tipologia: str) -> int:
    return config.SOGLIE_VETUSTA.get(str(tipologia).strip().upper(),
                                     config.SOGLIA_VETUSTA_DEFAULT)


def _parse_data_collaudo(col: pd.Series) -> pd.Series:
    """DATACOLLAUDO nel NSIS è una colonna mista: quasi sempre una data completa,
    ma per alcune righe è un intero che rappresenta solo l'anno (es. 2013, senza
    giorno/mese). pd.to_datetime() interpreterebbe un intero nudo come timestamp
    Unix in NANOSECONDI (2013 -> 1° gennaio 1970!), gonfiando artificialmente
    l'anzianità. Lo intercettiamo e lo trattiamo come 1° gennaio dell'anno indicato."""
    def _a_data(v):
        if isinstance(v, bool) or v is None:
            return pd.NaT
        if isinstance(v, (int, float)) and not pd.isna(v):
            anno = int(v)
            return pd.Timestamp(year=anno, month=1, day=1) if 1900 <= anno <= 2100 else pd.NaT
        return pd.to_datetime(v, errors="coerce")
    return col.map(_a_data)


def _stato_vetusta(anzianita: pd.Series, soglia: pd.Series) -> pd.Series:
    """OK / In avvicinamento (entro il margine sotto soglia) / Vetusto / n.d."""
    margine = config.MARGINE_AVVICINAMENTO_ANNI
    stato = pd.Series("OK", index=anzianita.index)
    stato[(anzianita >= soglia - margine) & (anzianita <= soglia)] = "In avvicinamento"
    stato[anzianita > soglia] = "Vetusto"
    stato[anzianita.isna()] = "n.d."
    return stato


def _e_accessorio_per_nome(tipologia) -> bool:
    t = str(tipologia or "").lower()
    return any(kw in t for kw in config.PAROLE_CHIAVE_ACCESSORIO)


def _classifica_componente(tipologia: pd.Series, ha_padre: pd.Series | None = None) -> pd.Series:
    """'Accessorio / Consolle' vs 'Apparecchiatura principale'.

    Criterio robusto quando disponibile: legame padre-figlio del cespite ELM
    (refPadreId/refPadreNumero valorizzati -> è un accessorio del cespite padre;
    campo 'padre' del Cespite_ELM). Le parole chiave sulla tipologia (es.
    'consolle', 'iniettore per') restano il FALLBACK per i record dove il legame
    non è popolato: verificato sull'ambiente di test che accade spesso anche su
    accessori veri e propri. Nel NSIS (nessun legame padre-figlio) si usa solo
    la parola chiave, innocuo perché le categorie NSIS non includono accessori."""
    per_nome = tipologia.map(_e_accessorio_per_nome)
    if ha_padre is not None:
        # apply invece di fillna(False): ha_padre può arrivare a dtype 'object'
        # (reindex su cache .parquet senza la colonna, tutta NaN) ed evita il
        # FutureWarning di pandas sul downcasting silenzioso in quel caso.
        ha_padre_bool = ha_padre.apply(lambda v: bool(v) if pd.notna(v) else False)
        per_nome = per_nome | ha_padre_bool
    return per_nome.map({True: "Accessorio / Consolle", False: "Apparecchiatura principale"})


# --------------------------------------------------------------------------- #
# Sorgente NSIS (offline)
# --------------------------------------------------------------------------- #
def carica_nsis(path: str) -> pd.DataFrame:
    grezzo = pd.read_excel(path, sheet_name=0, header=0)
    grezzo.columns = [str(c).strip() for c in grezzo.columns]

    attese = {"DESCRAPP", "EX ASL", "CODUNITAOPERATIVA", "FABBRICANTE",
              "MODELLO", "inv", "DATACOLLAUDO"}
    mancanti = attese - set(grezzo.columns)
    if mancanti:
        raise ValueError(f"Colonne mancanti nel file NSIS: {sorted(mancanti)}")

    df = pd.DataFrame()
    df["n_inventario"] = grezzo["inv"].astype(str).str.strip()
    df["tipologia"] = grezzo["DESCRAPP"].astype(str).str.strip()
    df["fabbricante"] = grezzo["FABBRICANTE"].map(_norm_fabbricante)
    df["modello"] = grezzo["MODELLO"].astype(str).str.strip()
    df["descrizione"] = (df["tipologia"] + " " + df["modello"]).str.strip()
    df["zona"] = grezzo["EX ASL"].map(config.ZONE).fillna(
        grezzo["EX ASL"].astype(str))
    df["sede"] = grezzo["CODUNITAOPERATIVA"].astype(str).str.strip()

    dc = _parse_data_collaudo(grezzo["DATACOLLAUDO"])
    df["data_collaudo"] = dc
    df["anno_collaudo"] = dc.dt.year
    oggi = pd.Timestamp(_dt.date.today())
    df["anzianita_anni"] = ((oggi - dc).dt.days / 365.25).round(1)

    df["soglia_vetusta"] = df["tipologia"].map(_soglia)
    df["vetusto"] = df["anzianita_anni"] > df["soglia_vetusta"]
    df["stato_vetusta"] = _stato_vetusta(df["anzianita_anni"], df["soglia_vetusta"])

    note = grezzo["Note"] if "Note" in grezzo.columns else ""
    df["note"] = note
    df["modalita_acquisizione"] = (note if isinstance(note, pd.Series)
                                   else pd.Series([None] * len(df))).map(_modalita_da_note)
    df["pnrr"] = (note if isinstance(note, pd.Series)
                  else pd.Series([""] * len(df))).astype(str).str.contains("pnrr", case=False)

    # Campi non presenti nel NSIS: valorizzati quando la sorgente sarà l'API.
    df["valore_economico"] = pd.NA
    df["scadenza_contratto"] = pd.NaT
    df["scadenza_vse"] = pd.NaT
    df["scadenza_cq"] = pd.NaT
    df["tipo_record"] = "cespite"
    df["ha_padre"] = False  # nessun legame padre-figlio nel NSIS: solo unità principali

    return df.reindex(columns=COLONNE)


# --------------------------------------------------------------------------- #
# Sorgente API AT2.0
# --------------------------------------------------------------------------- #
_COLONNE_BASE = [c for c in COLONNE if not c.startswith("scadenza_")]


def mappa_cespiti_a_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Rimappa un DataFrame di cespiti già normalizzati da
    AT20ElmClient.normalize_cespite (colonne 'classe'/'unita_operativa'/...) sullo
    schema COLONNE della dashboard, calcolando anzianità/vetustà.

    Punto UNICO di mappatura campo-per-campo tra il client ELM e la dashboard: sia
    carica_api() (on-demand, con arricchimento) sia sync.py (sync in blocco, senza
    arricchimento) passano da qui, così le due strade non possono divergere. Non
    valorizza le colonne 'scadenza_*': dipendono dall'arricchimento per-cespite e
    restano a carico del chiamante.
    """
    if df.empty:
        # DataFrame vuoto (es. sync incrementale senza novità): df.get(...) su un
        # DataFrame senza colonne restituirebbe None invece di una Series, mandando
        # in crash pd.to_datetime(...).dt più sotto. Usciamo prima, schema corretto.
        return pd.DataFrame(columns=_COLONNE_BASE)

    out = pd.DataFrame()
    out["n_inventario"] = df.get("n_inventario")
    out["descrizione"] = df.get("descrizione")
    out["tipologia"] = df.get("classe")
    out["fabbricante"] = df.get("fabbricante")
    out["modello"] = df.get("modello")
    out["zona"] = df.get("zona")
    out["sede"] = df.get("unita_operativa")
    dc = pd.to_datetime(df.get("data_collaudo"), errors="coerce", utc=True).dt.tz_localize(None)
    out["data_collaudo"] = dc
    out["anno_collaudo"] = dc.dt.year
    oggi = pd.Timestamp(_dt.date.today())
    out["anzianita_anni"] = ((oggi - dc).dt.days / 365.25).round(1)
    out["soglia_vetusta"] = out["tipologia"].map(lambda t: _soglia(t or ""))
    out["vetusto"] = out["anzianita_anni"] > out["soglia_vetusta"]
    out["stato_vetusta"] = _stato_vetusta(out["anzianita_anni"], out["soglia_vetusta"])
    out["modalita_acquisizione"] = df.get("modalita_acquisizione")
    out["pnrr"] = False
    out["note"] = ""
    out["valore_economico"] = df.get("valore_economico")
    out["tipo_record"] = df.get("tipo_record", "cespite")
    out["ha_padre"] = df.get("ref_padre_id").notna() | df.get("ref_padre_numero").notna()
    return out


def carica_api(solo_grandi: bool = True, arricchisci: bool = False,
               max_records: int | None = None) -> pd.DataFrame:
    """Carica il parco dalle API ELM. Richiede at20_elm_client configurato via env.
    max_records: tetto ai cespiti scaricati (consigliato in test; il parco completo
    può contare decine di migliaia di record)."""
    import os
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
    # Filtro grandi apparecchiature ESATTO: ricava i codici classe con flag
    # grandeApparecchiatura=True da MgCA (Codifiche). Se fallisce, si ricade
    # sull'euristica per parola chiave già presente nel client.
    if solo_grandi and not cfg.grandi_classi_codici and not cfg.grandi_cnd_prefissi:
        try:
            from mgca_client import MgcaClient
            codici = MgcaClient(cfg).codici_classe_grandi_apparecchiature()
            if codici:
                cfg.grandi_classi_codici = codici
        except Exception:  # noqa: BLE001 - fallback all'euristica
            pass
    righe = client.build_parco_apparecchiature(
        solo_grandi=solo_grandi, arricchisci=arricchisci, max_records=max_records)
    df = pd.DataFrame(righe)

    out = mappa_cespiti_a_schema(df)
    out["scadenza_contratto"] = pd.to_datetime(
        df["contratto"].map(lambda c: c.get("data_fine") if isinstance(c, dict) else None)
        if "contratto" in df else pd.NaT, errors="coerce", utc=True).dt.tz_localize(None)
    out["scadenza_vse"] = pd.to_datetime(df.get("scadenza_vse"), errors="coerce", utc=True).dt.tz_localize(None)
    out["scadenza_cq"] = pd.to_datetime(df.get("scadenza_cq"), errors="coerce", utc=True).dt.tz_localize(None)
    return out.reindex(columns=COLONNE)


# --------------------------------------------------------------------------- #
# Sorgente cache su file (prodotta da sync.py)
# --------------------------------------------------------------------------- #
def carica_cache(cache_path: str = "parco.parquet") -> pd.DataFrame:
    """Legge il parco dalla cache su file generata da sync.py. Veloce (millisecondi)."""
    import os
    if not os.path.exists(cache_path):
        raise FileNotFoundError(
            f"Cache non trovata: {cache_path}. Esegui prima 'python sync.py'.")
    df = pd.read_parquet(cache_path)
    return df.reindex(columns=COLONNE)


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def carica(sorgente: str = "nsis", nsis_path: str | None = None,
           max_records: int | None = None) -> pd.DataFrame:
    if sorgente == "api":
        df = carica_api(max_records=max_records)
    elif sorgente == "cache":
        df = carica_cache()
    else:
        df = carica_nsis(nsis_path or config.NSIS_PATH_DEFAULT)

    # Ricalcolata sempre qui (non nei singoli loader): così una cache .parquet
    # generata prima dell'introduzione di 'ha_padre' (colonna assente -> NaN dopo
    # il reindex) ricade correttamente sulla sola parola chiave, senza nascondere
    # tutto per un falso "nessuna riga è accessorio".
    df["componente"] = _classifica_componente(df["tipologia"], df.get("ha_padre"))
    return df
