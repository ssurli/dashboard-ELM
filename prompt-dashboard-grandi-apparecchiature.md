# Prompt per Claude Code — Dashboard aziendale Grandi Apparecchiature (NSIS)

> Copia tutto ciò che segue e incollalo in Claude Code, **dopo aver aperto la cartella
> del progetto** (`Dashboard ELM`), che contiene già uno scaffold funzionante da estendere.

---

## Stato attuale — punto di partenza (IMPORTANTE: NON ripartire da zero)

Nella cartella esiste già uno **scaffold Streamlit funzionante e testato**. Il tuo compito è
**estenderlo e rifinirlo**, non riscriverlo. File presenti:

- `app.py` — dashboard Streamlit: KPI, filtri in sidebar (zona, tipologia, fabbricante,
  modalità, solo-vetuste), tab Panoramica (4 grafici Plotly), Elenco con drill-down per sede,
  tab Vetustà & scadenze, tab Export (Excel della selezione). Funziona già sul NSIS.
- `data_source.py` — layer sorgente con schema di uscita unico (`COLONNE`): `carica_nsis()`
  (loader + normalizzazione: mappa `EX ASL`→zona, normalizza fabbricante, calcola
  anzianità/vetustà, deduce `modalita_acquisizione` dalle Note) e `carica_api()` (già pronto,
  riusa `at20_elm_client.py`). Il dispatcher `carica(sorgente)` commuta NSIS/API.
- `config.py` — mapping zone ex-ASL, soglie di vetustà per tipologia, alias fabbricante, finestra alert.
- `at20_elm_client.py` — client di sola lettura per le API AT2.0/ELM (auth OAuth2+apikey,
  paginazione, rate limit 2 req/s, normalizzazione `Cespite_ELM`/`Sistema_ELM`→schema dashboard).
- `NSIS__2_.xls` — estrazione NSIS (sorgente offline attuale).
- `requirements.txt`, `README.md`, `diag.py` (diagnostica API).

**Prima di scrivere codice**: leggi questi file e riassumimi in 3-4 righe come sono strutturati
e cosa intendi estendere. Mantieni lo schema `COLONNE` di `data_source.py` come contratto tra
dati e UI: qualunque nuova sorgente/campo passa da lì.

## Vincolo operativo attuale

L'ambiente **API AT2.0 di test è al momento non utilizzabile**: tutti gli endpoint
`/api/med/integrazione/...` restituiscono **HTTP 500** (errore lato server Metis, ticket aperto);
gli endpoint `/api/med/webreparti/...` restituiscono **403** per l'utenza di servizio. Il token
OAuth invece si ottiene correttamente. **Finché Metis non risolve, sviluppa e collauda tutto in
modalità NSIS (offline).** La commutazione su API dovrà avvenire senza modifiche alla UI (già
predisposta in `data_source.carica_api`).

---

## Contesto

Sono il Direttore della UOC Tecnologie del Dipartimento Tecnico e Patrimonio dell'Azienda USL Toscana Nord Ovest. Voglio una **dashboard aziendale in Streamlit** che censisca **tutte le sedi/strutture aziendali** e le loro **grandi apparecchiature** (TAC, RM, mammografi, angiografi, acceleratori lineari, gamma camere, sistemi TAC/PET), con caratteristiche principali, valore economico, stato contrattuale e scadenze.

**Riusa lo stile, l'architettura e i componenti della dashboard Streamlit che ho già sviluppato per il fabbisogno delle Case di Comunità (PNRR)**: prima di scrivere codice, ispeziona quel repo/quei file (percorso: `<<PERCORSO_REPO_DASHBOARD_PNRR>>`) e riprendi lo stesso layout, la stessa palette, gli stessi pattern di caricamento dati, cache, filtri, drill-down cliccabile struttura→apparecchiature ed eventuale componente mappa. La nuova dashboard deve sembrare parte della stessa suite.

## Sorgenti dati

I dati risiedono nella piattaforma **Area Tecnica 2.0 (AT2.0) del Consorzio Metis** (consorzio in-house della Regione Toscana per le aziende sanitarie; motore sottostante CMDBuild/PostgreSQL). L'interfaccia da usare **non** è la REST nativa di CMDBuild, ma le **REST API di AT2.0**, documentate in Swagger/OpenAPI. Il file NSIS allegato è solo un'**estrazione parziale**. Prevedi **due modalità di alimentazione**, selezionabili da config.

### 1) AT2.0 REST API (sorgente primaria)
- Base URL: `https://at20.consorziometis.it`. Indice documentazione: `/api-docs`. Sono esposti tre servizi con Swagger UI:
  - **ELM** → `/elm/rest/swagger-ui.html` · spec JSON: `/elm/rest/swagger-api` — **MODULO PRINCIPALE** (Ingegneria Clinica, elettromedicali)
  - **MgCA** → `/mgca/rest/swagger-ui.html` · spec JSON: `/mgca/rest/swagger-api`
  - **DAE** → `/dae/rest/swagger-ui.html` · spec JSON: `/dae/rest/swagger-api`
- **ELM è il modulo chiave** (base path `/elm/rest`; tag: `Inventario_Elm`, `Collaudo`, `Controllo_Qualita'`, `Manutenzione_Preventiva`, `Manutenzione_Correttiva`, `Verifica_Sicurezza`, `WebReparti_Elm`). Endpoint principali (GET, JSON; paginati con `offset`/`limit`, totali con `count=true`, sync incrementale con `dataDa`; molti filtrano per `codiceAzienda` e `cdcId`):
  - `GET /api/med/integrazione/cespite/` → **elenco apparecchiature** (cespiti elettromedicali; filtri `nInventario`, `idCespite`). Schema `Cespite_ELM`. Anagrafica RM/TAC ecc.
  - `GET /api/med/integrazione/contratto/` → **contratti** (noleggio/locazione), filtrabili per `idCespite`/`numeroInventario`, `dataDa`/`dataA`. Schema `Contratto` → stato contrattuale e **scadenze**.
  - `GET /api/med/integrazione/contratto/listaCespiti/?idContratto=` → cespiti per contratto. Schema `Contratto_Cespite_Anno` → **dato economico per anno** (canone/valore).
  - `GET /api/med/integrazione/col/collaudo/?idCespite=` → **collaudi** → data collaudo (anzianità/vetustà; equivale a `DATACOLLAUDO` del NSIS).
  - `GET /api/med/integrazione/mp/intervento/` e `/mc/intervento/` → **manutenzioni** preventive/correttive per cespite; `mp` ha `frequenza` → **prossima scadenza programmata**.
  - `GET /api/med/integrazione/cq/intervento/` → **controlli qualità** (frequenza/esito) → scadenze CQ.
  - tag `Verifica_Sicurezza` → **verifiche di sicurezza elettrica (VSE)** → scadenze VSE (leggi endpoint/schema dalla spec completa).
  - tag `WebReparti_Elm` → **reparti/ubicazioni** per la vista per sede/UO.
- **Autenticazione ELM**: ogni endpoint richiede `apiKey` (header, scope `rest-api`) **oppure** `OAuth2` (bearer, scope `rest-api`). Servono credenziali di un **utente di servizio in sola lettura** e il `codiceAzienda` di AUSL TNO (in file di config/secret, mai nel codice).
- **Nomi campo esatti**: leggi la sezione `definitions` della spec (`Cespite_ELM`, `Contratto`, `Contratto_Cespite_Anno`, `Collaudo`, `Intervento_MP`/`_MC`, schema VSE, reparti) per mappare i singoli attributi (valore, ubicazione, ditta, modello, matricola, date…).
- (MgCA — gruppi `Inventario`, `Anagrafica`, `Codifica`, `Identity_Manager`, `PUBLIC_MgCa`, più `ATView`/`AIRQino` non pertinenti — e DAE restano **secondari** per questo cruscotto.)
- **Mappatura campi confermata dalla spec** (`Cespite_ELM`): `numero`=n. inventario · `descrizione`/`denominazione` · `classeDenominazione`/`cndDenominazione`=tipologia/classe (usare per filtrare le grandi apparecchiature) · `dittaDenominazione`=fabbricante · `modelloDenominazione` · `matricola` · **`costoInEuro`=valore economico** · **`acqTipoPossessoDenominazione`=modalità (Proprietà/Noleggio/Locazione/Service)** · `acqStatoUsoDenominazione` · `dataInventario`/`dataInizioUtilizzo`/`skTecnicaDataEsitoCollaudo`=anzianità · `dataScadGaranzia` · `dataDismissione`/`fuoriUso`/`inManutenzione`=stato · ubicazione: `zonaDenominazione` (zona ex-ASL), `presidioDenominazione`, `edificioDenominazione`, `piano`, `stanza`, `uoDenominazione`, `dipartimentoDenominazione`, `repartoDenominazione` · `ccDenominazione`=centro di costo · `critico`/`vitale`.
- **Contratti** (`Contratto`): `dataInizio`/`dataFine`=periodo e **scadenza**; `costo`/`costoTotale`=importo/canone; `tipoContrattoDenominazione`; `statoContratto` (AGGIUDICATO/IN_CORSO/CONCLUSO) e `statoContrattoTecnico` (IN_CORSO/SOSPESO/**SCADUTO**/ATTESA_*) per gli alert; `cig`, `denContratto`.
- **Scadenze programmate** (`Intervento_MP`, `Verifica_di_Sicurezza`, `Controllo_Qualita`): `dataPre` (prevista), `dataEse` (eseguita), `frequenzaDenominazione`, `esitoDenominazione`, `completata` → prossima scadenza ≈ `dataEse` + frequenza.
- **Autenticazione (confermata da Metis, ambiente di test)**: OAuth2 *password grant* con token su **MGCA** (`POST https://at20test.consorziometis.it/mgca/rest/v2/oauth/token`), header `Authorization: Basic Y2xpZW50OnNlY3JldA==` (fisso, "client:secret") e body `x-www-form-urlencoded` (`grant_type=password` + username/password). Su **ogni** chiamata successiva servono **insieme** `Authorization: Bearer <access_token>` **e** l'header `apikey`. `codiceAzienda`=**202** (AUSL TNO). Rate limit **2 req/s** (già gestito nel client). Solo gli endpoint `/api/med/integrazione/...` sono abilitati per l'utenza di servizio (i `/webreparti/...` danno 403). Produzione: sostituire `at20test`→`at20`. Credenziali solo in `.env`/secret, mai nel codice.
- **Endpoint comodi per la sola lettura** (tag `WebReparti_Elm`): `…/ricerca/cespite_elm/` (ricerca con filtri `uoId`/`cdcId`/`anagLevel`=azienda|zona|presidio|edificio, `disponibilita`, `escludiAlienati`); `…/ricerca/cespite_elm/report/` (**export XLS** dei cespiti filtrati); `…/ricerca/contratto/` e `…/storico/contratto/`; `…/ricerca/collaudo/`; `…/vs/`, `…/cq/`, `…/mp/intervento/` (informazioni complete, filtrabili per `idCespite`, `dataDa`/`dataA`).
- **Connettore pronto**: parti da `at20_elm_client.py` (allegato) — client con auth apikey/OAuth2, paginazione offset/limit, normalizzazione `Cespite_ELM`→schema dashboard e stima scadenze; estendilo secondo necessità. Verifica sull'istanza i codici CND/classe per il filtro "grandi apparecchiature" e l'URL esatto del token OAuth2.
- **Primo passo obbligatorio**: scarica la spec **OpenAPI JSON** di ciascun servizio (tipicamente `/{modulo}/rest/v2/api-docs` o `/{modulo}/rest/v3/api-docs`; ricava l'URL esatto dalla config dello Swagger UI) e **genera da lì la mappa degli endpoint e un client tipizzato**. Non dedurre gli endpoint a memoria: leggi la spec reale.
- **Identifica quale servizio espone cosa** e mostrami la mappatura prima di consolidarla: elenco **apparecchiature elettromedicali** (RM, TAC, ecc.), **ubicazioni/sedi**, **contratti** (noleggio/locazione/service), **anagrafica economica** (valore, canone), **attività di manutenzione e verifiche periodiche** con relative **scadenze**. (Ambito funzionale AT2.0: Ingegneria Clinica = manutenzione beni elettromedicali; Patrimonio beni mobili/immobili; Area Tecnica impianti; Sistemi Informativi.)
- **Credenziali e autenticazione** in un file di config/secret separato (mai in chiaro nel codice); gestisci token/sessione secondo quanto indicato dalla spec. Usa un **utente di servizio in sola lettura**.
- Layer dati resiliente: timeout, retry, **paginazione**, cache (`@st.cache_data` con TTL) e degradazione a "dato non disponibile" quando un campo o un endpoint manca.
- (Fallback tecnico, opzionale e **disattivato di default**: lettura **read-only diretta dal PostgreSQL** del backend CMDBuild, solo `SELECT`.)

### 2) Estrazione Excel NSIS (sorgente attuale / offline)
File Excel di censimento NSIS: **`NSIS__2_.xls`** (già nella cartella; loader già implementato in `data_source.carica_nsis`).
Formato `.xls` legacy (OLE2) — il loader legge sia `.xls` (xlrd) sia `.xlsx` (openpyxl). Foglio: primo foglio, header in prima riga, ~79 righe. Schema reale rilevato:

| Colonna | Significato | Note |
|---|---|---|
| `DESCRAPP` | Tipologia apparecchiatura | Valori: TAC, RISONANZA, MAMMOGRAFI, ANGIOGRAFI, ACCELERATORI LINEARI, GAMMA CAMERE COMPUTERIZZATE, SISTEMI TAC/PET |
| `EX ASL` | Codice zona ex-ASL (intero) | Mapping: 1=Massa-Carrara, 2=Lucca, 5=Pisa, 6=Livorno, 12=Versilia (rendilo configurabile) |
| `CODUNITAOPERATIVA` | Sede / Unità Operativa | es. "Radiologia Versilia", "Medicina Nucleare Lucca" |
| `FABBRICANTE` | Produttore | Normalizza i duplicati per case/spelling (es. "Philips"/"PHIlIPS", "PHILIPS") |
| `MODELLO` | Modello | |
| `inv` | N. inventario | può essere numerico o alfanumerico (es. "S006088") → tienilo stringa |
| `DATACOLLAUDO` | Data di collaudo | usala per calcolare **anzianità** e **vetustà** |
| `Note` | Testo libero su stato/contratto | contiene indizi: "locazione N anni", "noleggio pluriennale", "PNRR", "riscattata nel 2026", ecc. |

## Valore economico, contratti e scadenze

Voglio in dashboard anche **valore economico**, **scadenze contratti** (noleggio/locazione) e **scadenze verifiche/manutenzioni**. Questi campi **non sono nell'estrazione NSIS**, ma la piattaforma AT2.0 (ambito Ingegneria Clinica) **tipicamente li gestisce già** (anagrafica economica, contratti, scadenzario manutenzioni/verifiche): in modalità **AT2.0 live cercali e mappali dagli endpoint corrispondenti**, senza richiederli a mano.

Solo quando lavori sul **solo Excel NSIS (offline)**, questi campi restano **non disponibili** e vanno gestiti così (lo scaffold lo fa già):

1. `modalita_acquisizione` viene dedotta con parsing euristico della colonna `Note` ("locazione"→Locazione, "noleggio"→Noleggio, "riscattata"→Proprietà); un flag `pnrr` viene alzato se la nota contiene "PNRR".
2. `valore_economico`, scadenze contratti e scadenze verifiche/manutenzioni **non ci sono nel NSIS**: mostrali come "n.d." e fai in modo che KPI e sezioni scadenze non si rompano (già gestito). **Non** costruire un template Excel di arricchimento manuale: quei dati arriveranno dall'API AT2.0.
3. La dashboard deve funzionare col solo NSIS senza errori.

## Funzionalità richieste

**Data layer**
- Loader unico che: legge NSIS, normalizza tipi (date, stringhe), normalizza `FABBRICANTE`, mappa `EX ASL`→nome zona, deduplica, fa join con l'arricchimento. `@st.cache_data`.
- Config centralizzata (`config.py` o `.toml`): mapping zone, soglie di vetustà per tipologia (default configurabili, es. TAC/RM 8 anni, mammografi 10, acceleratori 10, gamma camere 10), finestra di alert scadenze in mesi (default 12), percorsi file.

**Vista d'insieme (home)**
- Riga di KPI: n° totale apparecchiature, n° per tipologia, n° sedi/UO, n° zone; valore economico totale (se disponibile); età media del parco; n° apparecchiature obsolete (oltre soglia); n° contratti in scadenza < finestra; n° verifiche in scadenza < finestra.
- Grafici: distribuzione per tipologia, per zona, per fabbricante; istogramma anzianità (da `DATACOLLAUDO`); parco per anno di collaudo; valore per zona/tipologia (se disponibile). Usa lo stesso motore grafico della dashboard PNRR (plotly o altair, quello che già usi).

**Filtri** (sidebar, coerenti con PNRR): zona/ex-ASL, tipologia, fabbricante, sede/UO, modalità acquisizione, stato, range anno collaudo. Tutte le viste reagiscono ai filtri.

**Drill-down per struttura**
- Elenco/griglia cliccabile delle sedi (UO): al click si apre il dettaglio con la tabella delle apparecchiature di quella sede e le loro caratteristiche complete. Riusa il pattern di drill-down cliccabile già presente nella dashboard PNRR.

**Sezione "Scadenze & Alert"**
- Tre blocchi con semaforo/codice colore: (a) contratti noleggio/locazione in scadenza; (b) verifiche VSE / controlli qualità in scadenza; (c) apparecchiature vetuste oltre soglia per tipologia. Ordina per urgenza, evidenzia scadute (rosso) / in scadenza (giallo) / ok (verde).

**Export**
- Bottone per esportare in Excel (e, se già lo fai nella dashboard PNRR, in PDF) il report filtrato per la Direzione, con intestazione aziendale.

**Mappa (opzionale, se già presente in PNRR)**
- Se la dashboard PNRR ha già un componente mappa, riusalo per localizzare le sedi radiologiche per zona; altrimenti lascialo come TODO, non bloccante.

## Requisiti tecnici

- Python 3.x, Streamlit, pandas, openpyxl + xlrd, motore grafico coerente con PNRR.
- Struttura repo pulita e modulare (data loading / config / componenti UI / pagine), `requirements.txt`, `README.md` con istruzioni di avvio (`streamlit run app.py`).
- Percorsi file **configurabili** (no hardcoding), gestione robusta di valori mancanti e date invalide, nessun dato sensibile in chiaro nel codice.
- Registro assunzioni: se devi assumere qualcosa (es. soglie di vetustà), scrivilo nel README e rendilo configurabile.

## Passi che ti chiedo di seguire

1. Leggi lo scaffold esistente (`app.py`, `data_source.py`, `config.py`, `at20_elm_client.py`) e riassumi cosa riuserai/estenderai. **Non riscrivere da zero.**
2. (Se disponibile) ispeziona la dashboard PNRR Case di Comunità per allinearne stile/palette/componenti; altrimenti procedi con lo stile attuale.
3. Estendi la **modalità NSIS (offline)**, che è quella su cui lavorare ora: rifinisci KPI e grafici, migliora il drill-down struttura→apparecchiature, aggiungi la sezione Scadenze & Alert con semaforo (per ora popolata solo dalla vetustà, con i campi valore/scadenze marcati "n.d." finché la sorgente è il NSIS), e l'export report per la Direzione (Excel e, se lo fai già in PNRR, PDF con intestazione aziendale).
4. Verifica che `carica_api()` in `data_source.py` mappi correttamente i campi del client sullo schema `COLONNE`, così alla riattivazione dell'ambiente Metis basti commutare sorgente. Quando l'API tornerà disponibile: cablare i codici CND/classe delle grandi apparecchiature (recuperabili dalle Codifiche MGCA) nel filtro `AT20Config`, e gestire l'arricchimento per-cespite on-demand con cache per rispettare il rate limit.
5. Aggiorna il `README` con le funzionalità aggiunte e le assunzioni (es. soglie di vetustà).

Procedi step by step, mostrandomi le decisioni chiave prima di generare grandi quantità di codice.
