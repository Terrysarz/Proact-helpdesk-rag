"""
Centrale configuratie voor de Proact Service Desk Assistant (lokale RAG-PoC v3).
"""

import os
from pathlib import Path

# --- Mappen -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "documents"
INDEX_PATH = BASE_DIR / "index.json"
DATA_DIR = BASE_DIR / "data"
TICKETS_PATH = DATA_DIR / "tickets.json"
ACTION_LOG_PATH = DATA_DIR / "action_log.jsonl"

# --- Modellen (moeten in LM Studio geladen/gedownload zijn) -----------------
#   - weinig RAM/geen GPU : "qwen/qwen3-1.7b"  (sneller)
#   - comfortabel         : "qwen/qwen3-4b-2507"
LLM_MODEL = "qwen/qwen3-4b-2507"
EMBEDDING_MODEL = "nomic-embed-text-v1.5"

# --- RAG-parameters ---------------------------------------------------------
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 3
MIN_SCORE = 0.35
MAX_TOKENS = 400
HISTORY_MAX = 8          # hoeveel berichten (user+assistant) we onthouden per sessie

# --- Acties / simulatie -----------------------------------------------------
EMAIL_DOMAIN = "proact.nl"
RESET_LINK_VALID_MINUTES = 30
RESET_BASE_URL = os.getenv("RESET_BASE_URL", "https://reset.proact.local/reset")
# Lab/demo: stuur reset-meldingen naar één adres (bv. je eigen inbox), omdat
# testgebruikers geen echte mailbox hebben. Leeg = naar het adres van de gebruiker.
RESET_NOTIFY_OVERRIDE = os.getenv("RESET_NOTIFY_OVERRIDE", "")

# --- Echt e-mail versturen (optioneel) --------------------------------------
# Vul deze als OMGEVINGSVARIABELEN in (nooit in de code zetten!). Zijn ze leeg,
# dan wordt de reset-mail gesimuleerd i.p.v. echt verstuurd.
#   export SMTP_HOST=smtp.gmail.com
#   export SMTP_USER=jouwadres@gmail.com
#   export SMTP_PASS=<app-wachtwoord>
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "servicedesk@proact.nl")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASS)

# --- Microsoft Graph / Entra ID (optioneel) ---------------------------------
# Vul als omgevingsvariabelen. Als deze leeg zijn, wordt Graph niet gebruikt.
#   export GRAPH_TENANT_ID=...      export GRAPH_CLIENT_ID=...
#   export GRAPH_CLIENT_SECRET=...  export GRAPH_SENDER=servicedesk@jouwtenant.onmicrosoft.com
GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
GRAPH_SENDER = os.getenv("GRAPH_SENDER", "")

# --- On-prem Active Directory (optioneel) -----------------------------------
# Zie de output van scripts/02-Setup-Lab.ps1 voor de juiste waarden.
AD_SERVER = os.getenv("AD_SERVER", "")              # bv. 192.168.2.10
AD_PORT = int(os.getenv("AD_PORT", "636"))
AD_USE_SSL = os.getenv("AD_USE_SSL", "true").lower() == "true"
AD_VALIDATE_CERT = os.getenv("AD_VALIDATE_CERT", "false").lower() == "true"  # false = lab
AD_BASE_DN = os.getenv("AD_BASE_DN", "")            # bv. DC=lab,DC=proact,DC=local
AD_BIND_DN = os.getenv("AD_BIND_DN", "")            # DN van het serviceaccount
AD_BIND_PASSWORD = os.getenv("AD_BIND_PASSWORD", "")
# Gebruikersnamen (sAMAccountName) die 'agent' zijn en ook ANDERE accounts mogen
# resetten. Komma-gescheiden, bv. "terry.sarpong". Leeg = iedereen mag alleen zichzelf.
AD_AGENTS = [a.strip().lower() for a in os.getenv("AD_AGENTS", "").split(",") if a.strip()]

# --- Zelfservice software-uitrol --------------------------------------------
# De gebruiker vraagt een applicatie aan; de chatbot voegt het account toe aan de
# bijbehorende AD-groep. Een GPO met Software Installation (gefilterd op die groep)
# rolt de applicatie vervolgens uit bij de volgende aanmelding. Geen goedkeuring
# nodig voor licentievrije software zoals Adobe Reader.
#   alias/vriendelijke naam (lowercase) -> naam van de AD-groep
APP_GROUPS = {
    "adobe reader": "App-AdobeReader",
    "adobe acrobat reader": "App-AdobeReader",
    "acrobat reader": "App-AdobeReader",
    "acrobat": "App-AdobeReader",
    "adobe": "App-AdobeReader",
    "reader": "App-AdobeReader",
    "7-zip": "App-7Zip",
    "7zip": "App-7Zip",
}
# AD-groep -> nette weergavenaam voor in de chat.
APP_NAMES = {
    "App-AdobeReader": "Adobe Reader",
    "App-7Zip": "7-Zip",
}
# Lijst die aan de gebruiker getoond wordt als "beschikbare software".
APP_DISPLAY = ["Adobe Reader", "7-Zip"]

# --- Systeemprompt ----------------------------------------------------------
# Belangrijk: het model noemt GEEN bronnen meer zelf (dat verzon het soms, bijv.
# "04-m36" i.p.v. "04-m365"). De bronnen worden door de app toegevoegd op basis
# van de écht opgehaalde documenten.
SYSTEM_PROMPT = """Je bent de Proact Service Desk Assistant: een vriendelijke virtuele
helpdesk voor eindgebruikers (klanten).
Beantwoord de vraag UITSLUITEND op basis van de onderstaande context uit de kennisbank.
Regels:
- Schrijf klantgericht: vriendelijk, rustig en in duidelijke stappen, in het Nederlands.
- Gebruik GEEN interne termen of processen (zoals teamnamen, ticketsystemen of
  monitoringtools) in je antwoord. Praat tegen de klant, niet over de interne organisatie.
- Staat het antwoord niet in de context? Zeg dan: "Dat kan ik hier helaas niet
  vinden — ik kan er een ticket voor aanmaken voor de Service Desk."
- Verzin niets en gok niet. Noem zelf GEEN bronnen of bestandsnamen.
- Noem GEEN volledige webadressen (geen https://) en GEEN markdown-links. Verwijs
  hooguit naar de naam van een pagina; de officiële link wordt automatisch toegevoegd.
- Eerdere berichten mag je gebruiken om de bedoeling te begrijpen; baseer feiten
  uitsluitend op de context.
- Houd het kort en behulpzaam."""
