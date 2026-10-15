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


def create_ticket(subject: str, details: str = "") -> dict:
    tickets = _load_tickets()
    ticket = {
        "id": f"PRO-{len(tickets) + 1:05d}",
        "created": _now_iso(),
        "subject": subject.strip() or "Onbekend onderwerp",
        "details": details.strip(),
        "status": "open",
    }
    tickets.append(ticket)
    _save_tickets(tickets)
    _log_action("create_ticket", {"ticket_id": ticket["id"], "subject": ticket["subject"]})
    return ticket


def _send_reset_email(to_addr: str, link: str) -> None:
    """Verstuurt echt een e-mail met een reset-link via SMTP. Kan een fout opgooien."""
    msg = EmailMessage()
    msg["Subject"] = "Wachtwoord opnieuw instellen — Proact Service Desk"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(
        "Hallo,\n\n"
        "Er is een verzoek gedaan om je wachtwoord opnieuw in te stellen.\n"
        f"Gebruik onderstaande link (geldig {config.RESET_LINK_VALID_MINUTES} minuten):\n\n"
        f"{link}\n\n"
        "Heb je dit niet aangevraagd? Negeer deze e-mail of neem contact op met de Service Desk.\n"
        "Er wordt nooit een wachtwoord per e-mail verstuurd.\n\n"
        "— Proact Service Desk Assistant (PoC)\n"
    )
    ctx = ssl.create_default_context()
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
        if config.SMTP_STARTTLS:
            server.starttls(context=ctx)
        server.login(config.SMTP_USER, config.SMTP_PASS)
        server.send_message(msg)


def request_password_reset(identifier: str) -> dict:
    """
    Start een wachtwoordreset: genereert een reset-link en mailt die (of simuleert).
    Geeft een VEILIGE samenvatting terug — zonder token of wachtwoord.
    """
    email = to_email(identifier)
    token = secrets.token_urlsafe(24)          # alleen voor de link; niet tonen/mailen als wachtwoord
    link = f"{config.RESET_BASE_URL}?token={token}"

    sent = False
    error = None
    if config.EMAIL_ENABLED:
        try:
            _send_reset_email(email, link)
            sent = True
        except Exception as e:                 # SMTP-fouten netjes opvangen
            error = str(e)

    _log_action("password_reset", {
        "identifier": identifier, "email": email,
        "email_sent": sent, "simulated": not config.EMAIL_ENABLED,
        "error": error,                        # de token zelf loggen we bewust niet
    })
    return {
        "email_masked": mask_email(email),
        "valid_minutes": config.RESET_LINK_VALID_MINUTES,
        "sent": sent,
        "simulated": not config.EMAIL_ENABLED,
        "error": error,
    }
