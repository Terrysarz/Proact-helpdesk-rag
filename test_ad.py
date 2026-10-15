"""
Koppelingstest: bewijst dat de chatbot je Active Directory kan bereiken.

Gebruik op de Linux-VM (in de venv), NADAT je de AD_* omgevingsvariabelen hebt gezet
(zie de output van 02-Setup-Lab.ps1) en 'pip install ldap3' hebt gedaan:

    python test_ad.py terry.sarpong
    python test_ad.py terry.sarpong --unlock
    python test_ad.py terry.sarpong --reset     # zet een tijdelijk wachtwoord (toont het NIET)

Het laat zien of de verbinding werkt en of de gebruiker gevonden wordt.
"""

import sys
sys.path.insert(0, "src")
import ad


def main() -> None:
    if not ad.enabled():
        print("AD is niet geconfigureerd. Zet eerst de AD_* omgevingsvariabelen "
              "(zie de output van 02-Setup-Lab.ps1).")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Gebruik: python test_ad.py <gebruikersnaam-of-upn> [--unlock | --reset]")
        sys.exit(1)

    identifier = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Verbinden met AD en zoeken naar '{identifier}' ...")
    try:
        user = ad.find_user(identifier)
    except Exception as e:
        print("FOUT bij verbinden/zoeken:", e)
        print("Controleer AD_SERVER/poort, het serviceaccount en of LDAPS actief is.")
        sys.exit(1)

    if not user:
        print("Gebruiker NIET gevonden. Controleer de naam of de AD_BASE_DN.")
        sys.exit(1)

    print("Gevonden:")
    print("  naam :", user["name"] or "(onbekend)")
    print("  upn  :", user["upn"])
    print("  mail :", user["mail"] or "(geen)")
    print("  dn   :", user["dn"])

    if action == "--unlock":
        ad.unlock(user["dn"])
        print("Account ontgrendeld.")
    elif action == "--reset":
        ad.reset_to_temp(user["dn"])
        print("Tijdelijk wachtwoord gezet + 'wijzigen bij volgende aanmelding'. "
              "(Het wachtwoord wordt bewust niet getoond.)")
    else:
        print("Koppeling werkt. (Voeg --unlock of --reset toe om een actie uit te voeren.)")


if __name__ == "__main__":
    main()
