"""
Service Desk-acties: ticket aanmaken en wachtwoordreset starten.

Veiligheidsprincipe (bewuste keuze): er wordt NOOIT een wachtwoord verstuurd —
niet in de chat en niet per e-mail. Een echt systeem mailt een *reset-link*, geen
wachtwoord, omdat een wachtwoord dan leesbaar in een mailbox belandt. Deze PoC
volgt dat principe: de e-mail bevat een reset-link.

E-mail wordt alleen écht verstuurd als SMTP is ingesteld (zie config.py). Anders
wordt het netjes gesimuleerd.
"""

from __future__ import annotations
import json
import ssl
import smtplib
import secrets
from email.message import EmailMessage
from datetime import datetime, timezone

import config
try:
    import graph          # optioneel (Microsoft Graph / Entra ID)
except ImportError:
    graph = None
try:
    import ad             # optioneel (on-prem Active Directory)
except ImportError:
    ad = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_data_dir() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)


def _log_action(kind: str, details: dict) -> None:
    _ensure_data_dir()
    record = {"time": _now_iso(), "action": kind, **details}
    with config.ACTION_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_tickets() -> list[dict]:
    if config.TICKETS_PATH.exists():
        try:
            return json.loads(config.TICKETS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save_tickets(tickets: list[dict]) -> None:
    _ensure_data_dir()
    config.TICKETS_PATH.write_text(
        json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mask_email(email: str) -> str:
    """t.sarpong@proact.nl -> t***@proact.nl"""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return email
    return f"{(local[0] if local else '?')}***@{domain}"


def to_email(identifier: str) -> str:
    identifier = identifier.strip().lower()
    return identifier if "@" in identifier else f"{identifier}@{config.EMAIL_DOMAIN}"


def create_ticket(subject: str, description: str = "", naam: str = "",
                  bedrijf: str = "", telefoon: str = "") -> dict:
    tickets = _load_tickets()
    ticket = {
        "id": f"PRO-{len(tickets) + 1:05d}",
        "created": _now_iso(),
        "subject": subject.strip() or "Onbekend onderwerp",
        "description": description.strip(),
        "naam": naam.strip(),
        "bedrijf": bedrijf.strip(),
        "telefoon": telefoon.strip(),
        "status": "open",
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    _log_action("create_ticket", {"ticket_id": ticket["id"], "subject": ticket["subject"]})
    return ticket


def _ticket_body(ticket: dict) -> str:
    """Nette bevestigingsmail van een aangemaakt ticket (lab/PoC)."""
    return (
        f"Hallo {ticket.get('naam') or 'collega'},\n\n"
        "Bedankt voor je melding. De Service Desk heeft een ticket voor je aangemaakt.\n\n"
        f"Ticketnummer : {ticket['id']}\n"
        f"Onderwerp    : {ticket['subject']}\n"
        f"Omschrijving : {ticket.get('description') or ticket['subject']}\n"
        f"Naam         : {ticket.get('naam', '')}\n"
        f"Bedrijf      : {ticket.get('bedrijf', '')}\n"
        f"Telefoon     : {ticket.get('telefoon', '')}\n"
        f"Aangemaakt   : {ticket['created']}\n"
        f"Status       : {ticket['status']}\n\n"
        "Een medewerker neemt dit zo snel mogelijk op. Verwijs bij vragen naar het ticketnummer.\n\n"
        "Proact Service Desk Assistant (PoC)\n"
    )


def send_ticket_email(ticket: dict, identifier: str = "", user_mail: str = "") -> dict:
    """Stuurt (als SMTP is ingesteld) een bevestigingsmail van het ticket naar het
    geregistreerde adres. Geeft een veilige samenvatting terug; is SMTP niet ingesteld,
    dan gebeurt er niets (sent=False)."""
    result = {"sent": False, "email_masked": "", "error": None}
    if not config.EMAIL_ENABLED:
        return result
    recipient = _notify_recipient(identifier or ticket.get("naam", ""), user_mail)
    result["email_masked"] = mask_email(recipient)
    try:
        _smtp_send(recipient, f"Ticket {ticket['id']} aangemaakt - {ticket['subject']}",
                   _ticket_body(ticket))
        result["sent"] = True
    except Exception as e:
        result["error"] = str(e)
    _log_action("ticket_email", {"ticket_id": ticket["id"], "sent": result["sent"],
                                 "error": result["error"]})
    return result


def _smtp_send(to_addr: str, subject: str, body: str) -> None:
    """Verstuurt een e-mail via SMTP. Kan een fout opgooien."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
        if config.SMTP_STARTTLS:
            server.starttls(context=ctx)
        server.login(config.SMTP_USER, config.SMTP_PASS)
        server.send_message(msg)


def _reset_link_body(link: str) -> str:
    return (
        "Hallo,\n\n"
        "Er is een verzoek gedaan om je wachtwoord opnieuw in te stellen.\n"
        f"Gebruik onderstaande link (geldig {config.RESET_LINK_VALID_MINUTES} minuten):\n\n"
        f"{link}\n\n"
        "Heb je dit niet aangevraagd? Neem contact op met de Service Desk.\n"
        "Er wordt nooit een wachtwoord per e-mail verstuurd.\n\n"
        "— Proact Service Desk Assistant (PoC)\n"
    )


def _sspr_body() -> str:
    return (
        "Hallo,\n\n"
        "Er is een verzoek gedaan om je wachtwoord opnieuw in te stellen.\n"
        "Stel zelf een nieuw wachtwoord in via de self-service wachtwoordreset: aka.ms/sspr\n\n"
        "Uit voorzorg zijn je actieve aanmeldingssessies beëindigd; je moet opnieuw inloggen.\n"
        "Heb je dit niet aangevraagd? Neem contact op met de Service Desk.\n"
        "Er wordt nooit een wachtwoord per e-mail verstuurd.\n\n"
        "— Proact Service Desk Assistant (PoC)\n"
    )


def _temp_password_body(temp: str) -> str:
    # PoC/lab: een tijdelijk wachtwoord mailen is alleen verantwoord doordat het bij de
    # volgende aanmelding MOET worden gewijzigd. Productiepatroon: one-time self-destruct link.
    return (
        "Hallo,\n\n"
        "Je wachtwoord is op verzoek opnieuw ingesteld door de Service Desk.\n\n"
        f"Tijdelijk wachtwoord: {temp}\n\n"
        "Je MOET dit wachtwoord wijzigen bij je volgende aanmelding.\n"
        "Heb je dit niet aangevraagd? Neem direct contact op met de Service Desk.\n\n"
        "— Proact Service Desk Assistant (PoC)\n"
    )


def _notify_recipient(identifier: str, user_mail: str = "") -> str:
    """Bepaalt het ontvangeradres.

    Volgorde (bewust gekozen):
      1. Het bij het account GEREGISTREERDE e-mailadres (AD-attribuut 'mail'). Net als
         bij een echte self-service reset gaat de melding naar het adres dat de
         gebruiker zelf heeft geregistreerd — dat kan dus per gebruiker verschillen.
      2. Een lab-vangnet (RESET_NOTIFY_OVERRIDE), voor accounts zonder geregistreerd adres.
      3. Pas als laatste een afgeleid adres.
    Zo gaat er nooit per ongeluk iets naar een echt @proact.nl-adres.
    """
    if user_mail:
        return user_mail
    if config.RESET_NOTIFY_OVERRIDE:
        return config.RESET_NOTIFY_OVERRIDE
    return to_email(identifier)


def request_software(identifier: str, app_key: str) -> dict:
    """
    Zelfservice software-aanvraag. Voegt het account toe aan de AD-groep die bij de
    gevraagde applicatie hoort; een GPO rolt de software daarna uit. Geen goedkeuring
    nodig (licentievrije software). Geeft een veilige samenvatting terug.
    """
    group_cn = config.APP_GROUPS.get(app_key.lower())
    result = {
        "app_key": app_key,
        "app_name": config.APP_NAMES.get(group_cn, app_key),
        "group": group_cn or "",
        "method": "simulated", "found": None,
        "added": False, "already": False, "error": None,
    }
    if not group_cn:
        result["error"] = "unknown_app"
        return result

    if ad and ad.enabled():
        result["method"] = "ad"
        try:
            user = ad.find_user(identifier)
            if user is None:
                result["found"] = False
                _log_action("software_request", {"identifier": identifier, "app": result["app_name"],
                                                 "group": group_cn, "method": "ad", "found": False})
                return result
            result["found"] = True
            grp = ad.find_group(group_cn)
            if grp is None:
                result["error"] = "group_missing"
            else:
                members_low = [m.lower() for m in grp.get("members", [])]
                if user["dn"].lower() in members_low:
                    result["already"] = True
                else:
                    ad.add_to_group(user["dn"], grp["dn"])
                    result["added"] = True
        except Exception as e:
            result["error"] = str(e)

    _log_action("software_request", {"identifier": identifier, "app": result["app_name"],
                                     "group": group_cn, "method": result["method"],
                                     "added": result["added"], "already": result["already"],
                                     "error": result["error"]})
    return result


def request_password_reset(identifier: str) -> dict:
    """
    Start een wachtwoordreset. In volgorde, afhankelijk van de configuratie:
      1. Microsoft Graph (Entra ID): verifieer -> sessies intrekken -> SSPR-link mailen.
      2. Active Directory (LDAPS): verifieer -> ontgrendelen -> tijdelijk wachtwoord +
         geforceerde wijziging -> tijdelijk wachtwoord mailen (als SMTP is ingesteld).
      3. SMTP: een reset-link mailen.
      4. Anders: simuleren.
    Geeft een VEILIGE samenvatting terug — nooit een wachtwoord in het resultaat.
    """
    email = to_email(identifier)
    result = {
        "email_masked": mask_email(email),
        "valid_minutes": config.RESET_LINK_VALID_MINUTES,
        "sent": False, "simulated": True, "method": "simulated",
        "found": None, "sessions_revoked": False, "unlocked": False, "error": None,
    }

    # --- 1) Microsoft Graph (Entra ID) ---
    if graph and graph.enabled():
        result["method"] = "graph"; result["simulated"] = False
        try:
            user = graph.get_user(email)
            if user is None:
                result["found"] = False
                _log_action("password_reset", {"identifier": identifier, "method": "graph", "found": False})
                return result
            result["found"] = True
            try:
                graph.revoke_sessions(user["id"]); result["sessions_revoked"] = True
            except Exception as e:
                result["error"] = f"revoke: {e}"
            graph.send_mail(email, "Wachtwoord opnieuw instellen — Proact Service Desk", _sspr_body())
            result["sent"] = True
        except Exception as e:
            result["error"] = str(e)
        _log_action("password_reset", {"identifier": identifier, "method": "graph",
                                        "email_sent": result["sent"], "error": result["error"]})
        return result

    # --- 2) On-prem Active Directory (LDAPS) ---
    if ad and ad.enabled():
        result["method"] = "ad"; result["simulated"] = False
        try:
            user = ad.find_user(identifier)
            if user is None:
                result["found"] = False
                _log_action("password_reset", {"identifier": identifier, "method": "ad", "found": False})
                return result
            result["found"] = True
            try:
                ad.unlock(user["dn"]); result["unlocked"] = True
            except Exception as e:
                result["error"] = f"unlock: {e}"
            temp = ad.reset_to_temp(user["dn"])          # tijdelijk wachtwoord (niet in result!)
            recipient = _notify_recipient(identifier, user.get("mail", ""))
            result["email_masked"] = mask_email(recipient)
            if config.EMAIL_ENABLED:
                try:
                    _smtp_send(recipient, "Wachtwoord opnieuw ingesteld — Proact Service Desk",
                               _temp_password_body(temp))
                    result["sent"] = True
                except Exception as e:
                    result["error"] = f"mail: {e}"
        except Exception as e:
            result["error"] = str(e)
        _log_action("password_reset", {"identifier": identifier, "method": "ad",
                                        "unlocked": result["unlocked"], "email_sent": result["sent"],
                                        "error": result["error"]})
        return result

    # --- 3) SMTP (self-service reset — verwijst naar een ECHTE, bereikbare pagina) ---
    if config.EMAIL_ENABLED:
        result["method"] = "smtp"; result["simulated"] = False
        recipient = _notify_recipient(identifier)
        result["email_masked"] = mask_email(recipient)
        try:
            _smtp_send(recipient, "Wachtwoord opnieuw instellen — Proact Service Desk", _sspr_body())
            result["sent"] = True
        except Exception as e:
            result["error"] = str(e)
        _log_action("password_reset", {"identifier": identifier, "method": "smtp",
                                        "email_sent": result["sent"], "error": result["error"]})
        return result

    # --- 4) Simulatie ---
    _log_action("password_reset", {"identifier": identifier, "method": "simulated", "email_sent": False})
    return result
