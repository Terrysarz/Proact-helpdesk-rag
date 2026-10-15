"""
Officiële Microsoft-hulplinks per KB-onderwerp.

De chatbot stuurt bij een antwoord automatisch de bijpassende officiële
Microsoft-link mee (klantgericht: de klant kan het ook zelf nalezen). De links
worden hier deterministisch beheerd, zodat het model ze niet hoeft te verzinnen.
"""

from __future__ import annotations

# bestandsnaam in documents/  ->  lijst van (label, url)
SOURCE_LINKS: dict[str, list[tuple[str, str]]] = {
    "01-wachtwoord-en-mfa.md": [
        ("Wachtwoord opnieuw instellen (Microsoft)", "https://aka.ms/sspr"),
        ("Multi-factor authenticatie instellen (Microsoft)", "https://aka.ms/mfasetup"),
    ],
    "02-outlook.md": [
        ("Outlook-hulp (Microsoft)", "https://support.microsoft.com/outlook"),
    ],
    "03-teams.md": [
        ("Microsoft Teams-hulp", "https://support.microsoft.com/teams"),
    ],
    "04-onedrive-sharepoint.md": [
        ("OneDrive-hulp (Microsoft)", "https://support.microsoft.com/onedrive"),
    ],
    "07-m365-licentie.md": [
        ("Microsoft 365-apps installeren", "https://support.microsoft.com/office"),
    ],
    "08-antivirus-defender.md": [
        ("Windows-beveiliging (Microsoft)", "https://support.microsoft.com/windows"),
    ],
}


def for_sources(sources: list[str]) -> list[dict]:
    """Geeft de links terug voor de eerste bron die een match heeft (max 2)."""
    for src in sources:
        hit = SOURCE_LINKS.get(src)
        if hit:
            return [{"label": label, "url": url} for label, url in hit[:2]]
    return []
