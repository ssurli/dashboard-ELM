"""
mgca_client.py — Client di sola lettura per il modulo MgCA (Codifiche/Anagrafica)
della piattaforma AT2.0 del Consorzio Metis.

Serve a rendere ESATTO il filtro "grandi apparecchiature" della dashboard: lo
schema Classe di MgCA espone il flag booleano `grandeApparecchiatura`, quindi si
ricavano dinamicamente i codici classe delle grandi apparecchiature, senza liste
statiche né euristiche.

Riusa l'autenticazione e il layer HTTP di at20_elm_client (stesso token OAuth su
MgCA + apikey, stesso rate limit). Cambia solo il base_url del modulo.

Uso:
    from at20_elm_client import AT20Config, AT20ElmClient
    from mgca_client import MgcaClient

    cfg = AT20Config(...)                 # come per ELM
    mgca = MgcaClient(cfg)
    codici = mgca.codici_classe_grandi_apparecchiature(azienda_id="<uuid AUSL TNO>")
    # -> set di codici classe da passare a AT20Config.grandi_classi_codici
"""
from __future__ import annotations

from typing import Any, Optional

from at20_elm_client import AT20Config, AT20ElmClient


class MgcaClient(AT20ElmClient):
    """Client MgCA. Eredita auth/paginazione/throttle da AT20ElmClient, ma punta
    al base path del modulo MgCA (di default lo ricava sostituendo /elm/ con /mgca/
    nel base_url ELM)."""

    def __init__(self, cfg: AT20Config, base_url: Optional[str] = None):
        super().__init__(cfg)
        self.mgca_base = (base_url or cfg.base_url.replace("/elm/rest", "/mgca/rest")).rstrip("/")

    # Override del solo target: le chiamate MgCA usano self.mgca_base.
    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        original = self.cfg.base_url
        try:
            self.cfg.base_url = self.mgca_base
            return super()._get(path, params)
        finally:
            self.cfg.base_url = original

    def _get_paginated(self, path: str, params: Optional[dict[str, Any]] = None,
                       max_records: Optional[int] = None):
        """Gli endpoint MgCA (es. classe/) rifiutano limit>250 — a differenza di ELM,
        che accetta pagine più grandi — quindi clampiamo qui, temporaneamente e senza
        toccare cfg.page_size condiviso con l'eventuale client ELM chiamante (stesso
        oggetto AT20Config passato a entrambi)."""
        originale = self.cfg.page_size
        try:
            self.cfg.page_size = min(self.cfg.page_size, 250)
            yield from super()._get_paginated(path, params, max_records)
        finally:
            self.cfg.page_size = originale

    # -- Codifiche ---------------------------------------------------------- #
    def get_classi(self, azienda_id: Optional[str] = None,
                   codice_azienda: Optional[str] = None) -> list[dict[str, Any]]:
        """Elenco classi CIVAB (schema Classe).

        Verificato sull'ambiente di test: il catalogo classi è condiviso a livello
        regionale (aziendaDenominazione='Regione Toscana'), NON per singola azienda —
        valorizzare 'codiceAzienda' filtra a zero risultati. Per questo, a differenza
        degli altri endpoint del client, qui NON si ricade sul default
        cfg.codice_azienda: va passato solo se esplicitamente richiesto dal chiamante."""
        return list(self._get_paginated("/api/pat/integrazione/classe/", {
            "codiceAzienda": codice_azienda,
        }))

    def get_categorie_merceologiche(self) -> list[dict[str, Any]]:
        return list(self._get_paginated("/api/pat/integrazione/categoriaMerceologica/", {}))

    def get_tipo_possesso(self) -> list[dict[str, Any]]:
        return list(self._get_paginated("/api/pat/integrazione/tipoPossesso/", {}))

    def get_stato_uso(self) -> list[dict[str, Any]]:
        return list(self._get_paginated("/api/pat/integrazione/statoUso/", {}))

    # -- Derivazione filtro grandi apparecchiature -------------------------- #
    def classi_grandi_apparecchiature(self, codice_azienda: Optional[str] = None
                                      ) -> list[dict[str, Any]]:
        """Classi con flag grandeApparecchiatura=True."""
        return [c for c in self.get_classi(codice_azienda=codice_azienda)
                if c.get("grandeApparecchiatura")]

    def codici_classe_grandi_apparecchiature(self, codice_azienda: Optional[str] = None
                                             ) -> tuple[str, ...]:
        """Codici classe (campo `codice`) delle grandi apparecchiature, pronti per
        AT20Config.grandi_classi_codici."""
        return tuple(sorted({c.get("codice") for c in
                             self.classi_grandi_apparecchiature(codice_azienda)
                             if c.get("codice")}))


if __name__ == "__main__":
    import os
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).with_name(".env"))
    except ImportError:
        pass

    cfg = AT20Config(
        base_url=os.environ.get("AT20_BASE_URL", "https://at20test.consorziometis.it/elm/rest"),
        token_url=os.environ.get("AT20_TOKEN_URL", "https://at20test.consorziometis.it/mgca/rest/v2/oauth/token"),
        codice_azienda=os.environ.get("AT20_CODICE_AZIENDA", "202"),
        api_key=os.environ.get("AT20_API_KEY"),
        username=os.environ.get("AT20_USER"),
        password=os.environ.get("AT20_PASS"),
    )
    mgca = MgcaClient(cfg)
    classi = mgca.get_classi()
    grandi = mgca.classi_grandi_apparecchiature()
    print(f"Classi totali: {len(classi)} | grandi apparecchiature: {len(grandi)}")
    print("Codici classe grandi apparecchiature:",
          mgca.codici_classe_grandi_apparecchiature())
    for c in grandi[:15]:
        print(" -", c.get("codice"), c.get("denominazione"))
