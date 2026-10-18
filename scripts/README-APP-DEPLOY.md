# Zelfservice software (chatbot, AD-groep, GPO)

Dit onderdeel heb ik toegevoegd zodat een gebruiker in de chatbot zelf een applicatie
kan beheren: aanvragen (*"ik wil adobe reader"*), controleren of die al klaarstaat
(*"heb ik al toegang tot adobe?"*) of weer laten verwijderen (*"verwijder adobe weer"*).
De chatbot leest met het taalmodel wat er echt bedoeld wordt, en of het voor de gebruiker
zelf of voor iemand anders is. Voor licentievrije software (Adobe Reader) is er geen
goedkeuring nodig.

De keten die ik heb gebouwd: de chatbot zet de gebruiker via LDAPS in of uit de groep
`App-AdobeReader`. De GPO is gefilterd op die groep, dus de software installeert bij
aanmelding voor groepsleden. Voor het verwijderen draait een geplande taak op de client
die bij aanmelding controleert of de gebruiker nog in de groep zit, en zo niet de software
stil de-installeert.

## Onderdelen

| Onderdeel | Waar | Rol |
|-----------|------|-----|
| `config.py` met `APP_GROUPS`, `APP_NAMES`, `APP_DISPLAY` | chatbot (Linux) | koppelt een app-naam aan een AD-groep |
| `ad.py` met `find_group()`, `add_to_group()`, `remove_from_group()` | chatbot (Linux) | zet de gebruiker in of uit de groep via LDAPS |
| `router.py`, `lmclient.py`, `rag.py` | chatbot (Linux) | leest de bedoeling (aanvragen/controleren/verwijderen, voor zichzelf of iemand anders) en voert de flow uit |
| `scripts/03-Setup-AppDeploy.ps1` | Windows Server (DC) | maakt groep, share, GPO en delegatie |
| GPO-editor (handmatig) | Windows Server (DC) | wijst de MSI toe aan de GPO (installeren) |
| `scripts/Uninstall-AdobeReader.ps1` + geplande taak | Windows Server / client | verwijdert de software zodra de gebruiker uit de groep is |
| Windows-client (domain-joined) | aparte VM | voert installatie en verwijdering uit bij aanmelding |

## Wat ik heb gedaan, stap voor stap

### 1. AD-groep, share en GPO aangemaakt (geautomatiseerd)

Op de domaincontroller heb ik het script als Administrator gedraaid:

```powershell
Unblock-File .\03-Setup-AppDeploy.ps1
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\03-Setup-AppDeploy.ps1 -MsiPath "C:\Install\AcroRead.msi" -UninstallScript "C:\Install\Uninstall-AdobeReader.ps1"
```

Het script maakt de security-groep in `OU=ProactLab`, geeft `svc-chatbot` schrijfrecht
op `member` (zodat de chatbot leden kan toevoegen en verwijderen), maakt de share
`\\DC01\Deploy\Reader`, kopieert de MSI en het verwijder-script daarheen, en maakt de
GPO met security-filtering (alleen leden van de groep passen de GPO toe, Geverifieerde
gebruikers houden alleen leesrecht voor MS16-072).

### 2. MSI klaargezet op de share

Ik heb de gratis Adobe Reader enterprise-installer (`.exe`) uitgepakt naar de share-map,
zodat de MSI zijn bijbehorende bestanden (onder andere `.cab`) bij zich heeft. Alleen de
`.msi` kopieren is niet genoeg.

```powershell
C:\Install\AcroRdrDC...exe -sfx_o"C:\Deploy\Reader" -nos_ne
Get-ChildItem C:\Deploy\Reader -Recurse -Filter *.msi | Select-Object FullName
```

Ik gebruik bewust de gratis **Adobe Reader**, niet Acrobat Pro. Reader is licentievrij
(past bij de self-service zonder goedkeuring) en laat zich netjes stil installeren en
verwijderen. Ik let er ook op dat de bitness van de uitgerolde MSI klopt met wat op de
client belandt, zodat installeren en verwijderen hetzelfde product betreffen.

### 3. MSI toegewezen in de GPO (handmatig)

Dit is de stap die PowerShell niet kan automatiseren en die ik met de hand heb gedaan:

1. In **Group Policy Management** rechtsklik op de GPO (`Deploy-AdobeReader`) en **Bewerken**.
2. Naar **Gebruikersconfiguratie, Beleid, Softwareinstellingen, Software-installatie**.
3. Rechtsklik, **Nieuw, Pakket**, en de MSI gekozen via het UNC-pad
   (`\\DC01\Deploy\Reader\AcroRead.msi`), niet via `C:\...`.
4. Gekozen voor **Toegewezen** (Assigned).
5. Daarna rechtsklik op het pakket, **Eigenschappen**, tabblad **Distributie**, en twee
   vinkjes aangezet:
   - **"Deze toepassing na aanmelding installeren"**. Zonder dit vinkje wordt de app
     alleen geadverteerd en installeert hij niet automatisch bij aanmelding. Dit was ook
     de reden waarom het eerst niet installeerde.
   - **"De installatie van deze toepassing ongedaan maken als deze niet wordt beheerd"**.

### 4. Client aan het domein gekoppeld

Een aparte Windows 11 Pro/Enterprise VM (Home kan niet domain-joinen). De DNS van de
client wijst naar de DC (192.168.2.10). Daarna:

```powershell
Add-Computer -DomainName lab.proact.local -Credential LAB\Administrator -Restart
```

### 5. Verwijderen ingericht (geplande taak)

Het GPO-vinkje "verwijderen zodra buiten beheer" ging bij mij niet betrouwbaar af (zie
de problemen onderaan). Daarom dwing ik het verwijderen af met een klein script dat bij
aanmelding draait. `Uninstall-AdobeReader.ps1` controleert of de aangemelde gebruiker nog
in `App-AdobeReader` zit, en zo niet de-installeert het Reader stil via de ProductCode.
Reader laat zich netjes verwijderen, dus een extra tool is niet nodig.

Ik heb er een geplande taak voor gemaakt in een GPO die op de client-computer werkt
(**Computerconfiguratie, Voorkeuren, Configuratieschermopties, Geplande taken**):

- Uitvoeren als **NT AUTHORITY\SYSTEM**, met hoogste bevoegdheden.
- Trigger: **Bij aanmelden** (elke gebruiker).
- Actie: `powershell.exe` met
  `-NoProfile -ExecutionPolicy Bypass -File \\DC01\Deploy\Reader\Uninstall-AdobeReader.ps1`

Zo blijft install en uninstall volledig gestuurd door het groepslidmaatschap dat de
chatbot beheert.

### 6. Gedemonstreerd

1. In de chatbot ingelogd als een gebruiker (`anna.devries`) en getypt: *"ik wil adobe reader"*.
2. In **Active Directory Users and Computers** gecontroleerd dat de gebruiker lid werd
   van `App-AdobeReader`.
3. Die gebruiker aangemeld op de client, waarna Reader bij aanmelding installeert.
4. In de chatbot *"verwijder adobe weer"* getypt, waarna de gebruiker uit de groep gaat
   en Reader bij de volgende aanmelding automatisch verdwijnt.

De chatbot meldt bij beide acties dat het bij de volgende aanmelding gebeurt, en dat je
het kunt versnellen met `gpupdate /force` en opnieuw aanmelden.

## Controle op de client

```powershell
whoami                              # toont lab\<gebruiker>
whoami /groups | findstr /i App-    # toont App-AdobeReader (of niet, na verwijderen)
gpresult /r                         # Deploy-AdobeReader onder toegepaste GPO's
```

Visueel: in het Startmenu staat de applicatie erbij (of is hij weg na verwijderen). Het
logje van het verwijder-script staat in `C:\Windows\Temp\Uninstall-AdobeReader.log`.

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
- **Software verscheen pas na `gpupdate /force`.** Software-installatie verwerkt alleen
  synchroon bij een volledige aanmelding (Windows fast-logon), dus soms was een tweede
  aanmelding of een `gpupdate /force` nodig.
- **Verwijderen via de GPO ging niet af.** Het vinkje "verwijderen zodra buiten beheer"
  wordt lokaal op de client vastgelegd op het moment van installeren en achteraf niet
  bijgewerkt, en een mismatch in het product (Acrobat Pro versus Reader, of bitness) zorgt
  dat de GPO het geinstalleerde product niet herkent. Daarom verwijder ik met een eigen
  script op basis van groepslidmaatschap (stap 5), wat wel betrouwbaar werkt.
- **Generiek icoon in plaats van het app-logo.** De icooncache liep achter; na de app
  een keer openen of de client herstarten was het goed.
