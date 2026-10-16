<#
    03-Setup-AppDeploy.ps1
    ----------------------------------------------------------------------------
    Richt de zelfservice software-uitrol in voor de Proact-chatbot (lab).

    Wat dit script doet (op de domaincontroller, als Administrator):
      1. Maakt de security-groep 'App-AdobeReader' in OU=ProactLab.
      2. Maakt een gedeelde map \\<DC>\Deploy met de MSI('s) erin (read-only voor
         domeincomputers/gebruikers).
      3. Maakt een GPO 'Deploy-AdobeReader', koppelt die aan OU=ProactLab en zet de
         security-filtering zo dat ALLEEN leden van 'App-AdobeReader' de software krijgen.

    Wat je daarna ZELF nog doet (kan niet via PowerShell — zie README onderaan):
      4. In de GPO-editor de MSI toewijzen onder
         Gebruikersconfiguratie > Beleid > Softwareinstellingen > Software-installatie.

    De chatbot voegt een gebruiker toe aan 'App-AdobeReader'; bij de volgende
    aanmelding rolt de GPO Adobe Reader uit.
    ----------------------------------------------------------------------------
    Gebruik:
      .\03-Setup-AppDeploy.ps1 -MsiPath "C:\Install\AcroRdrDC.msi"
    (zonder -MsiPath wordt alleen groep/share/GPO gemaakt; MSI zet je er later in)
#>

[CmdletBinding()]
param(
    [string]$MsiPath = "",
    [string]$OU      = "OU=ProactLab,DC=lab,DC=proact,DC=local",
    [string]$GroupName = "App-AdobeReader",
    [string]$GpoName   = "Deploy-AdobeReader",
    [string]$ShareRoot = "C:\Deploy",
    [string]$ShareName = "Deploy",
    [string]$ServiceAccount = "svc-chatbot",
    [string]$NetbiosDomain  = "LAB"
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

Write-Host "== 2) Gedeelde map voor de MSI('s) ==" -ForegroundColor Cyan
if (-not (Test-Path $ShareRoot)) { New-Item -ItemType Directory -Path $ShareRoot | Out-Null }
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
# NTFS-leesrechten voor domeincomputers (software-install draait als SYSTEM/computeraccount).
# SID-notatie (*S-1-5-11) is taal-onafhankelijk.
icacls $ShareRoot /grant "*S-1-5-11:(OI)(CI)R" /T | Out-Null

$uncMsi = ""
if ($MsiPath -ne "") {
    if (-not (Test-Path $MsiPath)) { throw "MSI niet gevonden: $MsiPath" }
    Copy-Item $MsiPath -Destination $ShareRoot -Force
    $msiFile = Split-Path $MsiPath -Leaf
    $uncMsi  = "\\$env:COMPUTERNAME\$ShareName\$msiFile"
    Write-Host "   MSI gekopieerd. UNC-pad voor de GPO: $uncMsi"
} else {
    Write-Host "   (Geen -MsiPath opgegeven. Zet de MSI later zelf in $ShareRoot.)" -ForegroundColor Yellow
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
Write-Host "NOG ZELF DOEN (eenmalig) in de Group Policy Management Editor:" -ForegroundColor Green
Write-Host "  1. Open 'Group Policy Management' > rechtsklik '$GpoName' > Bewerken."
Write-Host "  2. Gebruikersconfiguratie > Beleid > Softwareinstellingen > Software-installatie."
Write-Host "  3. Rechtsklik > Nieuw > Pakket... en kies de MSI via het UNC-pad:"
if ($uncMsi -ne "") {
    Write-Host "       $uncMsi"
} else {
    Write-Host "       \\$env:COMPUTERNAME\$ShareName\<jouw-reader>.msi"
}
Write-Host "     LET OP: kies het UNC-pad (\\server\share\...), NIET C:\..."
Write-Host "  4. Kies 'Toegewezen' (Assigned). Klaar."
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host "Testen: voeg een testgebruiker toe aan '$GroupName' (of via de chatbot),"
Write-Host "meld die gebruiker aan op een domein-client; Reader installeert bij aanmelding."
