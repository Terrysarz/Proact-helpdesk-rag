"""
Gedeelde hulpjes voor de gespreksflows: antwoordwoorden, variatie, voornaam en het lezen van
ja/nee-antwoorden.
"""

from __future__ import annotations
import config
import lmclient
import responder
import router


_AFFIRMATIVE = {"ja", "graag", "ok", "oke", "oké", "yes", "jep", "jawel", "doe maar", "ja graag", "prima"}


_NEGATIVE = {"nee", "niet", "laat maar", "hoeft niet", "nee bedankt", "nee hoor"}


_CANCEL = {"annuleer", "annuleren", "stop", "laat maar", "laat maar zitten", "laat zitten",
           "cancel", "niet meer", "hoeft niet", "nee", "neen"}


# De gebruiker wil het voorgestelde onderwerp/omschrijving aanpassen (optie A).
_ADJUST = {"pas aan", "aanpassen", "pas het aan", "nee pas aan", "corrigeren", "anders",
           "klopt niet", "niet goed", "verander"}


def _first_name(session: dict) -> str:
    """Voornaam van de ingelogde gebruiker ('' als niemand is ingelogd)."""
    auth = session.get("auth") or {}
    first = (auth.get("first") or "").strip()
    if not first:
        name = (auth.get("name") or "").strip()
        first = name.split()[0] if name else ""
    return first


def _direct(kind: str, text: str, sources=None, meta=None) -> dict:
    return {"mode": "direct", "kind": kind, "text": text, "sources": sources or [], "meta": meta or {}}


def _pick(session: dict, key: str, options: list[str]) -> str:
    """Wisselt tussen een paar varianten, zodat dezelfde situatie niet steeds dezelfde zin geeft."""
    counts = session.setdefault("variant", {})
    n = counts.get(key, 0)
    counts[key] = n + 1
    return options[n % len(options)]


def _phrased(fn):
    """Laat het model de uitkomst van een softwareactie in eigen woorden zeggen (met voornaam).
    De feiten staan vast in de tekst; responder.rephrase controleert of ze bewaard zijn en geeft
    bij twijfel de originele tekst terug."""
    def wrapper(session, *args, **kwargs):
        plan = fn(session, *args, **kwargs)
        if plan.get("kind") == "software" and (plan.get("meta") or {}).get("app"):
            plan["text"] = responder.rephrase(plan["text"], _first_name(session))
        return plan
    return wrapper


def _last_assistant(history: list[dict]) -> str:
    for m in reversed(history):
        if m["role"] == "assistant":
            return m["content"]
    return ""


def _reply_kind(session: dict, msg: str, low: str) -> str:
    """Hoe reageert de gebruiker op de vorige vraag: yes / no / adjust / other.
    Eerst de snelle woordenlijst; bij een langer of vrij antwoord leest het model mee."""
    if low in _AFFIRMATIVE:
        return "yes"
    if low in _ADJUST:
        return "adjust"
    if low in _CANCEL or low in _NEGATIVE:
        return "no"
    if router.is_noise(msg):
        return "other"
    if not config.LLM_READ_REPLIES or len(msg.split()) > 12:
        return "other"
    try:
        kind = lmclient.parse_reply(msg, _last_assistant(session.get("history", [])))
    except Exception:
        kind = None
    return kind or "other"
