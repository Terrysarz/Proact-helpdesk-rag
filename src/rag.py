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

import config
import links
import lmclient
import router
from config import INDEX_PATH, TOP_K, MIN_SCORE, SURE_SCORE, HISTORY_MAX
from lmclient import embed, cosine_similarity, ask_llm
from flow_common import _CANCEL, _NEGATIVE, _direct, _first_name, _pick, _reply_kind
from flow_account import _PW_QUESTION_WORDS, _do_reset, _handle_reset, _offer_reset
from flow_software import (_do_software, _do_software_remove, _do_software_status, _extract_app,
                           _handle_software, _handle_software_status, _route_software)
from flow_ticket import _NO_TICKET, _begin_ticket, _continue_ticket


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

_DAYPARTS = ("goedemorgen", "goedemiddag", "goedenavond")


def _greeting(session: dict, msg: str) -> dict:
    """Korte, persoonlijke begroeting. Wat de bot kan staat al in de welkomsttekst bovenin
    de pagina, dus dat herhalen we hier niet. We spiegelen de groet van de gebruiker."""
    low = msg.lower()
    word = next((w for w in _DAYPARTS if w in low), "hoi")
    first = _first_name(session)
    hello = f"{word.capitalize()} {first}!" if first else f"{word.capitalize()}!"
    count = session.get("greeted", 0)
    session["greeted"] = count + 1
    tail = ("Waar kan ik je mee helpen?" if count == 0 else
            _pick(session, "greet_again", ["Ik ben er nog. Waarmee kan ik je helpen?",
                                           "Zeg het maar, waar kan ik mee helpen?",
                                           "Ik luister. Wat kan ik voor je doen?"]))
    return _direct("greeting", f"{hello} {tail}")


_FOLLOW_UP_WORDS = {"dat", "dit", "die", "deze", "daar", "hier", "ervan", "erover", "hierover",
                    "daarvan", "ook", "nog", "ervoor", "hiervoor"}


def _confident_links(hits: list[dict]) -> list[dict]:
    """Alleen een 'Meer info'-link als de bovenste hit duidelijk beter is dan een hit uit een
    ander document. Liggen ze dicht bij elkaar, dan is de link een gok en laten we hem weg."""
    top = hits[0]
    rival = next((h for h in hits[1:] if h["source"] != top["source"]), None)
    if rival and top["score"] - rival["score"] < 0.04:
        return []
    return links.for_sources([top["source"]])


def _route_delegation(session: dict, msg: str, history: list[dict]):
    """Een kort bericht als "kan jij het voor me doen" verwijst naar het gesprek. Het model leest
    wat bedoeld is; bij twijfel (of een fout) gaat het bericht gewoon naar de kennisbank."""
    try:
        what = lmclient.parse_delegation(msg, history)
    except Exception:
        what = None
    if what == "password_reset":
        return _offer_reset(session, msg)
    if what == "ticket":
        return _begin_ticket(session, history, msg)
    if what == "software":
        return _route_software(session, msg, history)
    return None


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
            return _do_reset(ident, session)
    elif pending == "reset_confirm":
        session["pending"] = None
        kind = _reply_kind(session, msg, low)
        if kind == "yes":
            return _handle_reset(session, session.pop("reset_target", ""))
        if kind == "no":
            return _direct("info", _pick(session, "no_reset", [
                "Oké, ik heb niets gewijzigd. Kan ik iets anders doen?",
                "Prima, ik laat je wachtwoord zoals het is. Waar kan ik verder mee helpen?"]))
    elif pending == "offer_ticket":
        session["pending"] = None
        kind = _reply_kind(session, msg, low)
        if kind == "yes":
            return _begin_ticket(session, history, session.get("last_unanswered", ""))
        if kind == "no":
            return _direct("info", _pick(session, "no_ticket", _NO_TICKET))
    elif pending == "software_request":
        session["pending"] = None
        if low in _CANCEL or low in _NEGATIVE:
            session.pop("pending_app", None)
            return _direct("info", "Oké, ik heb geen software aangevraagd. Kan ik iets anders doen?")
        app = _extract_app(msg)
        if not app and session.get("pending_app"):     # antwoord op een eerder installeer-aanbod
            kind = _reply_kind(session, msg, low)
            if kind == "yes":
                app = session.get("pending_app")
            elif kind == "no":
                session.pop("pending_app", None)
                return _direct("info", "Oké, ik heb geen software aangevraagd. Kan ik iets anders doen?")
        if app:
            session.pop("pending_app", None)
            return _do_software(session, app)
        session["pending"] = "software_request"
        return _direct("software_ask",
                       f"Die software herken ik niet. Kies uit: {', '.join(config.APP_DISPLAY)}.")
    elif pending == "software_status":
        session["pending"] = None
        if low in _CANCEL or low in _NEGATIVE:
            return _direct("info", "Oké. Kan ik iets anders doen?")
        app = _extract_app(msg)
        if app:
            return _do_software_status(session, app)
        session["pending"] = "software_status"
        return _direct("software_ask",
                       f"Die software herken ik niet. Kies uit: {', '.join(config.APP_DISPLAY)}.")
    elif pending == "software_remove":
        session["pending"] = None
        if low in _CANCEL or low in _NEGATIVE:
            return _direct("info", "Oké, ik heb niets verwijderd. Kan ik iets anders doen?")
        app = _extract_app(msg)
        if app:
            return _do_software_remove(session, app)
        session["pending"] = "software_remove"
        return _direct("software_ask",
                       f"Die software herken ik niet. Kies uit: {', '.join(config.APP_DISPLAY)}.")

    # 2) Software/toegang: laat het model de bedoeling lezen (betrouwbaarder dan trefwoorden).
    if router.software_topic(msg):
        routed = _route_software(session, msg, history)
        if routed is not None:
            return routed

    # 3) Intent (trefwoorden) voor de overige gevallen.
    intent = router.classify(msg)

    if intent == "greeting":
        return _greeting(session, msg)

    first = _first_name(session)
    nm = f", {first}" if first else ""
    if intent == "noise":
        return _direct("info", _pick(session, "noise", [
            "Ik heb je bericht niet helemaal begrepen. Kun je het anders zeggen?",
            "Dat kwam niet helemaal bij me aan. Waar kan ik je mee helpen?"]))
    if intent == "thanks":
        return _direct("info", _pick(session, "thanks", [
            f"Graag gedaan{nm}!", f"Fijn dat ik kon helpen{nm}. Laat het weten als er nog iets is.",
            "Geen probleem! Zeg het maar als je nog iets nodig hebt."]))
    if intent == "bye":
        return _direct("info", _pick(session, "bye", [
            f"Tot ziens{nm}!", f"Fijne dag{nm}. Tot de volgende keer!", "Doei! Tot later."]))

    if intent == "software_status":
        return _handle_software_status(session, msg)

    if intent == "software_request":
        return _handle_software(session, msg)

    if intent == "password_reset":
        return _handle_reset(session, msg)

    if intent == "password_forgot":
        return _offer_reset(session, msg)

    if intent == "create_ticket":
        return _begin_ticket(session, history, msg)

    # Een kort verzoek dat naar het gesprek verwijst ("kan jij het voor me doen")?
    if intent == "question" and history and router.is_delegation(msg):
        routed = _route_delegation(session, msg, history)
        if routed is not None:
            return routed

    # 3) Kennisvraag -> RAG (met gespreksgeheugen). Het vorige bericht gaat alleen mee in de
    #    zoekopdracht bij een kort of terugverwijzend bericht, anders trekt het oude onderwerp mee.
    last_user = _last_user_message(history)
    words = set(re.findall(r"\w+", msg.lower()))
    follow_up = len(words) <= 5 or bool(words & _FOLLOW_UP_WORDS)
    retrieval_query = f"{last_user} {msg}".strip() if (last_user and follow_up) else msg
    hits = retrieve(retrieval_query)
    below = not hits or hits[0]["score"] < MIN_SCORE
    gray = not below and hits[0]["score"] < SURE_SCORE
    it_verdict = None                      # True = IT-vraag, False = niet over IT, None = onbekend
    if (below or gray) and config.LLM_RELEVANCE:
        try:
            it_verdict = lmclient.is_it_question(msg)
        except Exception:
            it_verdict = None
    off_topic = below or (gray and it_verdict is False)
    if off_topic and it_verdict is False:
        # Geen IT-vraag: geen ticketaanbod, maar zeggen waar de bot wel voor is.
        return _direct("notfound", _pick(session, "offtopic", [
            "Daar kan ik je niet mee helpen. Ik help met IT-vragen, zoals wachtwoord, MFA, VPN, "
            "printers of Microsoft 365.",
            "Dat valt buiten wat ik kan. Voor IT-vragen (wachtwoord, MFA, VPN, licenties, printers) "
            "ben ik er wel."]))
    if off_topic:
        session["pending"] = "offer_ticket"
        session["last_unanswered"] = msg
        return _direct("notfound", _pick(session, "notfound", [
            "Dat staat niet in de kennisbank. Wil je dat ik hiervoor een ticket aanmaak "
            "voor de Service Desk? (ja / nee)",
            "Hier heb ik geen antwoord op in de kennisbank. Zal ik er een ticket voor aanmaken "
            "bij de Service Desk? (ja / nee)",
            "Dit kan ik niet terugvinden in de kennisbank. Wil je dat de Service Desk ernaar "
            "kijkt? Dan maak ik een ticket aan. (ja / nee)",
        ]))

    context = build_context(hits)
    user_prompt = (
        f"{_history_block(history)}"
        f"Context uit de kennisbank:\n\n{context}\n\n"
        f"Huidige vraag: {msg}\n\n"
        + (f"De klant heet {_first_name(session)}. Gebruik de voornaam hooguit af en toe, niet in elk antwoord.\n"
           if _first_name(session) else "") +
        "Beantwoord de huidige vraag en speel in op wat de klant hierboven al heeft verteld. "
        "Herhaal geen stappen die de klant al heeft gedaan of die je eerder al noemde, en "
        "vraag niet te controleren wat de klant net al heeft gemeld."
    )
    sources = sorted({h["source"] for h in hits})
    hit_links = _confident_links(hits)       # officiële Microsoft-link, alleen bij een duidelijke hit
    followup = ""
    low_msg = msg.lower()
    if (hits[0]["source"] == "01-wachtwoord-en-mfa.md" and "wachtwoord" in low_msg
            and any(w in low_msg for w in _PW_QUESTION_WORDS)):
        # Het antwoord legt uit hoe het zelf kan; de bot kan het ook zelf doen. Bied dat aan.
        session["pending"] = "reset_confirm"
        session["reset_target"] = ""
        followup = ("Wil je dat ik het nu voor je doe? Dan reset ik je wachtwoord en mail ik een "
                    "tijdelijk wachtwoord. (ja / nee)")
    return {"mode": "rag", "kind": "answer", "user_prompt": user_prompt,
            "sources": sources, "links": hit_links, "followup": followup}


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
