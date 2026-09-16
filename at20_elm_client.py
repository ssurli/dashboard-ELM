"""
at20_elm_client.py — Client di sola lettura per il modulo ELM (Ingegneria Clinica)
della piattaforma Area Tecnica 2.0 del Consorzio Metis.

Costruito sulla spec OpenAPI di https://at20.consorziometis.it/elm/rest (Swagger 2.0).
Pensato per alimentare la dashboard aziendale Grandi Apparecchiature.

Dipendenze:  pip install requests
Uso rapido:
    cfg = AT20Config(
        base_url="https://at20.consorziometis.it/elm/rest",
        codice_azienda="<CODICE_AUSL_TNO>",
        api_key="<APIKEY>",                 # oppure usa username/password (OAuth2)
    )
    client = AT20ElmClient(cfg)
    parco = client.build_parco_apparecchiature(solo_grandi=True)

NB: i nomi campo derivano dalla spec reale (Cespite_ELM, Contratto, Intervento_MP,
Verifica_di_Sicurezza, Controllo_Qualita). Verificare i codici CND/classe usati per
il filtro "grandi apparecchiature" sulla propria istanza.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Optional

import requests

log = logging.getLogger("at20_elm")


# --------------------------------------------------------------------------- #
# Configurazione
# --------------------------------------------------------------------------- #
@dataclass
class AT20Config:
    # Endpoint (ambiente di test Metis; per la produzione sostituire 'at20test' con 'at20')
    base_url: str = "https://at20test.consorziometis.it/elm/rest"
    codice_azienda: str = "202"        # AUSL Toscana Nord Ovest

    # Autenticazione: OAuth2 password grant. Servono ENTRAMBI su ogni chiamata:
    # access_token (Bearer) + apikey.
    api_key: Optional[str] = None      # apikey associata all'utenza (header "apikey")
    username: Optional[str] = None     # credenziali utenza di servizio
    password: Optional[str] = None
    # Il token si ottiene sul modulo MGCA (URL assoluto, NON relativo a base_url):
    token_url: str = "https://at20test.consorziometis.it/mgca/rest/v2/oauth/token"
    oauth_scope: Optional[str] = None  # non richiesto dal flusso Metis; lasciare None
    # Basic auth di client fissa "client:secret" (base64 Y2xpZW50OnNlY3JldA==):
    oauth_client_auth: tuple[str, str] = ("client", "secret")

    # Rete
    timeout: int = 30
    page_size: int = 1000             # compromesso: pagine troppo grandi rallentano il server
    max_retries: int = 3
    retry_backoff: float = 1.5
    verify_tls: bool = True
    rate_limit_per_sec: float = 2.0    # limite Metis: max 2 richieste/secondo

    # Filtro "grandi apparecchiature": adattare ai codici reali della propria istanza.
    # I codici CND/CIVAB sono recuperabili dinamicamente dalle API MGCA (sezione Codifiche);
    # in assenza di codici configurati si usa il match per parola chiave su classe/CND/descrizione.
    grandi_cnd_prefissi: tuple[str, ...] = ()          # es. ("Z11", "Z12", ...)
    grandi_classi_codici: tuple[str, ...] = ()         # es. codici CIVAB
    # NB: euristica di fallback, usata solo se MgCA non risponde o non ha il flag
    # grandeApparecchiatura popolato (verificato: nell'ambiente di test è sempre
    # None, anche sulle classi TAC/TRM/MAG/GCA/ALI — da segnalare a Metis).
    # Frasi (non sottostringhe generiche): "tomograf" da solo cattura anche
    # ECOTOMOGRAFO (ecografi, categoria diversa); "pet" da solo dà troppi falsi
    # positivi. Va allineata da chi conosce lo scope clinico esatto — vedi README.
    grandi_keyword: tuple[str, ...] = (
        "tomografo assiale computerizzato", "tomografo a risonanza magnetica",
        "risonanza magnetica", "mammografo", "angiografia digitale",
        "acceleratore lineare", "linac", "gamma camera",
        "sistema tac/pet", "sistema tac gamma camera", "medicina nucleare",
    )


# Mappa frequenza (denominazione) -> mesi, per stimare la prossima scadenza.
_FREQ_MESI = {
    "mensile": 1, "bimestrale": 2, "trimestrale": 3, "quadrimestrale": 4,
    "semestrale": 6, "annuale": 12, "biennale": 24, "triennale": 36,
    "quadriennale": 48, "quinquennale": 60,
}


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class AT20ElmClient:
    def __init__(self, cfg: AT20Config):
        self.cfg = cfg
        self._session = requests.Session()
        self._session.verify = cfg.verify_tls
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._last_request_ts: float = 0.0

    # -- Autenticazione ----------------------------------------------------- #
    def _auth_headers(self) -> dict[str, str]:
        """Ogni chiamata richiede Bearer token + apikey (entrambi)."""
        if not self.cfg.api_key:
            raise RuntimeError("apikey mancante: impostare AT20Config.api_key.")
        return {
            "Authorization": f"Bearer {self._get_oauth_token()}",
            "apikey": self.cfg.api_key,
        }

    def _get_oauth_token(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        if not (self.cfg.username and self.cfg.password):
            raise RuntimeError("Credenziali mancanti: impostare username e password.")
        data = {
            "grant_type": "password",
            "username": self.cfg.username,
            "password": self.cfg.password,
        }
        if self.cfg.oauth_scope:
            data["scope"] = self.cfg.oauth_scope
        self._throttle()
        resp = self._session.post(
            self.cfg.token_url, data=data,
            auth=self.cfg.oauth_client_auth, timeout=self.cfg.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_exp = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    def _throttle(self) -> None:
        """Rispetta il rate limit lato client (default 2 richieste/secondo)."""
        if self.cfg.rate_limit_per_sec <= 0:
            return
        min_interval = 1.0 / self.cfg.rate_limit_per_sec
        elapsed = time.time() - self._last_request_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_ts = time.time()

    # -- HTTP di base ------------------------------------------------------- #
    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = self.cfg.base_url.rstrip("/") + path
        params = {k: v for k, v in (params or {}).items() if v is not None}
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                self._throttle()
                resp = self._session.get(
                    url, params=params, headers=self._auth_headers(), timeout=self.cfg.timeout
                )
                if resp.status_code == 401:
                    # token probabilmente scaduto: forza refresh e riprova una volta
                    self._token = None
                    self._throttle()
                    resp = self._session.get(
                        url, params=params, headers=self._auth_headers(), timeout=self.cfg.timeout
                    )
                if resp.status_code == 404:
                    # Questa API usa 404 per "nessun risultato": non è un errore.
                    log.debug("GET %s -> 404 (nessun risultato)", path)
                    return None
                if not resp.ok:
                    body = (resp.text or "")[:1000]
                    log.warning("GET %s -> %s %s | corpo risposta: %s",
                                path, resp.status_code, resp.reason, body)
                resp.raise_for_status()
                if not resp.content:
                    return None
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                wait = self.cfg.retry_backoff ** attempt
                log.warning("GET %s tentativo %d/%d fallito: %s (retry in %.1fs)",
                            path, attempt, self.cfg.max_retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"GET {path} fallito dopo {self.cfg.max_retries} tentativi") from last_exc

    def _get_paginated(self, path: str, params: Optional[dict[str, Any]] = None,
                       max_records: Optional[int] = None) -> Iterator[dict[str, Any]]:
        """Scorre tutte le pagine usando offset/limit finché una pagina è incompleta.
        Se max_records è valorizzato, si ferma dopo aver restituito quel numero di
        record (utile in test per non scaricare l'intero parco)."""
        params = dict(params or {})
        offset = 0
        limit = self.cfg.page_size
        restituiti = 0
        while True:
            if max_records is not None:
                limit = min(self.cfg.page_size, max_records - restituiti)
                if limit <= 0:
                    return
            page = self._get(path, {**params, "offset": offset, "limit": limit})
            if not page:
                return
            if isinstance(page, dict):   # endpoint che restituisce un singolo oggetto
                yield page
                return
            for item in page:
                yield item
                restituiti += 1
                if max_records is not None and restituiti >= max_records:
                    return
            if len(page) < limit:
                return
            offset += limit

    # -- Endpoint: inventario ----------------------------------------------- #
    def get_cespiti(self, data_da: Optional[str] = None,
                    max_records: Optional[int] = None) -> list[dict[str, Any]]:
        """Elenco cespiti elettromedicali (schema Cespite_ELM)."""
        return list(self._get_paginated("/api/med/integrazione/cespite/",
                                        {"dataDa": data_da}, max_records=max_records))

    def get_sistemi(self, data_da: Optional[str] = None,
                    max_records: Optional[int] = None) -> list[dict[str, Any]]:
        """Elenco sistemi di cespiti (schema Sistema_ELM) — es. sistemi TAC/PET integrati."""
        return list(self._get_paginated("/api/med/integrazione/sistema/",
                                        {"dataDa": data_da}, max_records=max_records))

    def get_cespiti_di_sistema(self, id_sistema: str) -> list[dict[str, Any]]:
        """Cespiti che compongono un sistema (schema Cespite_Sistema)."""
        return list(self._get_paginated("/api/med/integrazione/sistema/listaCespiti/",
                                        {"idSistema": id_sistema}))

    def cerca_cespiti(self, *, uo_id=None, cdc_id=None, cm_id=None,
                      anag_level=None, anag_id=None, descrizione=None,
                      escludi_alienati=True) -> list[dict[str, Any]]:
        """Ricerca WebReparti con filtri di ubicazione.
        NB: il gruppo 'webreparti' può essere NON abilitato per l'utenza di servizio
        (403). Per l'elenco completo usare invece get_cespiti()."""
        return list(self._get_paginated("/api/med/webreparti/ricerca/cespite_elm/", {
            "uoId": uo_id, "cdcId": cdc_id, "cmId": cm_id,
            "anagLevel": anag_level, "anagId": anag_id,
            "descrizione": descrizione, "escludiAlienati": escludi_alienati,
            "authFilters": False,
        }))

    def get_documenti(self, id_cespite: str) -> list[dict[str, Any]]:
        return self._get("/api/med/integrazione/documenti/", {"idCespite": id_cespite}) or []

    # -- Endpoint: contratti (integrazione) --------------------------------- #
    def get_contratti(self, id_cespite: Optional[str] = None,
                      n_inventario: Optional[str] = None) -> list[dict[str, Any]]:
        return list(self._get_paginated("/api/med/integrazione/contratto/", {
            "idCespite": id_cespite, "numeroInventario": n_inventario,
        }))

    def get_contratto_corrente(self, id_cespite=None, n_inventario=None) -> Optional[dict[str, Any]]:
        """Contratto 'in essere' per il cespite. Deriva dai contratti (integrazione),
        scegliendo quello con stato tecnico IN_CORSO se presente, altrimenti il primo."""
        contratti = self.get_contratti(id_cespite=id_cespite, n_inventario=n_inventario)
        if not contratti:
            return None
        in_corso = [k for k in contratti if k.get("statoContrattoTecnico") == "IN_CORSO"]
        return (in_corso or contratti)[0]

    def get_storico_contratti(self, id_cespite=None, n_inventario=None) -> list[dict[str, Any]]:
        return self.get_contratti(id_cespite=id_cespite, n_inventario=n_inventario)

    # -- Endpoint: collaudo, manutenzioni, verifiche (integrazione) --------- #
    def get_collaudo_concluso(self, id_cespite=None, n_inventario=None) -> Optional[dict[str, Any]]:
        collaudi = self._get("/api/med/integrazione/col/collaudo/", {
            "idCespite": id_cespite, "numeroInventario": n_inventario,
        }) or []
        return collaudi[0] if collaudi else None

    def get_manutenzioni_preventive(self, id_cespite=None, data_da=None, data_a=None):
        return list(self._get_paginated("/api/med/integrazione/mp/intervento/", {
            "idCespite": id_cespite, "dataDa": data_da, "dataA": data_a,
        }))

    def get_manutenzioni_correttive(self, id_cespite=None, data_da=None, data_a=None):
        return list(self._get_paginated("/api/med/integrazione/mc/intervento/", {
            "idCespite": id_cespite, "dataDa": data_da, "dataA": data_a,
        }))

    def get_controlli_qualita(self, id_cespite=None, data_da=None, data_a=None):
        return list(self._get_paginated("/api/med/integrazione/cq/intervento/", {
            "idCespite": id_cespite, "dataDa": data_da, "dataA": data_a,
        }))

    def get_verifiche_sicurezza(self, id_cespite=None, data_da=None, data_a=None):
        return list(self._get_paginated("/api/med/integrazione/vs/intervento/", {
            "idCespite": id_cespite, "dataDa": data_da, "dataA": data_a,
        }))

    # -- Normalizzazione ---------------------------------------------------- #
    @staticmethod
    def normalize_cespite(c: dict[str, Any]) -> dict[str, Any]:
        """Cespite_ELM (raw) -> riga dashboard."""
        return {
            "id": c.get("id"),
            "n_inventario": c.get("numero"),
            "descrizione": c.get("descrizione") or c.get("denominazione"),
            "classe": c.get("classeDenominazione"),
            "cnd": c.get("cndDenominazione"),
            "fabbricante": c.get("dittaDenominazione"),
            "modello": c.get("modelloDenominazione"),
            "matricola": c.get("matricola"),
            "valore_economico": c.get("costoInEuro"),
            "modalita_acquisizione": c.get("acqTipoPossessoDenominazione"),
            "proprieta": c.get("acqProprietaDenominazione"),
            "stato_uso": c.get("acqStatoUsoDenominazione"),
            "data_inventario": c.get("dataInventario"),
            "data_inizio_utilizzo": c.get("dataInizioUtilizzo"),
            "data_collaudo": c.get("skTecnicaDataEsitoCollaudo"),
            "data_fine_supporto": c.get("skTecnicaDataFineSupporto"),
            "data_scad_garanzia": c.get("dataScadGaranzia"),
            "data_dismissione": c.get("dataDismissione"),
            "fuori_uso": c.get("fuoriUso"),
            "in_manutenzione": c.get("inManutenzione"),
            "dismissione_temporanea": c.get("dismissioneTemporanea"),
            "critico": c.get("critico"),
            "vitale": c.get("vitale"),
            # Legame padre-figlio (es. la consolle di comando è un cespite a sé con
            # refPadreId/refPadreNumero valorizzati verso il TAC/RM padre): criterio
            # robusto per distinguere accessori dall'unità principale, più affidabile
            # del solo nome-classe (verificato: popolato solo su una parte dei cespiti
            # nell'ambiente di test, va quindi usato con fallback per parola chiave —
            # vedi data_source._classifica_componente).
            "ref_padre_id": c.get("refPadreId"),
            "ref_padre_numero": c.get("refPadreNumero"),
            "e_padre": c.get("padre"),
            # ubicazione
            "zona": c.get("zonaDenominazione"),          # zona ex-ASL
            "presidio": c.get("presidioDenominazione"),
            "edificio": c.get("edificioDenominazione"),
            "piano": c.get("piano"),
            "stanza": c.get("stanza"),
            "unita_operativa": c.get("uoDenominazione"),
            "dipartimento": c.get("dipartimentoDenominazione"),
            "reparto": c.get("repartoDenominazione"),
            "centro_costo": c.get("ccDenominazione"),
            "global_service": c.get("globalServiceNome"),
        }

    @staticmethod
    def normalize_sistema(s: dict[str, Any]) -> dict[str, Any]:
        """Sistema_ELM (raw) -> riga dashboard. Stesso schema di normalize_cespite,
        con i campi non previsti per i sistemi lasciati a None e tipo_record='sistema'."""
        return {
            "id": s.get("id"),
            "n_inventario": s.get("numero"),
            "descrizione": s.get("descrizione") or s.get("denominazione"),
            "classe": s.get("classeDenominazione"),
            "cnd": None,
            "fabbricante": s.get("dittaDenominazione"),
            "modello": s.get("modelloDenominazione"),
            "matricola": s.get("matricola"),
            "valore_economico": s.get("costoInEuro"),
            "modalita_acquisizione": None,     # i sistemi non espongono acqTipoPossesso
            "proprieta": None,
            "stato_uso": None,
            "data_inventario": s.get("dataInventario"),
            "data_inizio_utilizzo": None,
            "data_collaudo": None,
            "data_fine_supporto": None,
            "data_scad_garanzia": None,
            "data_dismissione": None,
            "fuori_uso": None,
            "in_manutenzione": None,
            "dismissione_temporanea": None,
            "critico": None,
            "vitale": None,
            "ref_padre_id": None,      # i sistemi non espongono il legame padre-figlio
            "ref_padre_numero": None,
            "e_padre": None,
            "zona": s.get("zonaDenominazione"),
            "presidio": s.get("presidioDenominazione"),
            "edificio": s.get("edificioDenominazione"),
            "piano": s.get("piano"),
            "stanza": s.get("stanza"),
            "unita_operativa": s.get("uoDenominazione"),
            "dipartimento": s.get("dipartimentoDenominazione"),
            "reparto": s.get("repartoDenominazione"),
            "centro_costo": s.get("ccDenominazione"),
            "global_service": s.get("globalServiceNome"),
            "tipo_record": "sistema",
        }

    @staticmethod
    def normalize_contratto(k: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": k.get("id"),
            "denominazione": k.get("denContratto") or k.get("oggetto"),
            "cig": k.get("cig"),
            "tipo": k.get("tipoContrattoDenominazione"),
            "fatturazione": k.get("tipoFatturazioneDenominazione"),
            "data_inizio": k.get("dataInizio"),
            "data_fine": k.get("dataFine"),
            "costo": k.get("costo"),
            "costo_totale": k.get("costoTotale"),
            "stato": k.get("statoContratto"),
            "stato_tecnico": k.get("statoContrattoTecnico"),   # es. SCADUTO
            "fornitore": k.get("dittaFornitriceNome") or k.get("dittaDenominazione"),
        }

    @classmethod
    def _prossima_scadenza(cls, interventi: Iterable[dict[str, Any]]) -> Optional[str]:
        """Stima la prossima scadenza da (dataEse + frequenza) sugli interventi completati.

        Prende, per il cespite, l'ultima esecuzione con frequenza nota e ci somma la
        frequenza. Restituisce la data (ISO) più imminente tra quelle calcolate.
        """
        migliore: Optional[datetime] = None
        for it in interventi:
            base = it.get("dataEse") or it.get("dataPre")
            freq = (it.get("frequenzaDenominazione") or "").strip().lower()
            mesi = _FREQ_MESI.get(freq)
            if not base or not mesi:
                continue
            try:
                due = _add_months(_parse_dt(base), mesi)
            except ValueError:
                continue
            if migliore is None or due < migliore:
                migliore = due
        return migliore.date().isoformat() if migliore else None

    # -- Orchestrazione ----------------------------------------------------- #
    def _e_grande_apparecchiatura(self, c: dict[str, Any]) -> bool:
        cnd = (c.get("cndCodice") or "")
        classe = (c.get("classeCodice") or "")
        if self.cfg.grandi_cnd_prefissi and cnd.startswith(self.cfg.grandi_cnd_prefissi):
            return True
        if self.cfg.grandi_classi_codici and classe in self.cfg.grandi_classi_codici:
            return True
        if self.cfg.grandi_cnd_prefissi or self.cfg.grandi_classi_codici:
            return False  # se sono configurati codici, non usare il fallback keyword
        # Solo sulla classe standardizzata (non su descrizione/denominazione del
        # singolo cespite, testo libero e rumoroso: es. potrebbe nominare a caso
        # un'altra apparecchiatura nelle note).
        testo = " ".join(str(c.get(k) or "") for k in
                         ("classeDenominazione", "cndDenominazione")).lower()
        return any(kw in testo for kw in self.cfg.grandi_keyword)

    def build_parco_apparecchiature(self, solo_grandi: bool = True,
                                    arricchisci: bool = True,
                                    includi_sistemi: bool = True,
                                    max_records: Optional[int] = None,
                                    data_da: Optional[str] = None) -> list[dict[str, Any]]:
        """
        Restituisce l'elenco normalizzato delle apparecchiature, opzionalmente arricchito
        con contratto corrente e prossime scadenze VS/MP/CQ per cespite.
        Se includi_sistemi=True aggiunge anche i sistemi (es. TAC/PET integrati).
        max_records limita il numero di cespiti scaricati (utile in test: il parco
        completo può contare decine di migliaia di record).
        data_da limita a cespiti/sistemi modificati dopo questa data (sync incrementale).
        NB: arricchisci=True fa una chiamata per cespite: usare cache/limit in produzione.

        Punto UNICO in cui si applica il filtro "grandi apparecchiature": sia
        data_source.carica_api() sia sync.py passano da qui, così il filtro (esatto
        via MgCA, o euristico per parola chiave in fallback — vedi _e_grande_apparecchiatura)
        non può disallinearsi tra le due strade.
        """
        cespiti = self.get_cespiti(data_da=data_da, max_records=max_records)
        if solo_grandi:
            cespiti = [c for c in cespiti if self._e_grande_apparecchiatura(c)]

        righe: list[dict[str, Any]] = []
        for c in cespiti:
            riga = self.normalize_cespite(c)
            riga["tipo_record"] = "cespite"
            if arricchisci and riga["id"]:
                cid = riga["id"]
                try:
                    contratto = self.get_contratto_corrente(id_cespite=cid)
                    if contratto:
                        riga["contratto"] = self.normalize_contratto(contratto)
                except Exception as exc:            # non bloccare l'intero parco
                    log.debug("contratto ko per %s: %s", cid, exc)
                try:
                    riga["scadenza_vse"] = self._prossima_scadenza(
                        self.get_verifiche_sicurezza(id_cespite=cid))
                    riga["scadenza_mp"] = self._prossima_scadenza(
                        self.get_manutenzioni_preventive(id_cespite=cid))
                    riga["scadenza_cq"] = self._prossima_scadenza(
                        self.get_controlli_qualita(id_cespite=cid))
                except Exception as exc:
                    log.debug("scadenze ko per %s: %s", cid, exc)
            righe.append(riga)

        if includi_sistemi:
            # I sistemi sono aggregati di più cespiti (es. TAC/PET integrati), ma NON
            # sono per natura tutti "grandi apparecchiature": nei dati reali esistono
            # anche sistemi banali (monitor+PC+autoclave assemblati). Verificato:
            # senza questo filtro entravano MONITOR, PERSONAL COMPUTER, AUTOCLAVE...
            # Stesso filtro (esatto via MgCA, o euristico) usato per i cespiti.
            sistemi = self.get_sistemi(data_da=data_da)
            if solo_grandi:
                sistemi = [s for s in sistemi if self._e_grande_apparecchiatura(s)]
            for s in sistemi:
                righe.append(self.normalize_sistema(s))

        return righe


# --------------------------------------------------------------------------- #
# Utility
# --------------------------------------------------------------------------- #
def _add_months(d: datetime, months: int) -> datetime:
    """Somma 'months' mesi a una data, senza dipendenze esterne."""
    month0 = d.month - 1 + months
    year = d.year + month0 // 12
    month = month0 % 12 + 1
    # ultimo giorno valido del mese target (gestisce 31->30/28)
    days_in_month = [31, 29 if _bisestile(year) else 28, 31, 30, 31, 30,
                     31, 31, 30, 31, 30, 31][month - 1]
    return d.replace(year=year, month=month, day=min(d.day, days_in_month))


def _bisestile(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _parse_dt(value: str) -> datetime:
    """Parsa le date della spec (ISO 8601, con o senza millisecondi/offset)."""
    v = value.strip().replace("Z", "+00:00")
    for fmt in (None,):  # prova fromisoformat, poi formati noti
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            break
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Data non riconosciuta: {value!r}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os
    import sys
    from pathlib import Path

    # Carica un file .env dalla stessa cartella dello script (a prescindere dalla
    # directory da cui si lancia il comando). Richiede python-dotenv.
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).with_name(".env"))
    except ImportError:
        print("Suggerimento: 'pip install python-dotenv' per leggere il file .env.")

    # Credenziali e parametri via variabili d'ambiente (mai in chiaro nel codice).
    # Ambiente di test Metis di default; per la produzione esportare AT20_BASE_URL e
    # AT20_TOKEN_URL con l'host 'at20' (senza 'test').
    cfg = AT20Config(
        base_url=os.environ.get("AT20_BASE_URL", "https://at20test.consorziometis.it/elm/rest"),
        token_url=os.environ.get("AT20_TOKEN_URL", "https://at20test.consorziometis.it/mgca/rest/v2/oauth/token"),
        codice_azienda=os.environ.get("AT20_CODICE_AZIENDA", "202"),
        api_key=os.environ.get("AT20_API_KEY") or None,
        username=os.environ.get("AT20_USER") or None,
        password=os.environ.get("AT20_PASS") or None,
    )

    mancanti = [n for n, v in (("AT20_API_KEY", cfg.api_key),
                               ("AT20_USER", cfg.username),
                               ("AT20_PASS", cfg.password)) if not v]
    if mancanti:
        print("Credenziali mancanti:", ", ".join(mancanti))
        print("Crea un file .env in questa cartella (vedi README) oppure imposta le "
              "variabili d'ambiente prima di lanciare lo script.")
        sys.exit(1)

    client = AT20ElmClient(cfg)
    parco = client.build_parco_apparecchiature(solo_grandi=True, arricchisci=False)
    print(f"Apparecchiature trovate: {len(parco)}")
    for r in parco[:5]:
        print(r["n_inventario"], "-", r["descrizione"], "-", r["zona"], "-", r["valore_economico"])


