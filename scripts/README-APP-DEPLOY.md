# Zelfservice software-uitrol (chatbot, AD-groep, GPO)

Dit onderdeel heb ik toegevoegd zodat een gebruiker in de chatbot zelf een applicatie
kan aanvragen (bijvoorbeeld *"ik wil adobe reader"*). De chatbot zet het account in
een AD-groep; een GPO met Software Installation rolt de applicatie vervolgens uit bij
de volgende aanmelding. Voor licentievrije software is er geen goedkeuring nodig.

De keten die ik heb gebouwd: chatbot voegt de gebruiker toe aan de groep `App-<App>`
via LDAPS, de GPO is gefilterd op die groep, en de software installeert bij aanmelding.

## Onderdelen

| Onderdeel | Waar | Rol |
|-----------|------|-----|
| `config.py` met `APP_GROUPS`, `APP_NAMES`, `APP_DISPLAY` | chatbot (Linux) | koppelt een app-naam aan een AD-groep |
| `ad.py` met `find_group()` en `add_to_group()` | chatbot (Linux) | voegt de gebruiker toe aan de groep via LDAPS |
| `router.py` en `rag.py` | chatbot (Linux) | herkent de aanvraag en voert de self-service flow uit |
| `scripts/03-Setup-AppDeploy.ps1` | Windows Server (DC) | maakt groep, share, GPO en delegatie |
| GPO-editor (handmatig) | Windows Server (DC) | wijst de MSI toe aan de GPO |
| Windows-client (domain-joined) | aparte VM | voert de installatie uit bij aanmelding |

## Wat ik heb gedaan, stap voor stap

### 1. AD-groep, share en GPO aangemaakt (geautomatiseerd)

Op de domaincontroller heb ik het script als Administrator gedraaid:

```powershell
Unblock-File .\03-Setup-AppDeploy.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\03-Setup-AppDeploy.ps1
```

Het script maakt de security-groep in `OU=ProactLab`, geeft `svc-chatbot` schrijfrecht
op `member` (zodat de chatbot leden kan toevoegen), maakt de share `\\DC01\Deploy` en
maakt de GPO met security-filtering (alleen leden van de groep passen de GPO toe).

Voor een extra applicatie draai ik hetzelfde script met parameters, bijvoorbeeld:

```powershell
.\03-Setup-AppDeploy.ps1 -GroupName App-7Zip -GpoName Deploy-7Zip
```

### 2. MSI klaargezet op de share

De MSI zit in een `.exe` (offline installer). Ik heb die uitgepakt (niet geinstalleerd)
naar de share-map:

```powershell
C:\Install\AcroRdrDC.exe -sfx_o"C:\Deploy\Reader" -nos_ne
Get-ChildItem C:\Deploy\Reader -Recurse -Filter *.msi | Select-Object FullName
```

De hele uitgepakte map staat in de share, omdat de MSI zijn bijbehorende bestanden
(onder andere `.cab`) nodig heeft. Alleen de `.msi` kopieren is niet genoeg.

### 3. MSI toegewezen in de GPO (handmatig)

Dit is de stap die PowerShell niet kan automatiseren en die ik met de hand heb gedaan:

1. In **Group Policy Management** rechtsklik op de GPO (`Deploy-AdobeReader`) en **Bewerken**.
2. Naar **Gebruikersconfiguratie, Beleid, Softwareinstellingen, Software-installatie**.
3. Rechtsklik, **Nieuw, Pakket**, en de MSI gekozen via het UNC-pad
   (`\\DC01\Deploy\Reader\AcroRead.msi`), niet via `C:\...`.
4. Gekozen voor **Toegewezen** (Assigned).
5. Daarna rechtsklik op het pakket, **Eigenschappen**, tabblad **Implementatie**, en
   **"Deze toepassing na aanmelding installeren"** aangevinkt. Zonder dit vinkje wordt
   de app alleen geadverteerd en installeert hij niet automatisch bij aanmelding. Dit
   was ook de reden waarom het eerst niet installeerde.

### 4. Client aan het domein gekoppeld

Een aparte Windows 11 Pro/Enterprise VM (Home kan niet domain-joinen). De DNS van de
client wijst naar de DC (192.168.2.10). Daarna:

```powershell
Add-Computer -DomainName lab.proact.local -Credential LAB\Administrator -Restart
```

### 5. Gedemonstreerd

1. In de chatbot ingelogd als een gebruiker (`anna.devries`) en getypt: *"ik wil adobe reader"*.
2. In **Active Directory Users and Computers** gecontroleerd dat de gebruiker lid werd
   van `App-AdobeReader`.
3. Die gebruiker aangemeld op de client, waarna de software bij aanmelding installeert.
   Software-installatie verwerkt synchroon bij een volledige aanmelding; soms was een
   reboot of tweede aanmelding nodig door Windows fast-logon.

## Controle op de client

```powershell
whoami                              # toont lab\<gebruiker>
whoami /groups | findstr /i App-    # toont App-AdobeReader
gpresult /r                         # Deploy-AdobeReader onder toegepaste GPO's
```

Visueel: in het Startmenu staat de applicatie erbij.

## Problemen die ik ben tegengekomen en hoe ik ze heb opgelost

- **RDP werkte niet (poort 3389 geweigerd).** Opgelost met `Fix-RDP.ps1` op de server
  via de Proxmox-console: Remote Desktop en de firewall (`@FirewallAPI.dll,-28752`)
  aangezet en de `TermService` herstart.
- **Windows 11-setup eiste een Microsoft-account.** Omzeild met `Shift+F10` en
  `start ms-cxh:localonly` voor een lokaal account. Op een Mac-toetsenbord is dat
  `Fn+Shift+F10`.
- **"N/A" bij `gpresult`.** De MSI was nog niet toegewezen in de GPO (stap 3).
- **App installeerde niet bij aanmelding.** Het vinkje "Deze toepassing na aanmelding
  installeren" stond uit (stap 3.5), of de bron-MSI miste zijn `.cab`-bestanden (stap 2).
- **Generiek icoon in plaats van het app-logo.** De icooncache liep achter; na de app
  een keer openen of de client herstarten was het goed.
