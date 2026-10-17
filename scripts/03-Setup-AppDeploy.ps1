<#
    03-Setup-AppDeploy.ps1
    ----------------------------------------------------------------------------
    Richt de zelfservice software-uitrol in voor de Proact-chatbot (lab).
    Voorbeeld-app: Adobe Acrobat Reader DC.

    Wat dit script doet (op de domaincontroller, als Administrator):
      1. Maakt de security-groep 'App-AdobeReader' in OU=ProactLab.
      2. Geeft het serviceaccount (svc-chatbot) recht om leden van die groep te
         beheren, zodat de chatbot gebruikers kan toevoegen/verwijderen.
      3. Maakt een gedeelde map \\<DC>\Deploy\Reader met de MSI en het
         verwijder-script erin (read-only voor domeincomputers/gebruikers).
      4. Maakt een GPO 'Deploy-AdobeReader', koppelt die aan OU=ProactLab en zet de
         security-filtering zo dat ALLEEN leden van 'App-AdobeReader' de software krijgen.

    Wat je daarna ZELF nog doet (kan niet via PowerShell, zie uitvoer onderaan):
      5. In de GPO-editor de MSI TOEWIJZEN onder Gebruikersconfiguratie.
      6. Een geplande taak (GPO) aanmaken die 'Uninstall-AdobeReader.ps1' draait,
         zodat Reader wordt verwijderd zodra iemand uit de groep is.

    Rolverdeling:
      - De chatbot beheert alleen het GROEPSLIDMAATSCHAP (wie mag de software).
      - De GPO installeert Reader bij aanmelding voor groepsleden.
      - Het verwijder-script haalt Reader weg bij aanmelding voor niet-leden.
    ----------------------------------------------------------------------------
    Gebruik:
      .\03-Setup-AppDeploy.ps1 -MsiPath "C:\Install\AcroRead.msi" `
                               -UninstallScript "C:\Install\Uninstall-AdobeReader.ps1"
    (zonder -MsiPath wordt alleen groep/share/GPO gemaakt; bestanden zet je er later in)
#>

[CmdletBinding()]
param(
    [string]$MsiPath         = "",
    [string]$UninstallScript = "",
    [string]$OU              = "OU=ProactLab,DC=lab,DC=proact,DC=local",
    [string]$GroupName       = "App-AdobeReader",
    [string]$GpoName         = "Deploy-AdobeReader",
    [string]$ShareRoot       = "C:\Deploy",
    [string]$ShareName       = "Deploy",
    [string]$AppSubDir       = "Reader",
    [string]$ServiceAccount  = "svc-chatbot",
    [string]$NetbiosDomain   = "LAB"
)

$ErrorActionPreference = "Stop"
Import-Module ActiveDirectory
Import-Module GroupPolicy

Write-Host "== 1) Security-groep aanmaken ==" -ForegroundColor Cyan
if (-not (Get-ADGroup -Filter "Name -eq '$GroupName'" -ErrorAction SilentlyContinue)) {
    New-ADGroup -Name $GroupName -GroupScope Global -GroupCategory Security -Path $OU `
        -Description "Leden krijgen Adobe Reader via GPO (beheerd door de chatbot)"
    Write-Host "   Groep '$GroupName' aangemaakt in $OU"
} else {
    Write-Host "   Groep '$GroupName' bestaat al."
}

Write-Host "== 1b) Serviceaccount mag leden beheren van deze groep ==" -ForegroundColor Cyan
# Schrijfrecht op het 'member'-attribuut, zodat de chatbot (svc-chatbot) gebruikers
# aan de groep kan toevoegen/verwijderen.
$groupDn = (Get-ADGroup -Identity $GroupName).DistinguishedName
& dsacls "$groupDn" /G "$NetbiosDomain\$($ServiceAccount):WP;member" | Out-Null
Write-Host "   $NetbiosDomain\$ServiceAccount mag nu leden van '$GroupName' beheren."

Write-Host "== 2) Gedeelde map + app-submap ==" -ForegroundColor Cyan
if (-not (Test-Path $ShareRoot)) { New-Item -ItemType Directory -Path $ShareRoot | Out-Null }
$appDir = Join-Path $ShareRoot $AppSubDir
if (-not (Test-Path $appDir)) { New-Item -ItemType Directory -Path $appDir | Out-Null }
# Taal-onafhankelijk: 'Authenticated Users' via well-known SID S-1-5-11, zodat dit ook
# op een Nederlandstalige Windows werkt (daar heet die groep 'Geverifieerde gebruikers').
$authUsers = ([System.Security.Principal.SecurityIdentifier]"S-1-5-11").Translate([System.Security.Principal.NTAccount]).Value
if (-not (Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue)) {
    # Lezen voor alle geauthenticeerde accounts (incl. computeraccounts, nodig voor install).
    New-SmbShare -Name $ShareName -Path $ShareRoot -ReadAccess $authUsers | Out-Null
    Write-Host "   Share \\$env:COMPUTERNAME\$ShareName aangemaakt ($ShareRoot)"
} else {
    Write-Host "   Share '$ShareName' bestaat al."
}
# NTFS-leesrechten voor domeincomputers (install/uninstall draait als SYSTEM/computeraccount).
# SID-notatie (*S-1-5-11) is taal-onafhankelijk.
icacls $ShareRoot /grant "*S-1-5-11:(OI)(CI)R" /T | Out-Null

$uncMsi = ""
if ($MsiPath -ne "") {
    if (-not (Test-Path $MsiPath)) { throw "MSI niet gevonden: $MsiPath" }
    Copy-Item $MsiPath -Destination $appDir -Force
    $msiFile = Split-Path $MsiPath -Leaf
    $uncMsi  = "\\$env:COMPUTERNAME\$ShareName\$AppSubDir\$msiFile"
    Write-Host "   MSI gekopieerd. UNC-pad voor de GPO: $uncMsi"
} else {
    Write-Host "   (Geen -MsiPath opgegeven. Zet de MSI later zelf in $appDir.)" -ForegroundColor Yellow
}

$uncUninstall = "\\$env:COMPUTERNAME\$ShareName\$AppSubDir\Uninstall-AdobeReader.ps1"
if ($UninstallScript -ne "") {
    if (-not (Test-Path $UninstallScript)) { throw "Verwijder-script niet gevonden: $UninstallScript" }
    Copy-Item $UninstallScript -Destination (Join-Path $appDir "Uninstall-AdobeReader.ps1") -Force
    Write-Host "   Verwijder-script gekopieerd. UNC-pad voor de taak: $uncUninstall"
} else {
    Write-Host "   (Geen -UninstallScript opgegeven. Zet Uninstall-AdobeReader.ps1 later in $appDir.)" -ForegroundColor Yellow
}

Write-Host "== 3) GPO aanmaken, koppelen en filteren ==" -ForegroundColor Cyan
if (-not (Get-GPO -Name $GpoName -ErrorAction SilentlyContinue)) {
    New-GPO -Name $GpoName -Comment "Rolt Adobe Reader uit naar leden van $GroupName" | Out-Null
    Write-Host "   GPO '$GpoName' aangemaakt."
} else {
    Write-Host "   GPO '$GpoName' bestaat al."
}
# Koppel aan de OU waar de GEBRUIKERS staan (user-assigned software).
New-GPLink -Name $GpoName -Target $OU -LinkEnabled Yes -ErrorAction SilentlyContinue | Out-Null

# Security-filtering: alleen leden van de groep passen de GPO toe.
# Authenticated Users houdt alleen LEES-recht (vereist sinds MS16-072), geen Apply.
Set-GPPermission -Name $GpoName -TargetName "Authenticated Users" -TargetType Group -PermissionLevel GpoRead -Replace | Out-Null
Set-GPPermission -Name $GpoName -TargetName $GroupName -TargetType Group -PermissionLevel GpoApply | Out-Null
Write-Host "   Filtering gezet: alleen '$GroupName' krijgt de software."

Write-Host ""
Write-Host "KLAAR met het automatische deel." -ForegroundColor Green
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host "NOG ZELF DOEN (eenmalig):" -ForegroundColor Green
Write-Host ""
Write-Host "A) INSTALLEREN - MSI toewijzen in de GPO-editor:" -ForegroundColor Green
Write-Host "   1. Group Policy Management > rechtsklik '$GpoName' > Bewerken."
Write-Host "   2. Gebruikersconfiguratie > Beleid > Software-instellingen > Software-installatie."
Write-Host "   3. Rechtsklik > Nieuw > Pakket... kies de MSI via het UNC-pad:"
if ($uncMsi -ne "") { Write-Host "        $uncMsi" } else { Write-Host "        \\$env:COMPUTERNAME\$ShareName\$AppSubDir\<reader>.msi" }
Write-Host "      LET OP: kies het UNC-pad (\\server\share\...), NIET C:\..."
Write-Host "   4. Distributietype: 'Toegewezen' (Assigned)."
Write-Host "   5. Pakket-eigenschappen > tab Distributie: vink AAN"
Write-Host "        - 'Deze toepassing na aanmelding installeren'"
Write-Host "        - 'De installatie van deze toepassing ongedaan maken als deze niet wordt beheerd'"
Write-Host ""
Write-Host "B) VERWIJDEREN - geplande taak die het verwijder-script draait:" -ForegroundColor Green
Write-Host "   In een GPO die op de CLIENT-COMPUTER werkt (bv. Default Domain Policy):"
Write-Host "   Computerconfiguratie > Voorkeuren > Configuratieschermopties > Geplande taken"
Write-Host "   > Nieuw > Geplande taak (minimaal Windows 7):"
Write-Host "        - Uitvoeren als: NT AUTHORITY\SYSTEM, hoogste bevoegdheden,"
Write-Host "          'Uitvoeren ongeacht of gebruiker is aangemeld'."
Write-Host "        - Trigger: Bij aanmelden (Elke gebruiker)."
Write-Host "        - Actie: 'powershell.exe' starten met argumenten:"
Write-Host "            -NoProfile -ExecutionPolicy Bypass -File $uncUninstall"
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host "Testen via de chatbot:" -ForegroundColor Green
Write-Host "  'installeer adobe'  -> aanmelden -> Reader installeert."
Write-Host "  'verwijder adobe'   -> aanmelden -> Reader wordt verwijderd (en komt niet terug)."
Write-Host "  Versnellen op de client kan met: gpupdate /force  + opnieuw aanmelden."
