# Cruscotto Grandi Apparecchiature — AUSL Toscana Nord Ovest

Dashboard aziendale (Streamlit) per il monitoraggio delle grandi apparecchiature
(TAC, RM, mammografi, angiografi, acceleratori lineari, gamma camere, sistemi TAC/PET),
con caratteristiche, valore economico, stato contrattuale, scadenze e vetustà.
Sorgente dati: modulo **ELM** (Elettromedicali) della piattaforma **Area Tecnica 2.0**
del Consorzio Metis, con fallback sull'estrazione **NSIS**.

## File del progetto

| File | Cosa contiene |
|---|---|
| `app.py` | Dashboard Streamlit (KPI, filtri, drill-down, semaforo vetustà, export) |
| `data_source.py` | Layer sorgente unico (`COLONNE`): NSIS, API live, cache su file |
| `config.py` | Mapping zone ex-ASL, soglie vetustà, alias fabbricante |
| `at20_elm_client.py` | Client ELM (auth, paginazione, rate limit, normalizzazione) |
| `mgca_client.py` | Client MgCA (codifiche; classi con flag `grandeApparecchiatura`) |
| `sync.py` | Scarica il parco ELM e lo salva in cache `parco.parquet` |
| `diag.py` | Diagnostica connessione API |
| `NSIS.xls` | Estrazione NSIS (sorgente offline) |
| `requirements.txt`, `README.md` | Dipendenze e questo file |

## 1. Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Credenziali (mai nel codice)

Crea un file `.env` in questa cartella (aggiungilo a `.gitignore`):

```dotenv
AT20_BASE_URL=https://at20test.consorziometis.it/elm/rest
AT20_TOKEN_URL=https://at20test.consorziometis.it/mgca/rest/v2/oauth/token
AT20_CODICE_AZIENDA=202
AT20_API_KEY=...
AT20_USER=...
AT20_PASS=...
```

Windows/PowerShell: per creare il file usa `New-Item .env -ItemType File` (Blocco note
salverebbe `.env.txt`). Produzione: sostituire `at20test` con `at20` e usare le
credenziali di produzione. Alla messa in produzione, chiedere a Metis la rotazione
dell'apikey di test.

## 3. Avvio

```bash
streamlit run app.py
```

Nella sidebar si sceglie la **sorgente dati** (vedi sotto).

## 4. Le tre sorgenti dati

- **NSIS (offline)** — legge `NSIS.xls`. Istantaneo, per sviluppo. Valore economico
  e scadenze non presenti (mostrati "n.d.").
- **API (cache)** — legge `parco.parquet` prodotto da `sync.py`. Veloce (millisecondi):
  è la modalità da usare in esercizio.
- **API live** — interroga ELM in tempo reale. Lenta sul parco completo (vedi §6):
  usare **sempre** con il limite "Max cespiti" attivo in sidebar.

Tutte producono lo **stesso schema** (`data_source.COLONNE`), quindi la UI non cambia
tra le sorgenti.

## 5. Sincronizzazione della cache (`sync.py`)

```bash
python sync.py                 # sync completa (lenta, una tantum) -> parco.parquet
python sync.py --incrementale  # solo i cespiti modificati dall'ultima sync (via dataDa)
```

Consigliato schedularla (es. Utilità di pianificazione di Windows) di notte. La
dashboard su "API (cache)" legge poi il file all'istante.

## 6. Autenticazione e prestazioni (importante)

- **Token**: OAuth2 password grant su `AT20_TOKEN_URL` (modulo MgCA), header
  `Authorization: Basic Y2xpZW50OnNlY3JldA==` + body `grant_type=password`, username,
  password. Ogni chiamata invia **Bearer token + header `apikey`** insieme.
- **Rate limit**: 2 richieste/secondo (gestito dal client).
- **Overhead per richiesta ~2,5s** lato server ELM, a prescindere dalla dimensione di
  pagina. Con `page_size=1000` il parco completo (~56.000 cespiti) richiede **~2-3 minuti**:
  per questo la dashboard usa la **cache** e non l'API live per il caricamento pieno.
- **Arricchimento** (contratti/scadenze) fa ~4 chiamate per cespite: NON eseguirlo in
  blocco. Va fatto **on-demand sulla riga selezionata**, con cache (`arricchisci=False`
  di default nel loader API).

## 7. Filtro "grandi apparecchiature"

Esatto, non euristico: `mgca_client.py` legge da MgCA le classi con
`grandeApparecchiatura=True` e ne ricava i codici classe, usati dal connettore ELM per
filtrare i cespiti. Se MgCA non risponde, si ricade sull'euristica per parola chiave.

## 8. Multi-azienda (ex-ASL)

In ELM i cespiti risiedono sulle cinque **sotto-aziende** ex-ASL, non sul codice 202:

| Codice | Zona |
|---|---|
| 101 | Massa e Carrara |
| 102 | Lucca |
| 105 | Pisa |
| 106 | Livorno |
| 112 | Viareggio |

Corrispondono alle zone `EX ASL` del NSIS (1→101, 2→102, 5→105, 6→106, 12→112). Da
chiarire con Metis **come** selezionare la sotto-azienda sulle chiamate ELM (parametro,
apikey dedicate, o visibilità già inclusa nell'utenza): da questo dipende l'eventuale
iterazione sulle cinque aziende nel client/`sync.py`.

## 9. Rifiniture modalità NSIS (offline) — coerenza con la dashboard PNRR gemella

Stile e componenti allineati alla dashboard Streamlit "Tecnologie sanitarie PNRR"
(`dashboard_telemedicina.py`, repo `ssurli/tecnologie-sanitarie-pnrr`): Streamlit nativo
senza CSS custom, KPI a righe con `st.metric`, alert con `st.error/warning/info`, blocco
sidebar "📊 Info dataset" con pulsante "🔄 Aggiorna dati" (`st.cache_data.clear()`), e un
export Excel multi-foglio con intestazione aziendale in stile `genera_report_direzione.py`
(header blu, colonne auto-larghezza, righe evidenziate).

Novità aggiunte in questa iterazione:
- KPI "Sedi / UO" nella home.
- Colonna `valore_economico` visibile (formattata `€`, "n.d." se assente) nelle tabelle
  Elenco e Vetustà.
- Placeholder non bloccante "📍 Distribuzione geografica" (mappa non ancora disponibile:
  servono le coordinate GPS delle sedi, non presenti in NSIS né nell'API AT2.0 attuale).
- Tab **Export**: bottone "📊 Report Direzione (Excel)" — foglio Executive Summary +
  Vetustà & Alert (semaforo colorato, ordinato per urgenza) + Elenco apparecchiature,
  ognuno con intestazione aziendale (`config.AZIENDA_NOME`/`AZIENDA_UOC`). L'export
  "grezzo" a foglio singolo resta disponibile per elaborazioni successive.
- **Fix loader NSIS**: la colonna `DATACOLLAUDO` è mista — quasi sempre una data
  completa, ma per alcune righe (14/79 nell'estrazione corrente) contiene solo
  l'anno come intero (es. `2013`). `pd.to_datetime()` su un intero nudo lo interpreta
  come timestamp Unix in **nanosecondi**, facendolo collassare al 1970 e gonfiando
  artificialmente anzianità/vetustà. `data_source._parse_data_collaudo()` intercetta
  questo caso e lo tratta come 1° gennaio dell'anno indicato.

Nessuna mappa geografica delle sedi anche nel repo PNRR (stesso placeholder "servono le
coordinate GPS"): TODO non bloccante, non replicato per mancanza di anagrafica sedi
georeferenziata in nessuna delle due sorgenti dati.

## 10. Stato e prossimi passi

- Integrazione ELM + MgCA: pronta e testata a livello di codice.
- Ambiente **test**: anagrafica cespiti da popolare/abilitare correttamente (contratti
  presenti, cespiti no) — per questo è stata richiesta a Metis la produzione o il
  popolamento del test.
- Soglie di vetustà in `config.py` (default TAC/RM 8 anni, resto 10): allineare alle
  policy aziendali.
- Mappa geografica delle sedi: da fare quando sarà disponibile un'anagrafica sedi
  con coordinate GPS (non presente né nel NSIS né nell'API AT2.0 attuale).
