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
