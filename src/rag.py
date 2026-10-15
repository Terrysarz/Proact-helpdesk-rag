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
import router
import actions
import links

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
    if r["sent"]:
        lead = f"Er is een beveiligde reset-link **gemaild** naar **{r['email_masked']}**."
    elif r["simulated"]:
        lead = (f"Er is een beveiligde reset-link klaargezet voor **{r['email_masked']}** "
                f"(gesimuleerd — e-mail is niet geconfigureerd).")
    else:
        lead = (f"Het versturen naar **{r['email_masked']}** is mislukt; probeer het later "
                f"opnieuw of maak een ticket.")
    text = (
        f"{lead}\nDe link is {r['valid_minutes']} minuten geldig.\n\n"
        "Om veiligheidsredenen wordt er nooit een wachtwoord verstuurd — alleen een reset-link."
    )
    return _direct("reset", text, meta={"email_masked": r["email_masked"], "sent": r["sent"]})


def _do_ticket(subject: str, details: str = "") -> dict:
    ticket = actions.create_ticket(subject=subject, details=details)
    text = (
        f"Ik heb een ticket aangemaakt: **{ticket['id']}**\n"
        f"Onderwerp: {ticket['subject']}\n"
        f"Status: {ticket['status']}"
    )
    return _direct("ticket", text, meta={"ticket_id": ticket["id"]})


# Strip een "maak een ticket (voor/over)"-frase om het eigenlijke onderwerp over te houden.
_TICKET_PREFIX_RE = re.compile(
    r"(?i)^(kun je |kan je |zou je |graag |ik wil |ik zou graag |maak |open |start |regel )*"
    r"(een )?ticket( aanmaken| aan maken| maken| aan)?( voor| over)?\s*"
)
_REFERS_BACK = (
    "net ", "zojuist", "hiervoor", "eerder", "die melding", "dat probleem", "dit probleem",
    "nog steeds", "nogsteeds", "net vroeg", "net vrog", "die je net", "waar we het",
)


def _ticket_subject(msg: str, history: list[dict]) -> str:
    """Bepaalt een zinnig ticketonderwerp: verwijst het bericht terug, pak dan het
    vorige probleem uit het gesprek i.p.v. de letterlijke 'maak een ticket'-zin."""
    low = msg.lower()
    refers_back = any(w in low for w in _REFERS_BACK)
    last_problem = ""
    for m in reversed(history):
        if m["role"] == "user" and router.classify(m["content"]) == "question":
            last_problem = m["content"]
            break
    if refers_back and last_problem:
        return last_problem
    cleaned = _TICKET_PREFIX_RE.sub("", msg).strip()
    if len(cleaned) >= 5:
        return cleaned
    return last_problem or msg


# --- Hoofddispatcher --------------------------------------------------------

def prepare(message: str, session: dict | None = None) -> dict:
    session = session if session is not None else {}
    history = session.get("history", [])
    msg = message.strip()
    low = msg.lower().strip("!?. ")

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
            return _do_ticket(session.get("last_unanswered", "Vraag via de Service Desk Assistant"))
        if low in _NEGATIVE:
            return _direct("info", "Oké, ik heb geen ticket aangemaakt. Kan ik iets anders doen?")

    # 2) Intent.
    intent = router.classify(msg)

    if intent == "greeting":
        return _direct(
            "greeting",
            "Hoi! Ik ben de Proact Service Desk Assistant. Vraag me iets over wachtwoorden, "
            "MFA, VPN, licenties, printers of onboarding — of laat me een wachtwoordreset "
            "starten of een ticket aanmaken.",
        )

    if intent == "password_reset":
        ident = router.extract_identifier(msg)
        if ident:
            return _do_reset(ident)
        session["pending"] = "password_reset"
        return _direct(
            "reset_ask",
            "Ik kan een wachtwoordreset voor je starten. Voor welk account? "
            "Geef je gebruikersnaam of e-mailadres.",
        )

    if intent == "create_ticket":
        return _do_ticket(subject=_ticket_subject(msg, history), details=msg)

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
