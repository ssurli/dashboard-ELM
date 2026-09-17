"""Configurazione centralizzata del cruscotto Grandi Apparecchiature."""

# Mapping codice ex-ASL (colonna 'EX ASL' del NSIS) -> denominazione zona.
# Verificare con Metis: in AT2.0 la zona arriva già come 'zonaDenominazione'.
ZONE = {
    1: "Massa-Carrara",
    2: "Lucca",
    5: "Pisa",
    6: "Livorno",
    12: "Versilia",
}

# --------------------------------------------------------------------------- #
# Sotto-aziende (ex-ASL) — dimensione PRIMARIA per questo cruscotto
# --------------------------------------------------------------------------- #
# IMPORTANTE — verificato sui dati reali ELM: 'zonaDenominazione' (il campo 'zona'
# del parco) NON è la ex-ASL. È il DISTRETTO sanitario (es. "Zona Apuana",
# "Lunigiana", "Valle del Serchio", "Valdera", "Alta Val di Cecina"), a volte non
# valorizzato ("DEFAULT", "Beni da ubicare"). I distretti cambiano nel tempo: NON
# compilare a mano una mappa distretto->azienda, si disallineerebbe. La dimensione
# affidabile è la sotto-azienda, esposta direttamente dal Cespite_ELM come
# aziendaDenominazione/aziendaCodice — usarla da lì (vedi at20_elm_client.py e
# data_source.mappa_cespiti_a_schema), non derivarla dalla zona/distretto.
#
# Riferimento (codici AT2.0, coincidono con quelli già citati nel §8 del README):
SOTTO_AZIENDE = {
    101: "Massa e Carrara",
    102: "Lucca",
    105: "Pisa",
    106: "Livorno",
    112: "Viareggio",
}

# Mapping codice ex-ASL del NSIS ('EX ASL', numerazione 1/2/5/6/12 — diversa da
# quella AT2.0 sopra, stesso concetto) -> nome sotto-azienda, per popolare 'azienda'
# quando la sorgente è il NSIS (che non ha aziendaDenominazione) e restare
# confrontabili con l'azienda derivata dall'API (data_source normalizza il prefisso
# "AUSL TNo - " che l'API restituisce, per far combaciare i nomi).
EX_ASL_AD_AZIENDA = {
    1: "Massa e Carrara",
    2: "Lucca",
    5: "Pisa",
    6: "Livorno",
    12: "Viareggio",
}

# Soglie di vetustà (anni) per tipologia. Configurabili: adattare alle policy aziendali.
SOGLIE_VETUSTA = {
    "TAC": 8,
    "RISONANZA": 8,
    "SISTEMI TAC/PET": 8,
    "MAMMOGRAFI": 10,
    "ANGIOGRAFI": 10,
    "ACCELERATORI LINEARI": 10,
    "GAMMA CAMERE COMPUTERIZZATE": 10,
}
SOGLIA_VETUSTA_DEFAULT = 10

# Finestra di alert per le scadenze (mesi). Usata quando i dati di scadenza
# saranno disponibili (sorgente API), non presenti nel NSIS.
FINESTRA_ALERT_MESI = 12

# Margine (anni) sotto la soglia entro cui un'apparecchiatura è "in avvicinamento".
MARGINE_AVVICINAMENTO_ANNI = 2

# Normalizzazione nomi fabbricante (match per sottostringa, case-insensitive).
ALIAS_FABBRICANTE = {
    "philips": "Philips",
    "siemens": "Siemens",
    "general electric": "GE",
    "ge medical": "GE",
    "fuji": "Fuji",
    "toshiba": "Toshiba",
    "varian": "Varian",
    "elekta": "Elekta",
    "esaote": "Esaote",
    "hologic": "Hologic",
    "paramed": "Paramed",
    "spectrum": "Spectrum",
}

# Percorso di default del file NSIS (fallback offline).
NSIS_PATH_DEFAULT = "NSIS.xls"

# Parole chiave (sottostringa su 'tipologia', case-insensitive) che identificano una
# riga come accessorio/consolle/componente di una grande apparecchiatura (es. la
# consolle di comando di un TAC, un iniettore per RM) e non l'unità principale.
# In ELM sono censiti come cespiti a sé stanti. Di default restano visibili come
# righe separate (più fedele all'inventario); il filtro "Nascondi accessori" in
# sidebar usa questa lista per escluderli su richiesta.
PAROLE_CHIAVE_ACCESSORIO = (
    "consolle", "accessorio", "tavolo per", "iniettore per", "carrello",
    "stativo per", "alimentatore", "bobina per", "dosimetria per",
)

# Intestazione aziendale per i report esportati.
AZIENDA_NOME = "Azienda USL Toscana Nord Ovest"
AZIENDA_UOC = "UOC Tecnologie — Dipartimento Tecnico e Patrimonio"
