"""
Intent-router: bepaalt wat de gebruiker wil, VOORDAT we iets met het trage LLM doen.

Dit is de kern van de snelheidswinst: begroetingen, actie-verzoeken en
onbekende vragen worden direct afgehandeld. Alleen een echte kennisvraag gaat
naar RAG + LLM.

Intents:
  - "greeting"        : hoi / hallo / goedemorgen ...
  - "password_reset"  : een VERZOEK om een reset uit te voeren (actie)
  - "create_ticket"   : een VERZOEK om een ticket aan te maken (actie)
  - "question"        : alle inhoudelijke vragen -> RAG
"""

from __future__ import annotations
import re

GREETINGS = {
    "hoi", "hi", "hallo", "hey", "hee", "yo", "goedemorgen", "goedemiddag",
    "goedenavond", "hello", "dag", "hoihoi", "hai",
}

# Woorden die op een expliciete opdracht/wens wijzen (actie i.p.v. uitlegvraag).
_REQUEST_CUES = (
    "reset mijn", "reset me", "wil mijn", "wil een", "wil graag", "kun je mijn",
    "kun je een", "kan je mijn", "kan je een", "maak een", "open een",
    "start een", "stuur mij", "stuur me", "mijn wachtwoord resetten",
    "wachtwoord resetten voor", "regel een", "ik wil", "installeer",
    "ik heb nodig", "heb ik nodig",
)

# Vraagwoorden wijzen op een uitlegvraag -> RAG, niet op een actie.
_QUESTION_CUES = ("hoe ", "waar ", "wat ", "waarom ", "wanneer ", "welke ", "kan ik ", "mag ik ")

_PW_WORDS = ("wachtwoord", "password", "inloggen", "aanmelden")
_PW_RESET_WORDS = ("reset", "resetten", "vergeten", "kwijt", "opnieuw", "nieuw", "geblokkeerd", "vastgelopen")
_TICKET_WORDS = ("ticket", "melding", "storing", "incident", "aanvraag")
# Zelfservice software-uitrol (installeer/aanvragen van een applicatie).
# Werkwoorden en concrete app-namen zijn een STERK actiesignaal (ook zonder los
# verzoekwoord); algemene woorden ("software") hebben wél een verzoekwoord nodig.
_SOFTWARE_VERBS = ("installeer", "installeren", "installatie", "uitrollen", "uitrol")
_APP_HINTS = ("adobe", "acrobat", "reader", "7-zip", "7zip")
_SOFTWARE_WORDS = _SOFTWARE_VERBS + ("software", "programma", "applicatie") + _APP_HINTS


def _normalize(text: str) -> str:
    return text.strip().lower()


def is_greeting(text: str) -> bool:
    t = _normalize(text).strip("!?. ")
    if not t:
        return False
    # Alleen als het hele bericht een korte groet is (max 3 woorden, bevat een groet).
    words = t.split()
    return len(words) <= 3 and any(w.strip(",.!?") in GREETINGS for w in words)


def _looks_like_request(text: str) -> bool:
    t = _normalize(text)
    if any(cue in t for cue in _REQUEST_CUES):
        return True
    # Een imperatief aan het begin ("reset ...", "maak ...", "installeer ...").
    return bool(re.match(r"^(reset|maak|open|start|stuur|regel|installeer)\b", t))


def classify(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "question"

    if is_greeting(t):
        return "greeting"

    is_question_phrasing = any(t.startswith(c) or (" " + c) in (" " + t) for c in _QUESTION_CUES)
    request = _looks_like_request(t)

    # Software aanvragen/installeren: alleen als ACTIE bedoeld, niet als uitlegvraag.
    if not is_question_phrasing and any(w in t for w in _SOFTWARE_WORDS):
        strong = any(v in t for v in _SOFTWARE_VERBS) or any(a in t for a in _APP_HINTS)
        if strong or request:
            return "software_request"

    # Wachtwoordreset: alleen als ACTIE bedoeld (verzoek), niet als uitlegvraag.
    if any(w in t for w in _PW_WORDS) and any(w in t for w in _PW_RESET_WORDS):
        if request and not is_question_phrasing:
            return "password_reset"

    # Ticket aanmaken: verzoek + ticketwoord.
    if any(w in t for w in _TICKET_WORDS) and (request or "ticket" in t) and not is_question_phrasing:
        return "create_ticket"

    return "question"


# --- Hulpfuncties om gegevens uit een bericht te halen ----------------------

_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE)
# Een losstaande gebruikersnaam (letters/cijfers/punt), minstens 3 tekens.
_USERNAME_RE = re.compile(r"\b([a-z][a-z0-9._\-]{2,})\b", re.IGNORECASE)

_STOPWORDS = {
    "reset", "wachtwoord", "password", "mijn", "voor", "van", "het", "een", "account",
    "resetten", "graag", "alsjeblieft", "please", "naar", "met", "stuur", "maak",
    "ticket", "open", "start", "regel", "the", "ik", "wil", "je", "kun", "kan",
}


def extract_identifier(text: str) -> str | None:
    """Haalt een e-mailadres of gebruikersnaam uit het bericht, indien aanwezig."""
    email = _EMAIL_RE.search(text)
    if email:
        return email.group(0).lower()
    # Zoek een plausibele gebruikersnaam die geen gewoon woord is.
    for match in _USERNAME_RE.finditer(text):
        token = match.group(1).lower()
        if token in _STOPWORDS:
            continue
        # Gebruikersnamen bevatten vaak een punt (voornaam.achternaam) of een cijfer.
        if "." in token or any(ch.isdigit() for ch in token):
            return token
    return None
