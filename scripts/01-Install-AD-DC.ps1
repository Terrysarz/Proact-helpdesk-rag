<#
    01-Install-AD-DC.ps1
    --------------------
    Stap 1 van de AD-lab: statisch IP zetten, AD DS installeren en deze server
    promoveren tot domaincontroller (nieuw forest). De server HERSTART automatisch.

    Draai als Administrator op de verse Windows Server (PowerShell als admin):
        Set-ExecutionPolicy Bypass -Scope Process -Force
        .\01-Install-AD-DC.ps1

    Pas de variabelen hieronder aan je eigen omgeving aan.
    Het script vraagt bij het starten om het DSRM-wachtwoord. Dat staat bewust niet
    in het script.
#>

# ---- Instellingen (pas aan) -------------------------------------------------
$DomainName   = "lab.proact.local"      # nieuw domein (FQDN)
$NetBIOSName  = "LAB"                    # NetBIOS-naam
$ComputerName = "DC01"                   # naam van deze server
$StaticIP     = "192.168.2.10"           # vast IP voor de DC (in jouw 192.168.2.x-net)
$PrefixLength = 24                       # subnet /24 = 255.255.255.0
$Gateway      = "192.168.2.1"            # je router/gateway
$DSRMPassword = Read-Host "Directory Services Restore Mode-wachtwoord (DSRM)" -AsSecureString
# ----------------------------------------------------------------------------

Write-Host "== Netwerk instellen ==" -ForegroundColor Cyan
$adapter = Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | Select-Object -First 1
if (-not $adapter) { throw "Geen actieve netwerkadapter gevonden." }

# Bestaand IP/gateway op deze adapter opruimen en het statische IP zetten.
Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue

New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $StaticIP `
    -PrefixLength $PrefixLength -DefaultGateway $Gateway | Out-Null

# DNS tijdens promotie naar zichzelf (de DC wordt straks de DNS-server).
Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $StaticIP

Write-Host ("IP gezet op {0}/{1}, gateway {2}" -f $StaticIP, $PrefixLength, $Gateway) -ForegroundColor Green

Write-Host "== Computernaam zetten ==" -ForegroundColor Cyan
if ($env:COMPUTERNAME -ne $ComputerName) {
    Rename-Computer -NewName $ComputerName -Force
    Write-Host "Naam wordt '$ComputerName' na de herstart." -ForegroundColor Green
}

Write-Host "== AD DS-rol installeren ==" -ForegroundColor Cyan
Install-WindowsFeature AD-Domain-Services -IncludeManagementTools | Out-Null

Write-Host "== Promoveren tot domaincontroller (nieuw forest) ==" -ForegroundColor Cyan
Import-Module ADDSDeployment
$secure = $DSRMPassword

Install-ADDSForest `
    -DomainName $DomainName `
    -DomainNetbiosName $NetBIOSName `
    -InstallDns `
    -SafeModeAdministratorPassword $secure `
    -DomainMode "WinThreshold" `
    -ForestMode "WinThreshold" `
    -Force

# De server herstart automatisch. Log na de herstart in als domeinbeheerder
# (LAB\Administrator) en draai dan 02-Setup-Lab.ps1.
