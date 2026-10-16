# Zelfservice software-uitrol (chatbot → AD-groep → GPO)

Deze module laat een gebruiker in de chatbot een applicatie aanvragen (bijv.
*"ik wil adobe reader"*). De chatbot zet het account in een AD-groep; een GPO met
Software Installation rolt de applicatie vervolgens uit bij de volgende aanmelding.
Geen goedkeuring nodig voor licentievrije software.

**Keten:** chatbot → `add_members_to_groups` (LDAPS) → lidmaatschap `App-<App>` →
GPO (gefilterd op die groep) → installatie bij aanmelding.

---

## Onderdelen

| Onderdeel | Waar | Rol |
|-----------|------|-----|
| `config.py` → `APP_GROUPS`/`APP_NAMES`/`APP_DISPLAY` | chatbot (Linux) | koppelt een app-naam aan een AD-groep |
| `ad.py` → `find_group()`, `add_to_group()` | chatbot (Linux) | voegt gebruiker toe aan de groep via LDAPS |
| `router.py` / `rag.py` | chatbot (Linux) | herkent de aanvraag en voert de self-service flow uit |
| `scripts/03-Setup-AppDeploy.ps1` | Windows Server (DC) | maakt groep + share + GPO + delegatie |
| GPO-editor (handmatig) | Windows Server (DC) | wijst de MSI toe aan de GPO |
| Windows-client (domain-joined) | aparte VM | voert de installatie uit bij aanmelding |

---

## Stap 1 — AD-groep, share en GPO (geautomatiseerd)

Op de domaincontroller, PowerShell als Administrator:

```powershell
Unblock-File .\03-Setup-AppDeploy.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\03-Setup-AppDeploy.ps1
```

Voor een extra applicatie draai je hetzelfde script met parameters, bijv.:

```powershell
.\03-Setup-AppDeploy.ps1 -GroupName App-7Zip -GpoName Deploy-7Zip
```

Het script maakt: de security-groep in `OU=ProactLab`, schrijfrecht op `member`
voor `svc-chatbot` (zodat de chatbot leden kan toevoegen), de share `\\DC01\Deploy`,
en de GPO met security-filtering (alleen leden van de groep passen de GPO toe).

## Stap 2 — MSI klaarzetten op de share

De MSI zit meestal in een `.exe` (offline installer). Uitpakken (NIET installeren)
naar de share-map:

```powershell
# voorbeeld Adobe Reader
C:\Install\AcroRdrDC.exe -sfx_o"C:\Deploy\Reader" -nos_ne
Get-ChildItem C:\Deploy\Reader -Recurse -Filter *.msi | Select-Object FullName
```

> **Let op:** de hele uitgepakte map moet in de share staan — de MSI heeft zijn
> bijbehorende bestanden (o.a. `.cab`) nodig, anders faalt de installatie.

## Stap 3 — MSI toewijzen in de GPO (HANDMATIG — kan niet via script)

Dit is de stap die PowerShell niet kan automatiseren:

1. **Group Policy Management** → rechtsklik de GPO (bijv. `Deploy-AdobeReader`) → **Bewerken**.
2. **Gebruikersconfiguratie → Beleid → Softwareinstellingen → Software-installatie**.
3. Rechtsklik → **Nieuw → Pakket…** en kies de MSI via het **UNC-pad**
   (bijv. `\\DC01\Deploy\Reader\AcroRead.msi`) — NIET via `C:\...`.
4. Kies **Toegewezen** (Assigned).
5. **Belangrijk:** rechtsklik het pakket → **Eigenschappen** → tabblad **Implementatie**
   → vink **"Deze toepassing na aanmelding installeren"** aan. Zonder dit vinkje wordt
   de app alleen "geadverteerd" en installeert hij niet automatisch bij aanmelding.

## Stap 4 — Client aan het domein

Op een aparte Windows 11 **Pro/Enterprise** VM (Home kan niet domain-joinen):

```powershell
Add-Computer -DomainName lab.proact.local -Credential LAB\Administrator -Restart
```

(DNS van de client moet naar de DC wijzen: 192.168.2.10.)

## Stap 5 — Demonstreren

1. In de chatbot inloggen als een gebruiker (bijv. `anna.devries`) en typen:
   *"ik wil adobe reader"*.
2. In **Active Directory Users and Computers** controleren dat de gebruiker lid is
   geworden van `App-AdobeReader`.
3. Die gebruiker **aanmelden** op de client → de software installeert bij aanmelding.
   (Software-installatie verwerkt synchroon bij een volledige aanmelding; soms is een
   reboot of tweede aanmelding nodig door Windows' fast-logon.)

## Controle op de client

```powershell
whoami                              # moet lab\<gebruiker> tonen
whoami /groups | findstr /i App-    # moet App-AdobeReader tonen
gpresult /r                         # Deploy-AdobeReader onder toegepaste GPO's
```
Of visueel: Startmenu → de applicatie staat erbij.

---

## Troubleshooting (tegengekomen tijdens opzet)

- **RDP werkt niet (poort 3389 refused):** draai `Fix-RDP.ps1` op de server (via de
  Proxmox-console). Zet Remote Desktop + firewall (`@FirewallAPI.dll,-28752`) aan en
  herstart de `TermService`.
- **Windows 11 setup eist Microsoft-account:** `Shift+F10` → `start ms-cxh:localonly`
  voor een lokaal account. (Op een Mac-toetsenbord: `Fn+Shift+F10`.)
- **"N/A" bij `gpresult`:** de MSI was nog niet toegewezen in de GPO (stap 3).
- **App installeert niet bij aanmelding:** vinkje "Deze toepassing na aanmelding
  installeren" stond uit (stap 3.5), of de bron-MSI miste zijn `.cab`-bestanden (stap 2).
- **Generiek icoon i.p.v. app-logo:** icooncache loopt achter; open de app één keer
  of herstart de client.
