"""
Zelfservice voor software: aanvragen, controleren en verwijderen via een AD-groep.
"""

from __future__ import annotations
import actions
import ad
import config
import lmclient
import router
from flow_common import _direct, _phrased


# --- Zelfservice software-uitrol --------------------------------------------

def _extract_app(msg: str) -> str | None:
    """Herkent welke applicatie wordt gevraagd op basis van de aliassen uit config.
    Langste alias eerst, zodat 'adobe acrobat reader' wint van 'adobe'."""
    t = msg.lower()
    for alias in sorted(config.APP_GROUPS, key=len, reverse=True):
        if alias in t:
            return alias
    return None


def _software_problem(r: dict, name: str, *, no_account: str, missing: str, error: str):
    """Foutafhandeling die de drie softwareflows delen. Geeft een antwoord, of None als er geen fout is."""
    if r.get("error") == "unknown_app":
        return _direct("software",
                       f"Die software ken ik niet. Beschikbaar is: {', '.join(config.APP_DISPLAY)}.")
    if r.get("found") is False:
        return _direct("software", no_account)
    if r.get("error") == "group_missing":
        return _direct("software", missing)
    if r.get("error"):
        return _direct("software", error)
    return None


@_phrased
def _do_software(session: dict, app_key: str) -> dict:
    auth = session.get("auth") or {}
    identifier = auth.get("sam") or auth.get("upn") or ""
    if ad.enabled() and not identifier:
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software aan te vragen.")
    r = actions.request_software(identifier, app_key)
    name = r.get("app_name") or app_key

    problem = _software_problem(
        r, name,
        no_account="Ik kon je account niet vinden om de aanvraag te verwerken. "
                   "Log opnieuw in of maak een ticket aan.",
        missing=f"De automatische uitrol voor **{name}** is nog niet ingericht. "
                f"Ik kan er een ticket voor aanmaken voor de Service Desk.",
        error=f"Er ging iets mis bij het aanvragen van **{name}**. Probeer het later "
              f"opnieuw of maak een ticket aan.")
    if problem:
        return problem
    if r.get("already"):
        return _direct("software",
                       f"**{name}** staat al voor je klaar. Het verschijnt na je volgende "
                       f"aanmelding; als je het nog niet ziet, meld je dan opnieuw aan.",
                       meta={"app": name})
    if r.get("method") == "ad" and r.get("added"):
        return _direct("software",
                       f"Je aanvraag voor **{name}** is verwerkt. De software wordt automatisch "
                       f"geïnstalleerd bij je volgende aanmelding (geen licentie nodig). Dit kan "
                       f"een paar minuten duren. Wil je het meteen zien? Meld je af en weer aan. "
                       f"Je kunt het versnellen door op je computer `gpupdate /force` uit te voeren "
                       f"en je daarna opnieuw aan te melden.",
                       meta={"app": name})
    # Geen AD beschikbaar: nette simulatie.
    return _direct("software",
                   f"Je aanvraag voor **{name}** is genoteerd (demo-modus: AD niet gekoppeld).",
                   meta={"app": name})


def _software_other_user(session: dict, msg: str) -> dict:
    """Zelfservice geldt alleen voor je eigen account. Voor iemand anders: bied een ticket aan."""
    session["pending"] = "offer_ticket"
    session["last_unanswered"] = msg
    return _direct("software",
                   "De zelfservice werkt alleen voor je eigen account, dus software voor "
                   "iemand anders kan ik hier niet regelen. Wil je dat ik hiervoor een ticket "
                   "aanmaak voor de Service Desk? (ja / nee)")


def _handle_software(session: dict, msg: str) -> dict:
    if ad.enabled() and not session.get("auth"):
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software aan te vragen.")
    if router.mentions_other_user(msg):
        return _software_other_user(session, msg)
    app = _extract_app(msg)
    if not app:
        session["pending"] = "software_request"
        return _direct("software_ask",
                       f"Welke software wil je aanvragen? Beschikbaar is: "
                       f"{', '.join(config.APP_DISPLAY)}.")
    return _do_software(session, app)


@_phrased
def _do_software_status(session: dict, app_key: str) -> dict:
    """Vertelt of het eigen account de software AL heeft, zonder iets te wijzigen."""
    auth = session.get("auth") or {}
    identifier = auth.get("sam") or auth.get("upn") or ""
    if ad.enabled() and not identifier:
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om dit te kunnen bekijken.")
    r = actions.check_software(identifier, app_key)
    name = r.get("app_name") or app_key

    problem = _software_problem(
        r, name,
        no_account="Ik kon je account niet vinden om dit te controleren. Log opnieuw in "
                   "of maak een ticket aan.",
        missing=f"De automatische uitrol voor **{name}** is nog niet ingericht. Ik kan "
                f"er een ticket voor aanmaken voor de Service Desk.",
        error=f"Ik kon de toegang voor **{name}** nu niet controleren. Probeer het later "
              f"opnieuw of maak een ticket aan.")
    if problem:
        return problem
    if r.get("has") is True:
        return _direct("software",
                       f"Ja, je hebt **{name}** al. Zie je het niet op je computer? Meld je dan "
                       f"opnieuw aan, dan verschijnt het.", meta={"app": name})
    if r.get("has") is False:
        # Lees de bedoeling: waarschijnlijk wil de gebruiker het dán aanvragen. Vraag het, niet doen.
        session["pending"] = "software_request"
        session["pending_app"] = app_key
        return _direct("software_ask",
                       f"Je hebt **{name}** nog niet. Wil je dat ik het nu voor je aanvraag? (ja / nee)")
    # Demo-modus (AD niet gekoppeld).
    return _direct("software",
                   f"In demo-modus (AD niet gekoppeld) kan ik de toegang voor **{name}** niet "
                   f"live controleren.")


def _handle_software_status(session: dict, msg: str) -> dict:
    if ad.enabled() and not session.get("auth"):
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om dit te kunnen bekijken.")
    if router.mentions_other_user(msg):
        return _software_other_user(session, msg)
    app = _extract_app(msg)
    if not app:
        session["pending"] = "software_status"
        return _direct("software_ask",
                       f"Voor welke software wil je dit controleren? Beschikbaar is: "
                       f"{', '.join(config.APP_DISPLAY)}.")
    return _do_software_status(session, app)


@_phrased
def _do_software_remove(session: dict, app_key: str) -> dict:
    """Haalt de software van het eigen account af (uit de AD-groep); de GPO de-installeert."""
    auth = session.get("auth") or {}
    identifier = auth.get("sam") or auth.get("upn") or ""
    if ad.enabled() and not identifier:
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software te verwijderen.")
    r = actions.remove_software(identifier, app_key)
    name = r.get("app_name") or app_key

    problem = _software_problem(
        r, name,
        no_account="Ik kon je account niet vinden om dit te verwerken. Log opnieuw in "
                   "of maak een ticket aan.",
        missing=f"De automatische uitrol voor **{name}** is niet ingericht, dus er is "
                f"niets te verwijderen.",
        error=f"Er ging iets mis bij het verwijderen van **{name}**. Probeer het later "
              f"opnieuw of maak een ticket aan.")
    if problem:
        return problem
    if r.get("not_member"):
        return _direct("software",
                       f"Je hebt **{name}** niet (meer), dus er is niets te verwijderen.",
                       meta={"app": name})
    if r.get("method") == "ad" and r.get("removed"):
        return _direct("software",
                       f"Je aanvraag om **{name}** te verwijderen is verwerkt. De software wordt "
                       f"automatisch verwijderd bij je volgende aanmelding. Het kan even duren tot "
                       f"het weg is. Wil je het versnellen? Voer op je computer `gpupdate /force` "
                       f"uit en meld je daarna opnieuw aan.",
                       meta={"app": name})
    return _direct("software",
                   f"Je verzoek om **{name}** te verwijderen is genoteerd (demo-modus: AD niet "
                   f"gekoppeld).", meta={"app": name})


def _handle_software_remove(session: dict, msg: str) -> dict:
    if ad.enabled() and not session.get("auth"):
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software te verwijderen.")
    if router.mentions_other_user(msg):
        return _software_other_user(session, msg)
    app = _extract_app(msg)
    if not app:
        session["pending"] = "software_remove"
        return _direct("software_ask",
                       f"Welke software wil je verwijderen? Beschikbaar is: "
                       f"{', '.join(config.APP_DISPLAY)}.")
    return _do_software_remove(session, app)


def _route_software(session: dict, msg: str, history: list[dict]):
    """Laat het LLM de bedoeling LEZEN (controleren / installeren / iets anders, en voor
    jezelf of iemand anders). Lukt dat niet, dan valt het terug op de trefwoord-methode.
    Geeft None terug als het níet over software blijkt te gaan, zodat de gewone afhandeling
    (uitleg/RAG) het overneemt."""
    if ad.enabled() and not session.get("auth"):
        return _direct("software_ask",
                       "Log eerst in (knop rechtsboven) om software te bekijken of aan te vragen.")

    parsed = None
    try:
        parsed = lmclient.parse_software_intent(msg, history, config.APP_DISPLAY)
    except Exception:
        parsed = None

    # Vangnet: geen bruikbaar LLM-oordeel -> oude trefwoord-aanpak.
    if parsed is None:
        if router.mentions_other_user(msg):
            return _software_other_user(session, msg)
        if router.wants_remove(msg):
            return _handle_software_remove(session, msg)
        if router.wants_status(msg):
            return _handle_software_status(session, msg)
        if router.classify(msg) == "software_request":
            return _handle_software(session, msg)
        return None

    if parsed.get("intent") == "none":
        return None
    # Voor iemand anders? Zelfservice is alleen voor je eigen account.
    if not parsed.get("for_self", True) or router.mentions_other_user(msg):
        return _software_other_user(session, msg)

    app = _extract_app(parsed.get("app", "")) or _extract_app(msg)
    intent = parsed.get("intent")

    if intent == "check":
        if not app:
            session["pending"] = "software_status"
            return _direct("software_ask",
                           f"Voor welke software wil je dit controleren? Beschikbaar is: "
                           f"{', '.join(config.APP_DISPLAY)}.")
        return _do_software_status(session, app)

    if intent == "remove":
        if not app:
            session["pending"] = "software_remove"
            return _direct("software_ask",
                           f"Welke software wil je verwijderen? Beschikbaar is: "
                           f"{', '.join(config.APP_DISPLAY)}.")
        return _do_software_remove(session, app)

    # intent == "install"
    if not app:
        session["pending"] = "software_request"
        return _direct("software_ask",
                       f"Welke software wil je aanvragen? Beschikbaar is: "
                       f"{', '.join(config.APP_DISPLAY)}.")
    return _do_software(session, app)
