"""
Ticket-intake: eerst het probleem vaststellen en bevestigen, dan pas aanmaken.
"""

from __future__ import annotations
import re

import actions
import lmclient
import router
from flow_common import _CANCEL, _direct, _pick, _reply_kind


_NO_TICKET = ["Oké, ik heb geen ticket aangemaakt. Kan ik iets anders doen?",
              "Prima, dan laat ik het zo. Is er nog iets anders waar ik mee kan helpen?",
              "Geen probleem, er is geen ticket gemaakt. Zeg het maar als ik nog iets kan doen."]


# Een "maak (dan/even) een ticket (aan) (voor/over)"-frase vooraan strippen,
# inclusief vulwoorden, om het eigenlijke onderwerp over te houden.
_TICKET_PREFIX_RE = re.compile(
    r"(?i)^(?:(?:kun je|kan je|kan|kun|kunt|kunnen|zou je|mag|graag|ik wil|ik zou graag|maak|open|"
    r"start|regel|even|dan|maar|toch|alsjeblieft|aub|ook|nog|jij|jullie|voor me|voor mij|er)\s+)*"
    r"(?:een |de |het )?ticket"
    r"(?:\s+(?:gemaakt worden|worden gemaakt|aangemaakt worden|worden aangemaakt|aanmaken|"
    r"aan maken|maken|gemaakt|aangemaakt|aan))?"
    r"(?:\s+(?:voor|over))?\s*"
)


_REFERS_BACK = (
    "net ", "zojuist", "hiervoor", "ervoor", "eerder", "die melding", "dat probleem",
    "dit probleem", "nog steeds", "nogsteeds", "net vroeg", "net vrog", "die je net",
    "waar we het", "hierover", "hiervan",
)


# Trefwoorden om het laatste inhoudelijke onderwerp in het gesprek te herkennen.
_TOPIC_WORDS = (
    "teams", "outlook", "onedrive", "sharepoint", "wachtwoord", "password", "mfa", "vpn",
    "printer", "printen", "afdruk", "licentie", "defender", "antivirus", "camera", "geluid",
    "microfoon", "sync", "verbinding", "e-mail", "email", "mail", "office", "365", "entra",
    "aanmelden", "inloggen",
)


_VAGUE = {"", "aan", "ervoor", "hiervoor", "hiervan", "dit", "dat", "deze", "die", "hierover"}


def _topic_problem(history: list[dict]) -> str:
    """Zoekt het laatste gebruikersbericht met een herkenbaar onderwerp (trefwoord),
    anders de laatste echte vraag."""
    for m in reversed(history):
        if m["role"] == "user" and any(w in m["content"].lower() for w in _TOPIC_WORDS):
            return m["content"]
    for m in reversed(history):
        if m["role"] == "user" and router.classify(m["content"]) == "question":
            return m["content"]
    return ""


# --- Ticket-intake: eerst info verzamelen, dan pas aanmaken ------------------

_TICKET_FIELDS = [
    ("onderwerp", "Geef kort het onderwerp van je melding (bijv. 'PowerPoint start niet')."),
    ("beschrijving", "Omschrijf het probleem wat uitgebreider: wat gebeurt er precies, "
                     "sinds wanneer, en is er een foutmelding?"),
    ("naam", "Wat is je naam?"),
    ("bedrijf", "Bij welk bedrijf of welke klantomgeving hoor je?"),
    ("telefoon", "Op welk telefoonnummer kunnen we je bereiken? (bijv. 06-12345678)"),
]


def _short_subject(text: str) -> str:
    """Maakt een kort onderwerp van een langere tekst (eerste ~8 woorden)."""
    text = text.strip()
    words = text.split()
    return " ".join(words[:8]) if len(words) > 8 else text


def _prefill_subject(msg: str, history: list[dict]) -> str:
    """Bruikbaar onderwerp uit bericht/gesprek; lege string als het onbekend is."""
    low = msg.strip().lower()
    problem = _topic_problem(history)
    if any(w in low for w in _REFERS_BACK) and problem:
        return problem
    m = _TICKET_PREFIX_RE.match(low)
    remainder = msg.strip()[m.end():].strip() if m else msg.strip()
    rem_low = remainder.lower().strip(" .,-!?")
    if rem_low and rem_low not in _VAGUE and len(rem_low) >= 4:
        return remainder
    return problem or ""


def _explicit_subject(msg: str) -> str:
    """Noemt het bericht zelf het onderwerp ('ticket voor een onedrive probleem')? Dan wint
    dat van het gesprek. Lege string als het bericht alleen om een ticket vraagt."""
    low = msg.strip().lower()
    if "ticket" not in low or any(w in low for w in _REFERS_BACK):
        return ""
    m = _TICKET_PREFIX_RE.match(low)
    remainder = msg.strip()[m.end():].strip() if m else ""
    rem_low = remainder.lower().strip(" .,-!?")
    return remainder if rem_low and rem_low not in _VAGUE and len(rem_low) >= 4 else ""


def _next_ticket_field(t: dict):
    for field, question in _TICKET_FIELDS:
        if not t.get(field):
            return field, question
    return None, None


def _begin_ticket(session: dict, history: list[dict], request_msg: str = "") -> dict:
    """Start de intake. Het LLM leest het probleem uit het GESPREK en stelt een onderwerp
    + omschrijving voor; de gebruiker bevestigt dat kort (optie A). Lukt dat niet, dan
    valt het terug op de eenvoudige methode. Naam/bedrijf komen uit de login."""
    auth = session.get("auth") or {}

    onderwerp, beschrijving = "", ""
    explicit = _explicit_subject(request_msg)
    try:
        if explicit:        # het bericht noemt zelf het onderwerp: dat gaat voor het gesprek
            onderwerp, beschrijving = lmclient.summarize_ticket([], explicit)
        else:
            onderwerp, beschrijving = lmclient.summarize_ticket(history, request_msg)
    except Exception:
        onderwerp, beschrijving = "", ""
    if explicit and not onderwerp:
        onderwerp = _short_subject(explicit)
    if not onderwerp:                       # vangnet: oude, eenvoudige afleiding
        onderwerp = _prefill_subject(request_msg, history)
    if onderwerp and not beschrijving:
        beschrijving = onderwerp

    t = {"onderwerp": onderwerp or "", "beschrijving": beschrijving or "",
         "naam": auth.get("name", ""), "bedrijf": auth.get("company", ""),
         "telefoon": ""}
    session["ticket"] = t

    # Hebben we een zinnig onderwerp uit het gesprek? Vraag dan om bevestiging (optie A).
    if onderwerp:
        session["ticket_confirm"] = True
        omschr = f"\nOmschrijving: *{beschrijving}*" if beschrijving else ""
        return _direct("ticket",
                       f"Ik maak een ticket voor je aan over: **{onderwerp}**.{omschr}\n\n"
                       f"Klopt dat? Typ **ja** om door te gaan, of omschrijf kort hoe het anders moet.")

    # Geen context om op te bouwen: vraag gewoon het onderwerp (oude gedrag).
    field, question = _next_ticket_field(t)
    if field is None:
        return _finish_ticket(session)
    return _direct("ticket", f"Prima, ik maak een ticket voor je aan.\n\n{question}")


def _ask_next_or_finish(session: dict) -> dict:
    """Stelt de volgende ontbrekende vraag, of maakt het ticket aan als alles er is."""
    t = session["ticket"]
    nxt_field, nxt_q = _next_ticket_field(t)
    if nxt_field:
        return _direct("ticket", nxt_q)
    return _finish_ticket(session)


def _finish_ticket(session: dict) -> dict:
    t = session.pop("ticket")
    auth = session.get("auth") or {}
    ticket = actions.create_ticket(
        subject=t["onderwerp"],
        description=t.get("beschrijving") or t["onderwerp"],
        naam=t.get("naam", ""), bedrijf=t.get("bedrijf", ""),
        telefoon=t.get("telefoon", ""),
    )
    mail = actions.send_ticket_email(ticket, identifier=auth.get("sam", ""),
                                     user_mail=auth.get("mail", ""))
    lead = _pick(session, "ticket_done", [
        "Ik heb een ticket aangemaakt: **{id}**",
        "Je ticket is aangemaakt: **{id}**",
        "Gelukt, het ticket is aangemaakt: **{id}**",
        "Ik heb het ticket voor je geregistreerd: **{id}**",
    ]).format(id=ticket["id"])
    lines = [lead,
             f"Onderwerp: {ticket['subject']}",
             f"Naam: {ticket['naam']}",
             f"Bedrijf: {ticket['bedrijf']}",
             f"Telefoon: {ticket['telefoon']}",
             f"Status: {ticket['status']}"]
    if mail.get("sent"):
        lines.append(f"\nEen bevestiging is gemaild naar **{mail['email_masked']}**.")
    return _direct("ticket", "\n".join(lines), meta={"ticket_id": ticket["id"]})


def _continue_ticket(session: dict, msg: str, low: str) -> dict:
    """Verwerkt het antwoord tijdens een lopende ticket-intake."""
    t = session["ticket"]

    # Fase 1: bevestiging van het voorgestelde onderwerp/omschrijving (optie A).
    if session.get("ticket_confirm"):
        kind = _reply_kind(session, msg, low)
        short = len(msg.split()) <= 3
        if kind == "no" and short:
            session.pop("ticket", None); session.pop("ticket_confirm", None)
            return _direct("info", _pick(session, "no_ticket", _NO_TICKET))
        if kind == "yes":
            session.pop("ticket_confirm", None)
            return _ask_next_or_finish(session)
        if kind == "adjust" and short:
            session.pop("ticket_confirm", None)
            session["ticket_await_subject"] = True
            return _direct("ticket", "Geen probleem. Omschrijf kort waar het ticket over moet gaan.")
        # Een langer antwoord is een correctie of een eigen omschrijving. Het model haalt eruit
        # waar het ticket over moet gaan; correctiewoorden als "nee, dat klopt niet" tellen niet mee.
        session.pop("ticket_confirm", None)
        onderwerp, beschrijving = "", ""
        try:
            onderwerp, beschrijving = lmclient.summarize_ticket([], msg.strip(), correction=True)
        except Exception:
            pass
        t["onderwerp"] = onderwerp or _short_subject(msg.strip())
        t["beschrijving"] = beschrijving or msg.strip()
        if kind in ("no", "adjust"):        # het was een correctie: laat het nieuwe voorstel bevestigen
            session["ticket_confirm"] = True
            return _direct("ticket",
                           f"Aangepast. Ik maak een ticket voor je aan over: **{t['onderwerp']}**.\n"
                           f"Omschrijving: *{t['beschrijving']}*\n\n"
                           f"Klopt dat nu? Typ **ja** om door te gaan.")
        return _ask_next_or_finish(session)

    # Fase 2: de gebruiker omschrijft het onderwerp zelf (na 'pas aan').
    if session.get("ticket_await_subject"):
        session.pop("ticket_await_subject", None)
        t["onderwerp"] = _short_subject(msg.strip())
        t["beschrijving"] = msg.strip()
        return _ask_next_or_finish(session)

    # Fase 3: gewone velden invullen (meestal alleen nog telefoon).
    if low in _CANCEL:
        session.pop("ticket", None)
        return _direct("info", _pick(session, "no_ticket", _NO_TICKET))
    field, _q = _next_ticket_field(t)
    if field == "telefoon" and len(re.sub(r"\D", "", msg)) < 8:
        return _direct("ticket", "Dat lijkt geen volledig telefoonnummer. Typ het met minimaal 8 cijfers, "
                                 "bijvoorbeeld 06-12345678, of typ **stop** om te annuleren.")
    if field:
        t[field] = msg.strip()
    return _ask_next_or_finish(session)
