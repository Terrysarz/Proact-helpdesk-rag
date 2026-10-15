"""
Optionele on-prem Active Directory-integratie (LDAPS) voor de chatbot.

Configureer via OMGEVINGSVARIABELEN (nooit in de code):
  AD_SERVER          bv. 192.168.2.10 (IP of hostnaam van de domaincontroller)
  AD_PORT            standaard 636 (LDAPS)
  AD_USE_SSL         true  (LDAPS; nodig om wachtwoorden te zetten)
  AD_VALIDATE_CERT   false in een lab (sla certificaatvalidatie over)
  AD_BASE_DN         bv. DC=lab,DC=proact,DC=local
  AD_BIND_DN         DN van het serviceaccount (bv. CN=svc-chatbot,OU=ProactLab,DC=...)
  AD_BIND_PASSWORD   wachtwoord van het serviceaccount

Veilig: de chatbot toont nooit een wachtwoord in de chat. Voor een reset wordt een
tijdelijk wachtwoord gezet mét "moet wijzigen bij volgende aanmelding"; de levering
daarvan regelt de aanroeper (bv. per e-mail), nooit via de chat.
"""

from __future__ import annotations
import os
import ssl
import string
import secrets

# Instellingen rechtstreeks uit omgevingsvariabelen (zelfstandige module).
AD_SERVER = os.getenv("AD_SERVER", "")
AD_PORT = int(os.getenv("AD_PORT", "636"))
AD_USE_SSL = os.getenv("AD_USE_SSL", "true").lower() == "true"
AD_VALIDATE_CERT = os.getenv("AD_VALIDATE_CERT", "false").lower() == "true"
AD_BASE_DN = os.getenv("AD_BASE_DN", "")
AD_BIND_DN = os.getenv("AD_BIND_DN", "")
AD_BIND_PASSWORD = os.getenv("AD_BIND_PASSWORD", "")


def enabled() -> bool:
    return bool(AD_SERVER and AD_BASE_DN and AD_BIND_DN and AD_BIND_PASSWORD)


def _connect():
    """Opent een (LDAPS-)verbinding met de domaincontroller en bindt het serviceaccount."""
    from ldap3 import Server, Connection, Tls, ALL
    validate = ssl.CERT_REQUIRED if AD_VALIDATE_CERT else ssl.CERT_NONE
    tls = Tls(validate=validate)
    server = Server(AD_SERVER, port=AD_PORT, use_ssl=AD_USE_SSL, tls=tls, get_info=ALL)
    return Connection(server, user=AD_BIND_DN, password=AD_BIND_PASSWORD, auto_bind=True)


def find_user(identifier: str) -> dict | None:
    """Zoekt een gebruiker op userPrincipalName of sAMAccountName. None als niet gevonden."""
    from ldap3 import SUBTREE
    sam = identifier.split("@")[0] if "@" in identifier else identifier
    conn = _connect()
    try:
        conn.search(AD_BASE_DN,
                    f"(&(objectClass=user)(|(userPrincipalName={identifier})(sAMAccountName={sam})))",
                    search_scope=SUBTREE,
                    attributes=["distinguishedName", "userPrincipalName", "sAMAccountName",
                                "mail", "displayName", "cn", "company"])
        if not conn.entries:
            return None
        e = conn.entries[0]
        def val(attr):
            return str(e[attr]) if attr in e and e[attr] else ""
        return {
            "dn": str(e.entry_dn),
            "sam": val("sAMAccountName"),
            "upn": val("userPrincipalName"),
            "mail": val("mail"),
            "name": val("displayName") or val("cn"),
            "company": val("company"),
        }
    finally:
        conn.unbind()


def _upn_suffix() -> str:
    """Leidt het UPN-achtervoegsel af uit de base DN (DC=lab,DC=proact,DC=local -> lab.proact.local)."""
    override = os.getenv("AD_UPN_SUFFIX", "")
    if override:
        return override
    parts = [p.split("=", 1)[1] for p in AD_BASE_DN.split(",")
             if p.strip().lower().startswith("dc=")]
    return ".".join(parts)


def authenticate(username: str, password: str) -> dict | None:
    """
    Verifieert gebruikersnaam + wachtwoord via een LDAP-bind (de gebruiker zelf).
    Lukt de bind -> gebruiker is wie die zegt; geeft de gebruikersgegevens terug.
    Lukt de bind niet -> None.
    """
    from ldap3 import Server, Connection, Tls, ALL
    if not (username and password):
        return None
    bind_user = username if "@" in username else f"{username}@{_upn_suffix()}"
    validate = ssl.CERT_REQUIRED if AD_VALIDATE_CERT else ssl.CERT_NONE
    tls = Tls(validate=validate)
    server = Server(AD_SERVER, port=AD_PORT, use_ssl=AD_USE_SSL, tls=tls, get_info=ALL)
    try:
        conn = Connection(server, user=bind_user, password=password, auto_bind=True)
    except Exception:
        return None            # verkeerde inloggegevens
    conn.unbind()
    # Inloggegevens kloppen -> gegevens ophalen via het serviceaccount.
    return find_user(username)


def unlock(dn: str) -> None:
    """Ontgrendelt een vergrendeld account."""
    conn = _connect()
    try:
        conn.extend.microsoft.unlock_account(dn)
    finally:
        conn.unbind()


def _gen_password(length: int = 16) -> str:
    """Genereert een sterk tijdelijk wachtwoord dat aan AD-complexiteit voldoet."""
    alphabet = string.ascii_letters + string.digits + "!@#$%?-"
    body = "".join(secrets.choice(alphabet) for _ in range(length - 4))
    return "Aa1!" + body


def reset_to_temp(dn: str) -> str:
    """
    Zet een tijdelijk wachtwoord én 'moet wijzigen bij volgende aanmelding'.
    Vereist LDAPS. Geeft het tijdelijke wachtwoord terug, zodat de aanroeper het
    VEILIG kan leveren (bv. one-time link of e-mail) — nooit in de chat.
    """
    from ldap3 import MODIFY_REPLACE
    temp = _gen_password()
    conn = _connect()
    try:
        conn.extend.microsoft.modify_password(dn, temp)        # nieuw (tijdelijk) wachtwoord
        conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])]})  # 0 = wijzigen bij volgende logon
        if not conn.result or conn.result.get("result") not in (0, None):
            raise RuntimeError(f"pwdLastSet zetten mislukt: {conn.result}")
        return temp
    finally:
        conn.unbind()
