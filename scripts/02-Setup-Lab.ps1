<#
    02-Setup-Lab.ps1
    ----------------
    Stap 2 (na de herstart): maakt een OU + 10 gebruikers, een serviceaccount voor
    de chatbot (met reset/unlock-rechten op de OU), en zet LDAPS aan via AD CS.

    Draai als domeinbeheerder (LAB\Administrator) op de DC:
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\02-Setup-Lab.ps1

    Het script vraagt bij het starten om twee wachtwoorden (testgebruikers en
    serviceaccount). Die staan bewust niet in het script.
#>

Import-Module ActiveDirectory

# ---- Instellingen (pas aan) -------------------------------------------------
$OUName          = "ProactLab"               # OU waarin de gebruikers komen
$Company         = "Proact"
$Department      = "Servicedesk"
$UserPassword    = Read-Host "Beginwachtwoord voor de testgebruikers" -AsSecureString
$SvcName         = "svc-chatbot"             # serviceaccount voor de chatbot
$SvcPassword     = Read-Host "Wachtwoord voor het serviceaccount ($SvcName)" -AsSecureString
$InstallADCS     = $true                     # LDAPS aanzetten via een Enterprise Root CA
# ----------------------------------------------------------------------------

$BaseDN   = (Get-ADDomain).DistinguishedName
$NetBIOS  = (Get-ADDomain).NetBIOSName
$Domain   = (Get-ADDomain).DNSRoot
$OUPath   = "OU=$OUName,$BaseDN"

Write-Host "== OU aanmaken ==" -ForegroundColor Cyan
if (-not (Get-ADOrganizationalUnit -Filter "Name -eq '$OUName'" -ErrorAction SilentlyContinue)) {
    New-ADOrganizationalUnit -Name $OUName -Path $BaseDN -ProtectedFromAccidentalDeletion $false
}
Write-Host "OU: $OUPath" -ForegroundColor Green

Write-Host "== 10 gebruikers aanmaken ==" -ForegroundColor Cyan
$people = @(
    @{First="Terry";  Last="Sarpong"},
    @{First="Anna";   Last="de Vries"},
    @{First="Youssef";Last="El Amrani"},
    @{First="Lisa";   Last="Jansen"},
    @{First="Daan";   Last="Bakker"},
    @{First="Priya";  Last="Nair"},
    @{First="Mohammed";Last="Aydin"},
    @{First="Sophie"; Last="Visser"},
    @{First="Luca";   Last="Rossi"},
    @{First="Emma";   Last="de Boer"}
)
$secureUser = $UserPassword
foreach ($p in $people) {
    $sam = ("{0}.{1}" -f $p.First.ToLower(), ($p.Last -replace '\s','').ToLower())
    $sam = $sam.Substring(0, [Math]::Min(20, $sam.Length))   # sAMAccountName max 20 tekens
    $upn = "$sam@$Domain"
    if (Get-ADUser -Filter "SamAccountName -eq '$sam'" -ErrorAction SilentlyContinue) {
        Write-Host "  bestaat al: $sam"; continue
    }
    New-ADUser -Name ("{0} {1}" -f $p.First, $p.Last) `
        -GivenName $p.First -Surname $p.Last `
        -SamAccountName $sam -UserPrincipalName $upn `
        -AccountPassword $secureUser -Enabled $true `
        -Path $OUPath -Company $Company -Department $Department `
        -ChangePasswordAtLogon $false
    Write-Host "  aangemaakt: $sam ($upn)" -ForegroundColor Green
}

Write-Host "== Serviceaccount voor de chatbot ==" -ForegroundColor Cyan
$secureSvc = $SvcPassword
if (-not (Get-ADUser -Filter "SamAccountName -eq '$SvcName'" -ErrorAction SilentlyContinue)) {
    New-ADUser -Name $SvcName -SamAccountName $SvcName -UserPrincipalName "$SvcName@$Domain" `
        -AccountPassword $secureSvc -Enabled $true -Path $OUPath `
        -PasswordNeverExpires $true -CannotChangePassword $true
}
$SvcDN = (Get-ADUser -Identity $SvcName).DistinguishedName

Write-Host "== Rechten delegeren (reset wachtwoord + ontgrendelen) op de OU ==" -ForegroundColor Cyan
# Reset Password, en schrijfrechten op pwdLastSet (force change) en lockoutTime (unlock),
# op alle user-objecten onder de OU.
& dsacls "$OUPath" /I:S /G "${NetBIOS}\${SvcName}:CA;Reset Password;user" | Out-Null
& dsacls "$OUPath" /I:S /G "${NetBIOS}\${SvcName}:WP;pwdLastSet;user"       | Out-Null
& dsacls "$OUPath" /I:S /G "${NetBIOS}\${SvcName}:WP;lockoutTime;user"      | Out-Null
Write-Host "Rechten gedelegeerd aan $NetBIOS\$SvcName" -ForegroundColor Green

if ($InstallADCS) {
    Write-Host "== LDAPS aanzetten via AD CS (Enterprise Root CA) ==" -ForegroundColor Cyan
    Install-WindowsFeature AD-Certificate -IncludeManagementTools | Out-Null
    try {
        Install-AdcsCertificationAuthority -CAType EnterpriseRootCA -Force -ErrorAction Stop
    } catch {
        Write-Host "  CA mogelijk al geinstalleerd: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    # DC een certificaat laten ophalen zodat LDAPS (poort 636) actief wordt.
    & certutil -pulse | Out-Null
    Write-Host "LDAPS wordt actief zodra de DC een certificaat heeft (soms na een herstart)." -ForegroundColor Green
}

Write-Host ""
Write-Host "================= KLAAR: gegevens voor de chatbot =================" -ForegroundColor Cyan
Write-Host ("Domein (FQDN)   : {0}" -f $Domain)
Write-Host ("Base DN         : {0}" -f $BaseDN)
Write-Host ("DC-IP           : (het IP dat je in stap 1 zette, bv 192.168.2.10)")
Write-Host ("Serviceaccount  : {0}\{1}" -f $NetBIOS, $SvcName)
Write-Host ("Service DN      : {0}" -f $SvcDN)
Write-Host ""
Write-Host "Zet op de Linux-VM (chatbot) deze omgevingsvariabelen:" -ForegroundColor Cyan
Write-Host ("  export AD_SERVER={0}" -f "192.168.2.10")
Write-Host ("  export AD_BASE_DN='{0}'" -f $BaseDN)
Write-Host ("  export AD_BIND_DN='{0}'" -f $SvcDN)
Write-Host  "  export AD_BIND_PASSWORD='<serviceaccount-wachtwoord>'"
Write-Host  "  export AD_USE_SSL=true"
Write-Host  "  export AD_VALIDATE_CERT=false   # alleen in het lab"
Write-Host "===================================================================" -ForegroundColor Cyan
