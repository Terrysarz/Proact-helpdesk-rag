"""
Dunne wrapper rond de LM Studio Python SDK (lmstudio-python).

Alle contact met LM Studio loopt via dit bestand. De SDK praat met de lokale
LM Studio server; er gaat niets naar buiten.

Docs: https://lmstudio.ai/docs/python
"""

from __future__ import annotations
import os
import re
import math
from typing import Iterator, Sequence

import lmstudio as lms

from config import LLM_MODEL, EMBEDDING_MODEL, MAX_TOKENS, SYSTEM_PROMPT

# --- Waar draait LM Studio? --------------------------------------------------
# Leeg  -> lokaal op deze machine (localhost:1234, standaard).
# Ingevuld (bv. "192.168.2.50:1234") -> een ANDERE machine, bijvoorbeeld een
# snelle Mac (Apple Silicon) die LM Studio draait. Zo kun je het rekenwerk naar
# een krachtigere machine verplaatsen zonder de chatbot te verhuizen.
# Zet dit als omgevingsvariabele: export LMSTUDIO_HOST=192.168.2.50:1234
_LMS_HOST = os.getenv("LMSTUDIO_HOST", "").strip()
if _LMS_HOST:
    # Moet vóór het eerste SDK-gebruik; vandaar hier bovenaan de module.
    lms.configure_default_client(_LMS_HOST)

_llm = None
_embedder = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = lms.llm(LLM_MODEL)
    return _llm


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = lms.embedding_model(EMBEDDING_MODEL)
    return _embedder


def embed(text: str) -> list[float]:
    """Zet tekst om naar een embedding-vector (list van floats)."""
    result = get_embedder().embed(text)
    if hasattr(result, "embedding"):
        result = result.embedding
    if result and isinstance(result[0], (list, tuple)):
        result = result[0]
    return [float(x) for x in result]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# Sommige modellen (bv. Qwen3) laten hun redenering zien. Dat willen we NIET aan de
# klant tonen. We zetten de denk-modus uit met '/no_think' én filteren voor de zekerheid
# een eventueel <think>...</think>-blok of intern redeneermarkering alsnog weg.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_REASON_MARKER = re.compile(r".*?SYNTHETIC_REASONING_END_[0-9a-fA-F]+__\s*", re.DOTALL)
_OPEN, _CLOSE = "<think>", "</think>"


def _clean(text: str) -> str:
    text = _REASON_MARKER.sub("", text)
    text = _THINK_BLOCK.sub("", text)
    return text.strip()


def _build_chat(user_prompt: str):
    # '/no_think' zet de redeneer-modus van Qwen3 uit (geen <think>-blok). Harmloos
    # voor modellen die geen denk-modus hebben.
    chat = lms.Chat(SYSTEM_PROMPT)
    chat.add_user_message(user_prompt + "\n\n/no_think")
    return chat


def ask_llm(user_prompt: str) -> str:
    """Niet-streamend antwoord (gebruikt door de CLI)."""
    result = get_llm().respond(_build_chat(user_prompt), config={"maxTokens": MAX_TOKENS})
    return _clean(getattr(result, "content", str(result)))


def ask_llm_stream(user_prompt: str) -> Iterator[str]:
    """
    Streamt het antwoord fragment voor fragment (gebruikt door de web-UI), maar
    verbergt een eventueel <think>...</think>-blok, ook als dat over meerdere
    fragmenten verdeeld binnenkomt.
    """
    stream = get_llm().respond_stream(_build_chat(user_prompt), config={"maxTokens": MAX_TOKENS})
    buf = ""
    in_think = False
    hold = len(_OPEN) - 1   # houd een staartje vast i.v.m. een tag die over fragmenten splitst
    for fragment in stream:
        text = getattr(fragment, "content", "")
        if not text:
            continue
        buf += text
        out = ""
        changed = True
        while changed:
            changed = False
            if not in_think:
                i = buf.find(_OPEN)
                if i != -1:
                    out += buf[:i]
                    buf = buf[i + len(_OPEN):]
                    in_think = True
                    changed = True
            else:
                j = buf.find(_CLOSE)
                if j != -1:
                    buf = buf[j + len(_CLOSE):]
                    in_think = False
                    changed = True
        if not in_think:
            if len(buf) > hold:
                out += buf[:len(buf) - hold]
                buf = buf[len(buf) - hold:]
        else:
            tail = len(_CLOSE) - 1
            buf = buf[-tail:] if len(buf) > tail else buf
        if out:
            yield out
    if buf and not in_think:
        yield buf


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_software_intent(message: str, history: list[dict] | None = None,
                          apps: list[str] | None = None) -> dict | None:
    """Laat het LLM LEZEN wat de gebruiker met werkplek-software wil, i.p.v. trefwoorden te
    raden. Geeft {"intent": "install"|"check"|"none", "app": "<zoals geschreven>",
    "for_self": bool} terug, of None als het niet lukt (dan valt de aanroeper terug op
    de eenvoudige trefwoord-methode)."""
    apps_txt = ", ".join(apps) if apps else "Adobe Reader"
    prompt = (
        "Je bepaalt wat de gebruiker wil op het gebied van werkplek-software.\n"
        f"Beschikbare software: {apps_txt}.\n"
        "Kies precies EEN intent:\n"
        '- "install": de gebruiker wil software laten installeren, aanvragen of toevoegen.\n'
        '- "check": de gebruiker wil CONTROLEREN of er al toegang tot software is, zonder te '
        "installeren.\n"
        '- "remove": de gebruiker wil software laten VERWIJDEREN, deïnstalleren of weghalen.\n'
        '- "none": het gaat NIET over het aanvragen, controleren of verwijderen van software '
        "(bijvoorbeeld een storing, een uitlegvraag, of iets heel anders).\n"
        "Bepaal ook:\n"
        '- app: de genoemde software, exact zoals de gebruiker het schrijft, of "" als er geen '
        "genoemd is.\n"
        "- voor_zichzelf: true als het voor de gebruiker zelf is, false als het (ook) voor "
        "iemand anders is.\n"
        "Antwoord UITSLUITEND met EEN regel JSON, zonder uitleg:\n"
        '{"intent":"install|check|remove|none","app":"...","voor_zichzelf":true}\n\n'
        f'Bericht van de gebruiker: "{message.strip()}"\n\n/no_think'
    )
    try:
        chat = lms.Chat("Je classificeert software-verzoeken en antwoordt alleen met JSON.")
        chat.add_user_message(prompt)
        result = get_llm().respond(chat, config={"maxTokens": 120})
        text = _clean(getattr(result, "content", ""))
    except Exception:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    import json as _json
    try:
        data = _json.loads(m.group(0))
    except Exception:
        return None
    intent = str(data.get("intent", "")).strip().lower()
    if intent not in ("install", "check", "remove", "none"):
        intent = "none"
    app = str(data.get("app", "") or "").strip()
    for_self = data.get("voor_zichzelf", data.get("for_self", True))
    if isinstance(for_self, str):
        for_self = for_self.strip().lower() not in ("false", "nee", "no", "0", "onwaar")
    return {"intent": intent, "app": app, "for_self": bool(for_self)}


_SUBJECT_RE = re.compile(r"ONDERWERP:\s*(.+)", re.IGNORECASE)
_DESC_RE = re.compile(r"OMSCHRIJVING:\s*(.+)", re.IGNORECASE | re.DOTALL)


def summarize_ticket(history: list[dict], request_msg: str = "") -> tuple[str, str]:
    """Laat het LLM het probleem van de gebruiker uit het GESPREK samenvatten tot een
    kort ticketonderwerp + een korte omschrijving. Zo hoeft de klant zich niet te
    herhalen en hoeven we geen trefwoorden te raden. Geeft ("", "") terug bij twijfel,
    zodat de aanroeper kan terugvallen op een eenvoudiger methode."""
    recent = (history or [])[-8:]
    lines = []
    for m in recent:
        who = "Gebruiker" if m.get("role") == "user" else "Assistent"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{who}: {content}")
    transcript = "\n".join(lines) if lines else (request_msg or "")
    if not transcript.strip():
        return "", ""
    prompt = (
        "Hieronder staat een gesprek tussen een gebruiker en een IT-helpdesk. "
        "Vat het PROBLEEM VAN DE GEBRUIKER samen voor een ticket. "
        "Baseer je alleen op het gesprek; verzin niets.\n"
        "Antwoord in het Nederlands, EXACT in dit formaat en zonder extra tekst:\n"
        "ONDERWERP: <korte titel, maximaal 8 woorden>\n"
        "OMSCHRIJVING: <1 of 2 zinnen>\n\n"
        f"Gesprek:\n{transcript}\n\n/no_think"
    )
    try:
        chat = lms.Chat("Je bent een helpdesk-assistent die een ticket samenvat.")
        chat.add_user_message(prompt)
        result = get_llm().respond(chat, config={"maxTokens": 160})
        text = _clean(getattr(result, "content", ""))
    except Exception:
        return "", ""
    onderwerp, omschrijving = "", ""
    mo = _SUBJECT_RE.search(text)
    if mo:
        onderwerp = mo.group(1).strip().splitlines()[0].strip(" *\"'`")
    mb = _DESC_RE.search(text)
    if mb:
        # Alleen de omschrijving zelf; stop bij een eventuele volgende 'ONDERWERP:'-regel.
        omschrijving = re.split(r"ONDERWERP:", mb.group(1), flags=re.IGNORECASE)[0].strip(" *\"'`\n")
    return onderwerp, omschrijving
