"""
Wachtwoordreset: het aanbod, de bevestiging en de uitvoering.
"""

from __future__ import annotations
import actions
import ad
import responder
import router
from flow_common import _direct, _first_name, _pick


_PW_QUESTION_WORDS = ("reset", "resetten", "wijzig", "wijzigen", "aanpassen", "veranderen",
                      "vergeten", "kwijt", "opnieuw", "verlopen")


def _offer_reset(session: dict, msg: str) -> dict:
    """De klant zegt het wachtwoord kwijt te zijn of te willen wijzigen. Eerst vragen, dan pas doen."""
    if ad.enabled() and not session.get("auth"):
        return _handle_reset(session, msg)          # vraagt om eerst in te loggen
    found = router._EMAIL_RE.search(msg)
    session["pending"] = "reset_confirm"
    session["reset_target"] = found.group(0).lower() if found else ""
    return _direct("reset_ask", _pick(session, "reset_offer", [
        "Dat kan ik voor je regelen. Zal ik je wachtwoord resetten en een tijdelijk wachtwoord naar je mailen? (ja / nee)",
        "Ik kan je wachtwoord voor je resetten en het tijdelijke wachtwoord mailen. Zal ik dat doen? (ja / nee)",
    ]))


def _do_reset(identifier: str, session: dict | None = None) -> dict:
    session = session if session is not None else {}
    r = actions.request_password_reset(identifier)

    # Account niet gevonden (Active Directory).
    if r.get("found") is False:
        return _direct(
            "reset",
            f"Ik kon het account **{r['email_masked']}** niet vinden. Controleer de "
            f"gebruikersnaam of het e-mailadres, of maak een ticket aan.",
        )

    # Active Directory (on-prem): ontgrendelen + tijdelijk wachtwoord + geforceerde wijziging.
    if r.get("method") == "ad":
        parts = []
        if r.get("unlocked"):
            parts.append("Je account is ontgrendeld.")
        if r["sent"]:
            parts.append(f"Er is een tijdelijk wachtwoord ingesteld en gemaild naar "
                         f"**{r['email_masked']}**, te wijzigen bij de volgende aanmelding.")
        else:
            parts.append("Er is een tijdelijk wachtwoord ingesteld (te wijzigen bij de volgende "
                         "aanmelding). Neem contact op met de Service Desk voor de inloggegevens.")
        must = ["ontgrendeld"] if r.get("unlocked") else []
        if r["sent"]:
            must.append(r["email_masked"])
        text = (responder.rephrase(" ".join(parts), _first_name(session), must=tuple(must)) +
                "\n\nOm veiligheidsredenen wordt het wachtwoord nooit in de chat getoond.")
        return _direct("reset", text, meta={"email_masked": r["email_masked"]})

    if r["sent"]:
        lead = f"Er is een beveiligde reset-link **gemaild** naar **{r['email_masked']}**."
    elif r["simulated"]:
        lead = (f"Er is een beveiligde reset-link klaargezet voor **{r['email_masked']}** "
                f"(gesimuleerd: e-mail is niet geconfigureerd).")
    else:
        lead = (f"Het versturen naar **{r['email_masked']}** is mislukt; probeer het later "
                f"opnieuw of maak een ticket.")
    text = (
        f"{lead}\nDe link is {r['valid_minutes']} minuten geldig.\n\n"
        "Om veiligheidsredenen wordt er nooit een wachtwoord verstuurd, alleen een reset-link."
    )
    return _direct("reset", text, meta={"email_masked": r["email_masked"], "sent": r["sent"]})


def _handle_reset(session: dict, msg: str) -> dict:
    """Autorisatie rond een wachtwoordreset.
    Met AD-login: je moet ingelogd zijn en mag alleen je EIGEN account resetten
    (agents mogen anderen). Zonder AD-login: het oude gedrag."""
    auth = session.get("auth")
    ident = router.extract_identifier(msg)

    if ad.enabled():
        if not auth:
            return _direct("reset_ask",
                           "Log eerst in (knop rechtsboven) om een wachtwoordreset te starten.")
        self_sam = (auth.get("sam") or "").lower()
        target = ident or self_sam
        tgt_sam = target.lower().split("@")[0]
        if tgt_sam and tgt_sam != self_sam and not auth.get("is_agent"):
            return _direct("reset",
                           "Je kunt alleen je **eigen** wachtwoord resetten. "
                           "Vraag een Service Desk-medewerker voor een ander account.")
        return _do_reset(target, session)

    # Geen AD-login beschikbaar: oude gedrag.
    if ident:
        return _do_reset(ident, session)
    session["pending"] = "password_reset"
    return _direct("reset_ask",
                   "Ik kan een wachtwoordreset voor je starten. Voor welk account? "
                   "Geef je gebruikersnaam of e-mailadres.")
