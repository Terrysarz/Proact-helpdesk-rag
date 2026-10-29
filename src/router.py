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
import difflib

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
    "kun je dat", "kan je dat", "kun jij", "kan jij", "kunnen jullie", "kunt u", "zou je",
)

# Vraagwoorden wijzen op een uitlegvraag -> RAG, niet op een actie.
_QUESTION_CUES = ("hoe ", "waar ", "wat ", "waarom ", "wanneer ", "welke ", "kan ik ", "mag ik ")

_PW_WORDS = ("wachtwoord", "password", "inloggen", "aanmelden")
# "Ik ben mijn wachtwoord vergeten" / "ik wil mijn wachtwoord aanpassen": geen kale opdracht,
# maar wel een duidelijke wens om te resetten. De bot vraagt dan eerst of hij het mag doen.
_PW_FORGOT = ("vergeten", "kwijt", "weet ik niet", "weet het niet", "geblokkeerd", "vergrendeld", "verlopen")
_PW_CHANGE = ("wijzigen", "wijzig", "aanpassen", "veranderen", "aan te passen", "te veranderen", "te wijzigen")
# Bericht dat naar het gesprek verwijst en de assistent iets laat DOEN ("kan jij het voor me ...").
_DELEGATION_CUES = ("voor me", "voor mij", "jij het", "jij dit", "doe het", "doe maar", "regel het",
                    "ik wil dat jij", "kan jij", "kun jij", "kun je het", "kan je het", "kun je dit", "kan je dit")


def is_delegation(text: str) -> bool:
    t = _normalize(text)
    return _looks_like_request(t) or any(cue in t for cue in _DELEGATION_CUES)


_PW_RESET_WORDS = ("reset", "resetten", "vergeten", "kwijt", "opnieuw", "nieuw", "geblokkeerd", "vastgelopen")
_TICKET_WORDS = ("ticket", "melding", "storing", "incident", "aanvraag")
# Zelfservice software-uitrol (installeer/aanvragen van een applicatie).
# Een INSTALLATIE-werkwoord is een echt actiesignaal. Een kale app-naam is dat NIET:
# "de reader opent niet" of "heb ik adobe?" mogen nooit zomaar een installatie starten.
_SOFTWARE_VERBS = ("installeer", "installeren", "installatie", "uitrollen", "uitrol",
                   "aanvragen", "aanvraag", "toevoegen", "erbij zetten")
_APP_HINTS = ("adobe", "acrobat", "reader")
_SOFTWARE_WORDS = _SOFTWARE_VERBS + ("software", "programma", "applicatie") + _APP_HINTS

# De gebruiker wil CONTROLEREN of iets er is, niet iets installeren.
_CHECK_CUES = ("kijken of", "kijk of", "checken of", "check of", "controleer", "controleren",
               "nagaan", "ga na", "heb ik toegang", "heb ik al", "heb ik recht",
               "al toegang", "al geinstalleerd", "al geïnstalleerd", "staat het al",
               "heb ik ", "is er al")
# De gebruiker wil software VERWIJDEREN / deïnstalleren.
_REMOVE_CUES = ("verwijder", "verwijderen", "deinstalleer", "deïnstalleer", "de-installeer",
                "weghalen", "haal weg", "haal eraf", "eraf halen", "eraf", "wil ik niet meer",
                "hoef ik niet meer", "mag weg", "uitzetten")
# Het verzoek gaat over IEMAND ANDERS, niet over het eigen account.
_OTHER_USER_CUES = ("andere gebruiker", "iemand anders", "een ander", "collega", "medewerker",
                    "namens", "voor iemand", "ander account", "voor de gebruiker",
                    "een gebruiker")
# Een probleemMELDING is geen installatieverzoek -> die hoort bij uitleg/ticket.
_PROBLEM_CUES = ("werkt niet", "werkt niet meer", "lukt niet", "doet het niet", "doet niets",
                 "crasht", "vastgelopen", "loopt vast", "foutmelding", "error", "start niet",
                 "opent niet", "niet openen", "niet starten", "niet meer", "probleem met",
                 "kapot", "hangt")


def _normalize(text: str) -> str:
    return text.strip().lower()


_THANKS = ("bedankt", "dankjewel", "dankje", "dank je", "dankuwel", "thanks", "thx", "thank you", "tnx")
_BYE = ("doei", "doeg", "tot ziens", "tot later", "tot snel", "bye", "houdoe", "fijne dag", "fijne avond")


def is_noise(text: str) -> bool:
    """Alleen leestekens of een enkel teken: geen inhoud om op te antwoorden."""
    return len(re.findall(r"[^\W\d_]", text)) < 2 and not re.search(r"\d", text)


def is_thanks(text: str) -> bool:
    t = _normalize(text)
    return len(t.split()) <= 5 and any(w in t for w in _THANKS)


def is_bye(text: str) -> bool:
    t = _normalize(text)
    return len(t.split()) <= 5 and any(w in t for w in _BYE)


def is_greeting(text: str) -> bool:
    t = _normalize(text).strip("!?. ")
    if not t:
        return False
    # Alleen als het hele bericht een korte groet is (max 3 woorden, bevat een groet).
    words = t.split()
    if len(words) > 3:
        return False
    for w in (x.strip(",.!?") for x in words):
        if w in GREETINGS:
            return True
        # Typfout in een groet ("hellop", "hoii", "goedemorgn")
        if len(w) >= 4 and difflib.get_close_matches(w, GREETINGS, n=1, cutoff=0.8):
            return True
    return False


def _looks_like_request(text: str) -> bool:
    t = _normalize(text)
    if any(cue in t for cue in _REQUEST_CUES):
        return True
    # Een imperatief aan het begin ("reset ...", "maak ...", "installeer ...").
    return bool(re.match(r"^(reset|maak|open|start|stuur|regel|installeer)\b", t))


def wants_status(text: str) -> bool:
    """De gebruiker wil CONTROLEREN of iets aanwezig is (geen actie)."""
    return any(cue in _normalize(text) for cue in _CHECK_CUES)


def wants_remove(text: str) -> bool:
    """De gebruiker wil software laten verwijderen/deïnstalleren."""
    return any(cue in _normalize(text) for cue in _REMOVE_CUES)


def mentions_other_user(text: str) -> bool:
    """Het verzoek gaat over iemand anders dan het eigen account."""
    return any(cue in _normalize(text) for cue in _OTHER_USER_CUES)


def _is_problem_report(text: str) -> bool:
    """Een storings-/probleemmelding (hoort bij uitleg/ticket, niet bij installeren)."""
    return any(cue in _normalize(text) for cue in _PROBLEM_CUES)


def software_topic(text: str) -> bool:
    """Ruwe voorfilter: zou dit over werkplek-software of toegang kunnen gaan? Zo ja, laat
    het LLM de precieze bedoeling lezen. Breed opgezet; de fijn-bepaling doet het model."""
    t = _normalize(text)
    if any(a in t for a in _APP_HINTS):
        return True
    if any(w in t for w in ("software", "programma", "applicatie", "app ", "tool")):
        return True
    if any(v in t for v in _SOFTWARE_VERBS):
        return True
    # Ondubbelzinnige deïnstalleer-werkwoorden gaan altijd over software.
    if any(v in t for v in ("deinstalleer", "deïnstalleer", "de-installeer", "uninstall")):
        return True
    if "toegang" in t or "access" in t:
        return True
    return False


def classify(text: str) -> str:
    t = _normalize(text)
    if not t:
        return "question"

    if is_noise(t):
        return "noise"

    if is_greeting(t):
        return "greeting"

    if is_thanks(t):
        return "thanks"

    if is_bye(t):
        return "bye"

    is_question_phrasing = any(t.startswith(c) or (" " + c) in (" " + t) for c in _QUESTION_CUES)
    request = _looks_like_request(t)
    # "wil mijn wachtwoord NIET resetten": een ontkenning is geen verzoek om te resetten.
    negated_reset = bool(re.search(r"\b(niet|geen)\s+(\w+\s+)?(reset|resetten)\b", t))

    # Software: eerst LEZEN wat de gebruiker wil, dan pas routeren.
    software_ctx = any(w in t for w in _SOFTWARE_WORDS)
    if software_ctx:
        # 1) Controlevraag ("heb ik toegang / kijken of ...") -> status, geen installatie.
        if wants_status(t):
            return "software_status"
        has_verb = any(v in t for v in _SOFTWARE_VERBS)
        # 2) Uitlegvraag ("hoe installeer ik ...") of probleemmelding ("de reader opent niet")
        #    is GEEN installatieverzoek.
        problemish = _is_problem_report(t) or ("niet" in t and not has_verb)
        if not is_question_phrasing and not problemish:
            # 3) Alleen installeren bij een echt actiesignaal: een werkwoord, een verzoek,
            #    of een concrete app-naam (bv. "adobe reader").
            if has_verb or request or any(a in t for a in _APP_HINTS):
                return "software_request"

    # Wachtwoordreset: alleen als ACTIE bedoeld (verzoek), niet als uitlegvraag.
    if any(w in t for w in _PW_WORDS) and any(w in t for w in _PW_RESET_WORDS):
        if request and not is_question_phrasing and not negated_reset:
            return "password_reset"

    # Wachtwoord vergeten of wijzigen als WENS: de bot biedt de reset aan en vraagt om bevestiging.
    pw_strict = "wachtwoord" in t or "password" in t
    if pw_strict and not negated_reset:
        starts_q = any(t.startswith(c) for c in _QUESTION_CUES)
        if any(w in t for w in _PW_FORGOT) and not starts_q:
            return "password_forgot"
        if any(w in t for w in _PW_CHANGE) and request and not is_question_phrasing:
            return "password_forgot"

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
