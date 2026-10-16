"""
RAG-kern + dispatcher (v3: met gespreksgeheugen).

prepare() bepaalt per bericht wat er moet gebeuren:
  - greeting / actie / onbekende-vraag  -> direct antwoord ZONDER het trage LLM
  - echte kennisvraag                   -> RAG-plan dat de web-UI streamt

Nieuw: eerdere berichten uit de sessie worden meegenomen, zodat vervolgvragen
("en als dat niet lukt?") de juiste context hebben.
"""

from __future__ import annotations
import json
import re
from functools import lru_cache

from config import INDEX_PATH, TOP_K, MIN_SCORE, HISTORY_MAX
from lmclient import embed, cosine_similarity, ask_llm
import config
import router
import actions
import links
import ad

_AFFIRMATIVE = {"ja", "graag", "ok", "oke", "oké", "yes", "jep", "jawel", "doe maar", "ja graag", "prima"}
_NEGATIVE = {"nee", "niet", "laat maar", "hoeft niet", "nee bedankt", "nee hoor"}


@lru_cache(maxsize=1)
def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"{INDEX_PATH.name} niet gevonden. Draai eerst: python src/ingest.py"
        )
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def retrieve(question: str, top_k: int = TOP_K) -> list[dict]:
    index = load_index()
    q_vec = embed(question)
    scored = [(cosine_similarity(q_vec, rec["embedding"]), rec) for rec in index]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {"score": round(s, 3), "source": r["source"], "text": r["text"]}
        for s, r in scored[:top_k]
    ]


def build_context(hits: list[dict]) -> str:
    return "\n\n".join(
        f"[Bron {n}: {h['source']}]\n{h['text']}" for n, h in enumerate(hits, start=1)
    )


def _history_block(history: list[dict]) -> str:
    """Laatste paar berichten als korte tekst, voor context bij vervolgvragen."""
    if not history:
        return ""
    recent = history[-4:]
    lines = [("Gebruiker" if m["role"] == "user" else "Assistent") + ": " + m["content"]
             for m in recent]
    return "Eerder in het gesprek:\n" + "\n".join(lines) + "\n\n"


def _last_user_message(history: list[dict]) -> str:
    for m in reversed(history):
        if m["role"] == "user":
            return m["content"]
    return ""


# --- Directe (niet-LLM) antwoorden ------------------------------------------

def _direct(kind: str, text: str, sources=None, meta=None) -> dict:
    return {"mode": "direct", "kind": kind, "text": text, "sources": sources or [], "meta": meta or {}}


def _do_reset(identifier: str) -> dict:
    r = actions.request_password_reset(identifier)

    # Account niet gevonden (Entra ID of Active Directory).
    if r.get("found") is False:
        return _direct(
            "reset",
            f"Ik kon het account **{r['email_masked']}** niet vinden. Controleer de "
            f"gebruikersnaam of het e-mailadres, of maak een ticket aan.",
        )

    # Active Directory (on-prem): ontgrendelen + tijdelijk wachtwoord + geforceerde wijziging.
    if r.get("method") == "ad":
        parts = []
        if r.get("unlocked"):
            parts.append("Je account is ontgrendeld.")
        if r["sent"]:
            parts.append(f"Er is een tijdelijk wachtwoord ingesteld en gemaild naar "
                         f"**{r['email_masked']}** — te wijzigen bij de volgende aanmelding.")
        else:
            parts.append("Er is een tijdelijk wachtwoord ingesteld (te wijzigen bij de volgende "
                         "aanmelding). Neem contact op met de Service Desk voor de inloggegevens.")
        text = (" ".join(parts) +
                "\n\nOm veiligheidsredenen wordt het wachtwoord nooit in de chat getoond.")
        return _direct("reset", text, meta={"email_masked": r["email_masked"]})

    extra = " Je actieve sessies zijn uit voorzorg beëindigd." if r.get("sessions_revoked") else ""
    if r["sent"] and r.get("method") == "graph":
        lead = (f"De wachtwoordreset is gestart voor **{r['email_masked']}**.{extra} "
                f"Er is een reset-link gemaild.")
    elif r["sent"]:
        lead = f"Er is een beveiligde reset-link **gemaild** naar **{r['email_masked']}**."
    elif r["simulated"]:
        lead = (f"Er is een beveiligde reset-link klaargezet voor **{r['email_masked']}** "
                f"(gesimuleerd — e-mail/Graph is niet geconfigureerd).")
    else:
        lead = (f"Het versturen naar **{r['email_masked']}** is mislukt; probeer het later "
                f"opnieuw of maak een ticket.")
    text = (
        f"{lead}\nDe link is {r['valid_minutes']} minuten geldig.\n\n"
        "Om veiligheidsredenen wordt er nooit een wachtwoord verstuurd — alleen een reset-link."
    )
    return _direct("reset", text, meta={"email_masked": r["email_masked"], "sent": r["sent"]})


def _handle_reset(session: dict, msg: str) -> dict:
    """Autorisatie rond een wachtwoordreset.
    Met AD-login: je moet ingelogd zijn en mag alleen je EIGEN account resetten
    (agents mogen anderen). Zonder AD-login: het oude gedrag."""
    auth = session.get("auth")
    ident = router.extract_identifier(msg)

    if ad.enabled():
        if not auth:
            return _direct("reset_ask",
                           "Log eerst in (knop rechtsboven) om een wachtwoordreset te starten.")
        self_sam = (auth.get("sam") or "").lower()
        target = ident or self_sam
        tgt_sam = target.lower().split("@")[0]
        if tgt_sam and tgt_sam != self_sam and not auth.get("is_agent"):
            return _direct("reset",
                           "Je kunt alleen je **eigen** wachtwoord resetten. "
                           "Vraag een Service Desk-medewerker voor een ander account.")
        return _do_reset(target)

    # Geen AD-login beschikbaar: oude gedrag.
    if ident:
        return _do_reset(ident)
    session["pending"] = "password_reset"
    return _direct("reset_ask",
                   "Ik kan een wachtwoordreset voor je starten. Voor welk account? "
                   "Geef je gebruikersnaam of e-mailadres.")


# --- Zelfservice software-uitrol --------------------------------------------

def _extract_app(msg: str) -> str | None:
    """Herkent welke applicatie wordt gevraagd op basis van de aliassen uit config.
    Langste alias eerst, zodat 'adobe acrobat reader' wint van 'adobe'."""
    t = msg.lower()
    for alias in sorted(config.APP_GROUPS, key=len, reverse=True):
        if alias in t:
            return alias
    return None


def _do_software(session: dict, app_key: str) -> dict:
    auth = session.get("auth") or {}
    identifier = auth.get("sam") or auth.get("upn") or ""
    if ad.enabled() and not identifier:
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software aan te vragen.")
    r = actions.request_software(identifier, app_key)
    name = r.get("app_name") or app_key

    if r.get("error") == "unknown_app":
        return _direct("software",
                       f"Die software ken ik niet. Beschikbaar is: {', '.join(config.APP_DISPLAY)}.")
    if r.get("found") is False:
        return _direct("software",
                       "Ik kon je account niet vinden om de aanvraag te verwerken. "
                       "Log opnieuw in of maak een ticket aan.")
    if r.get("error") == "group_missing":
        return _direct("software",
                       f"De automatische uitrol voor **{name}** is nog niet ingericht. "
                       f"Ik kan er een ticket voor aanmaken voor de Service Desk.")
    if r.get("error"):
        return _direct("software",
                       f"Er ging iets mis bij het aanvragen van **{name}**. Probeer het later "
                       f"opnieuw of maak een ticket aan.")
    if r.get("already"):
        return _direct("software",
                       f"**{name}** staat al voor je klaar. Het verschijnt na je volgende "
                       f"aanmelding; als je het nog niet ziet, meld je dan opnieuw aan.",
                       meta={"app": name})
    if r.get("method") == "ad" and r.get("added"):
        return _direct("software",
                       f"Je aanvraag voor **{name}** is verwerkt. De installatie start "
                       f"automatisch bij je volgende aanmelding (geen licentie nodig). "
                       f"Zie je het niet meteen? Meld je dan opnieuw aan.",
                       meta={"app": name})
    # Geen AD beschikbaar: nette simulatie.
    return _direct("software",
                   f"Je aanvraag voor **{name}** is genoteerd (demo-modus: AD niet gekoppeld).",
                   meta={"app": name})


def _handle_software(session: dict, msg: str) -> dict:
    if ad.enabled() and not session.get("auth"):
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software aan te vragen.")
    app = _extract_app(msg)
    if not app:
        session["pending"] = "software_request"
        return _direct("software_ask",
                       f"Welke software wil je aanvragen? Beschikbaar is: "
                       f"{', '.join(config.APP_DISPLAY)}.")
    return _do_software(session, app)


def _do_ticket(subject: str, details: str = "") -> dict:
    ticket = actions.create_ticket(subject=subject, details=details)
    text = (
        f"Ik heb een ticket aangemaakt: **{ticket['id']}**\n"
        f"Onderwerp: {ticket['subject']}\n"
        f"Status: {ticket['status']}"
    )
    return _direct("ticket", text, meta={"ticket_id": ticket["id"]})


# Een "maak (dan/even) een ticket (aan) (voor/over)"-frase vooraan strippen,
# inclusief vulwoorden, om het eigenlijke onderwerp over te houden.
_TICKET_PREFIX_RE = re.compile(
    r"(?i)^(?:(?:kun je|kan je|zou je|graag|ik wil|ik zou graag|maak|open|start|regel|"
    r"even|dan|maar|toch|alsjeblieft|aub|ook|nog)\s+)*"
    r"(?:een |de |het )?ticket(?:\s+(?:aanmaken|aan maken|maken|aan))?(?:\s+(?:voor|over))?\s*"
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


def _ticket_subject(msg: str, history: list[dict]) -> str:
    """Bepaalt een zinnig ticketonderwerp. Is het bericht een kaal 'maak een ticket'
    of een terugverwijzing, pak dan het laatste onderwerp uit het gesprek."""
    low = msg.strip().lower()
    problem = _topic_problem(history)
    refers_back = any(w in low for w in _REFERS_BACK)
    m = _TICKET_PREFIX_RE.match(low)
    remainder = msg.strip()[m.end():].strip() if m else msg.strip()
    rem_low = remainder.lower().strip(" .,-!?")
    if (refers_back or rem_low in _VAGUE or len(rem_low) < 4) and problem:
        return problem
    if len(remainder) >= 4:
        return remainder
    return problem or msg


# --- Ticket-intake: eerst info verzamelen, dan pas aanmaken ------------------

_TICKET_FIELDS = [
    ("onderwerp", "Waar gaat het ticket over? Omschrijf kort het probleem."),
    ("naam", "Wat is je naam?"),
    ("bedrijf", "Bij welk bedrijf of welke klantomgeving hoor je?"),
]
_CANCEL = {"annuleer", "annuleren", "stop", "laat maar", "laat maar zitten", "laat zitten",
           "cancel", "niet meer", "hoeft niet", "nee", "neen"}


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


def _next_ticket_field(t: dict):
    for field, question in _TICKET_FIELDS:
        if not t.get(field):
            return field, question
    return None, None


def _begin_ticket(session: dict, onderwerp: str) -> dict:
    """Start de intake: zet de staat en stel de eerste ontbrekende vraag.
    Is de gebruiker ingelogd, dan worden naam en bedrijf automatisch overgenomen."""
    auth = session.get("auth") or {}
    t = {"onderwerp": onderwerp or "", "beschrijving": onderwerp or "",
         "naam": auth.get("name", ""), "bedrijf": auth.get("company", "")}
    session["ticket"] = t
    field, question = _next_ticket_field(t)
    if field is None:
        return _finish_ticket(session)   # alles al bekend (bv. ingelogd) -> meteen aanmaken
    if onderwerp:
        return _direct("ticket",
                       f"Ik ga een ticket voor je aanmaken. Ik noteer als onderwerp: "
                       f"**{onderwerp}**.\n\n{question}")
    return _direct("ticket", f"Prima, ik maak een ticket voor je aan.\n\n{question}")


def _finish_ticket(session: dict) -> dict:
    t = session.pop("ticket")
    details = (f"Beschrijving: {t['beschrijving'] or t['onderwerp']}\n"
               f"Naam: {t['naam']}\nBedrijf: {t['bedrijf']}")
    ticket = actions.create_ticket(subject=t["onderwerp"], details=details)
    text = (f"Ik heb een ticket aangemaakt: **{ticket['id']}**\n"
            f"Onderwerp: {ticket['subject']}\n"
            f"Naam: {t['naam']}\n"
            f"Bedrijf: {t['bedrijf']}\n"
            f"Status: {ticket['status']}")
    return _direct("ticket", text, meta={"ticket_id": ticket["id"]})


def _continue_ticket(session: dict, msg: str, low: str) -> dict:
    """Verwerkt het antwoord op de lopende intake-vraag."""
    if low in _CANCEL:
        session.pop("ticket", None)
        return _direct("info", "Oké, ik heb geen ticket aangemaakt. Kan ik iets anders doen?")
    t = session["ticket"]
    field, _q = _next_ticket_field(t)
    if field:
        t[field] = msg.strip()
        if field == "onderwerp":
            t["beschrijving"] = msg.strip()
    nxt_field, nxt_q = _next_ticket_field(t)
    if nxt_field:
        return _direct("ticket", nxt_q)
    return _finish_ticket(session)


# --- Hoofddispatcher --------------------------------------------------------

def prepare(message: str, session: dict | None = None) -> dict:
    session = session if session is not None else {}
    history = session.get("history", [])
    msg = message.strip()
    low = msg.lower().strip("!?. ")

    # 0) Lopende ticket-intake heeft voorrang: elk bericht is een antwoord op de vraag.
    if session.get("ticket") is not None:
        return _continue_ticket(session, msg, low)

    # 1) Lopende meerstaps-flow.
    pending = session.get("pending")
    if pending == "password_reset":
        ident = router.extract_identifier(msg)
        session["pending"] = None
        if ident:
            return _do_reset(ident)
    elif pending == "offer_ticket":
        session["pending"] = None
        if low in _AFFIRMATIVE:
            return _begin_ticket(session, session.get("last_unanswered", ""))
        if low in _NEGATIVE:
            return _direct("info", "Oké, ik heb geen ticket aangemaakt. Kan ik iets anders doen?")
    elif pending == "software_request":
        session["pending"] = None
        if low in _CANCEL or low in _NEGATIVE:
            return _direct("info", "Oké, ik heb geen software aangevraagd. Kan ik iets anders doen?")
        app = _extract_app(msg)
        if app:
            return _do_software(session, app)
        session["pending"] = "software_request"
        return _direct("software_ask",
                       f"Die software herken ik niet. Kies uit: {', '.join(config.APP_DISPLAY)}.")

    # 2) Intent.
    intent = router.classify(msg)

    if intent == "greeting":
        return _direct(
            "greeting",
            "Hoi! Ik ben de Proact Service Desk Assistant. Vraag me iets over wachtwoorden, "
            "MFA, VPN, licenties, printers of onboarding — of laat me een wachtwoordreset "
            "starten of een ticket aanmaken.",
        )

    if intent == "software_request":
        return _handle_software(session, msg)

    if intent == "password_reset":
        return _handle_reset(session, msg)

    if intent == "create_ticket":
        return _begin_ticket(session, _prefill_subject(msg, history))

    # 3) Kennisvraag -> RAG (met gespreksgeheugen).
    last_user = _last_user_message(history)
    retrieval_query = f"{last_user} {msg}".strip() if last_user else msg
    hits = retrieve(retrieval_query)
    if not hits or hits[0]["score"] < MIN_SCORE:
        session["pending"] = "offer_ticket"
        session["last_unanswered"] = msg
        return _direct(
            "notfound",
            "Dat staat niet in de kennisbank. Wil je dat ik hiervoor een ticket aanmaak "
            "voor de Service Desk? (ja / nee)",
        )

    context = build_context(hits)
    user_prompt = (
        f"{_history_block(history)}"
        f"Context uit de kennisbank:\n\n{context}\n\n"
        f"Huidige vraag: {msg}"
    )
    sources = sorted({h["source"] for h in hits})
    hit_links = links.for_sources([h["source"] for h in hits])   # officiële Microsoft-link(s)
    return {"mode": "rag", "kind": "answer", "user_prompt": user_prompt,
            "sources": sources, "links": hit_links}


def remember(session: dict, role: str, content: str) -> None:
    """Voegt een bericht toe aan het gespreksgeheugen en houdt het kort."""
    history = session.setdefault("history", [])
    history.append({"role": role, "content": content})
    if len(history) > HISTORY_MAX:
        del history[: len(history) - HISTORY_MAX]


def answer_once(message: str, session: dict | None = None) -> dict:
    """Niet-streamende variant (CLI)."""
    session = session if session is not None else {}
    plan = prepare(message, session)
    if plan["mode"] == "direct":
        text = plan["text"]
    else:
        text = ask_llm(plan["user_prompt"])
    remember(session, "user", message)
    remember(session, "assistant", text)
    return {"text": text, "sources": plan["sources"]}
