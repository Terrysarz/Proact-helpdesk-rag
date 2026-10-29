"""
Laat het taalmodel een vaste boodschap in eigen woorden verwoorden.

De feiten komen altijd uit de code (ticketnummer, e-mailadres, uitkomst van de actie). Het
model mag de zinnen alleen herschrijven, met de voornaam erbij. Het resultaat wordt
gecontroleerd en bij twijfel (te lang, ontbrekend feit, nieuw getal, link, fout of time-out)
wordt de originele tekst gebruikt. Uitzetten kan met LLM_PHRASING=false.
"""

from __future__ import annotations
import re
import concurrent.futures

import config

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_NUM = re.compile(r"\d+")


def _ask(source: str, first: str) -> str:
    import lmstudio as lms
    import lmclient
    naam = (f"De klant heet {first}. Gebruik de voornaam hooguit een keer, en alleen als dat "
            f"natuurlijk klinkt.\n" if first else "")
    prompt = (
        "Zeg de boodschap hieronder opnieuw tegen een klant van de helpdesk, in je eigen woorden, "
        "met een andere zinsbouw dan het origineel, in natuurlijk en vriendelijk Nederlands "
        "(je-vorm). Kopieer de zinnen dus niet.\n"
        "Regels:\n"
        "- Dezelfde inhoud: voeg niets toe en laat geen feit weg. Verzin geen stappen, links, "
        "tijden of beloftes.\n"
        "- Tekst tussen ** ** en tussen ` ` neem je letterlijk over, inclusief die tekens.\n"
        "- Even lang of korter dan het origineel.\n"
        "- Begin niet met een groet.\n"
        "- Gebruik geen gedachtestreepje.\n"
        f"{naam}\nBoodschap:\n{source}\n\nAntwoord alleen met de herschreven tekst.\n\n/no_think"
    )
    chat = lms.Chat("Je bent de Proact Service Desk Assistant. Je herschrijft boodschappen "
                    "zonder feiten te veranderen.")
    chat.add_user_message(prompt)
    result = lmclient.get_llm().respond(chat, config={"maxTokens": 220})
    return lmclient._clean(getattr(result, "content", ""))


def check(source: str, out: str, must=()) -> str | None:
    """Geeft None als de herschrijving deugt, anders de reden van afkeuren."""
    out = out.strip()
    if not (15 <= len(out) <= int(len(source) * 1.5) + 60):
        return "lengte"
    low = out.lower()
    if any(x in low for x in ("http", "www.", "—", "<think", "synthetic")):
        return "verboden tekst"
    for span in _BOLD.findall(source) + _CODE.findall(source):
        if span not in out:
            return f"feit ontbreekt: {span}"
    if out.count("`") > source.count("`"):
        return "backticks"
    for m in must:
        if m.lower() not in low:
            return f"verplicht ontbreekt: {m}"
    if not set(_NUM.findall(out)) <= set(_NUM.findall(source)):
        return "nieuw getal"
    if re.search(r"\b(u|uw)\b", low):
        return "u-vorm"
    ends = lambda t: len(re.findall(r"[.!?](?:\s|$)", t))
    if ends(out) > ends(source) + 1:
        return "te veel zinnen"
    return None


def rephrase(source: str, first: str = "", must=()) -> str:
    """Geeft de herschreven tekst, of `source` zelf als dat niet kan of niet mag."""
    if not config.LLM_PHRASING:
        return source
    try:
        out = _POOL.submit(_ask, source, first).result(timeout=config.LLM_PHRASING_TIMEOUT)
    except Exception as e:
        print(f"[phrasing] terugval: {type(e).__name__}", flush=True)
        return source
    reason = check(source, out, must)
    if reason:
        print(f"[phrasing] terugval: {reason}", flush=True)
        return source
    return out.strip()
