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
# Instelbaar via omgevingsvariabele, zodat je van model kunt wisselen zonder de code
# aan te passen. De naam moet exact overeenkomen met wat LM Studio toont (zie: lms ls).
#   export LLM_MODEL="qwen/qwen3-8b"
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3-8b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text-v1.5")

# --- RAG-parameters ---------------------------------------------------------
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 3
# Relevantiedrempels voor de kennisbank (cosine-score van de bovenste hit). Gemeten met het
# huidige embedding-model: echte vragen scoren 0.67 tot 0.86, vragen buiten het onderwerp 0.62 tot 0.71.
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.66"))     # eronder: direct "niet in de kennisbank"
SURE_SCORE = float(os.getenv("SURE_SCORE", "0.75"))   # erboven: zeker genoeg, direct antwoorden
# Daartussen vraagt de bot het model of de vraag over IT-hulp op het werk gaat.
LLM_RELEVANCE = os.getenv("LLM_RELEVANCE", "true").lower() == "true"
MAX_TOKENS = 400
HISTORY_MAX = 8          # hoeveel berichten (user+assistant) we onthouden per sessie

# --- Verwoording van antwoorden op acties -----------------------------------
# Het taalmodel mag de vaste uitkomst-teksten (ticket, reset, software) in eigen woorden
# zeggen, met de voornaam erbij. De feiten blijven uit de code komen; bij twijfel geldt de
# vaste tekst. Zet op "false" om alleen de vaste teksten te gebruiken.
LLM_PHRASING = os.getenv("LLM_PHRASING", "true").lower() == "true"
LLM_PHRASING_TIMEOUT = float(os.getenv("LLM_PHRASING_TIMEOUT", "20"))   # seconden
# Het taalmodel leest ook korte antwoorden als "ja hoor, doe maar" of "nee, liever anders".
# Korte modelaanroepen (bedoeling lezen, ja/nee, relevantie): na zoveel seconden valt de bot terug
# op de trefwoord-methode, zodat een slapende of uitgezette LM Studio niets blokkeert.
LLM_QUICK_TIMEOUT = float(os.getenv("LLM_QUICK_TIMEOUT", "15"))
LLM_READ_REPLIES = os.getenv("LLM_READ_REPLIES", "true").lower() == "true"

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
}
# AD-groep -> nette weergavenaam voor in de chat.
APP_NAMES = {
    "App-AdobeReader": "Adobe Reader",
}
# Lijst die aan de gebruiker getoond wordt als "beschikbare software".
APP_DISPLAY = ["Adobe Reader"]

# --- Systeemprompt ----------------------------------------------------------
# Belangrijk: het model noemt GEEN bronnen meer zelf (dat verzon het soms, bijv.
# "04-m36" i.p.v. "04-m365"). De bronnen worden door de app toegevoegd op basis
# van de écht opgehaalde documenten.
SYSTEM_PROMPT = """Je bent de Proact Service Desk Assistant: een vriendelijke virtuele
helpdesk voor eindgebruikers (klanten).
Beantwoord de vraag UITSLUITEND op basis van de onderstaande context uit de kennisbank.

Denk eerst mee met de klant voordat je antwoordt:
- Lees goed wat de klant AL heeft verteld of geprobeerd, ook in eerdere berichten, en
  speel daarop in. Ga uit van wat de klant zegt.
- Stel nooit voor om iets te controleren of te proberen wat de klant net al heeft gemeld.
  Zegt de klant bijvoorbeeld dat inloggen op de webversie niet lukt, ga daar dan vanuit
  en geef meteen de stap die daarbij hoort; stuur de klant niet terug om datzelfde opnieuw
  te doen.
- Kies de ene of twee stappen die echt bij deze situatie passen. Som geen hele lijst met
  mogelijkheden op.
- Herhaal niet je vorige antwoord. Komt de vraag in de kern op hetzelfde neer als daarvoor,
  breng het dan verder: geef de volgende logische stap, stel EEN gerichte vervolgvraag, of
  bied aan een ticket aan te maken.
- Weet je op basis van de context niet genoeg om verder te helpen, blijf dan niet herhalen
  maar bied een ticket aan.

Schrijfstijl en regels:
- Schrijf klantgericht: vriendelijk, rustig en in duidelijke stappen, in het Nederlands.
- Begin niet elk antwoord met een groet; een groet hoort alleen bij het eerste contact.
- Gebruik GEEN interne termen of processen (zoals teamnamen, ticketsystemen of
  monitoringtools) in je antwoord. Praat tegen de klant, niet over de interne organisatie.
- Staat het antwoord niet in de context? Zeg dan: "Dat kan ik hier helaas niet vinden. Ik
  kan er wel een ticket voor aanmaken voor de Service Desk."
- Verzin niets en gok niet. Noem zelf GEEN bronnen of bestandsnamen.
- Noem GEEN volledige webadressen (geen https://) en GEEN markdown-links. Verwijs
  hooguit naar de naam van een pagina; de officiële link wordt automatisch toegevoegd.
- Eerdere berichten mag je gebruiken om de bedoeling te begrijpen; baseer feiten
  uitsluitend op de context.
- Gebruik nooit een gedachtestreepje (het teken "—"). Gebruik in plaats daarvan een komma,
  een punt of een dubbele punt.
- Houd het kort en behulpzaam."""
