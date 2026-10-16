<#
    Fix-RDP.ps1  — Remote Desktop controleren en inschakelen (lab)
    ----------------------------------------------------------------------------
    DRAAI DIT OP DE SERVER ZELF, via de Proxmox-console (noVNC), in een
    PowerShell die je als Administrator opent. Niet via RDP (dat werkt nu juist niet).

    Het script:
      1. Toont het huidige IP (controle dat je op 192.168.2.10 zit).
      2. Schakelt Remote Desktop in (fDenyTSConnections = 0).
      3. Zet de RDP-firewallregels aan voor ALLE profielen.
      4. Zet het netwerkprofiel op Private (Public blokkeert RDP standaard).
      5. Zorgt dat de RDP-services draaien en automatisch starten.
      6. Controleert of er nu echt op poort 3389 wordt geluisterd.
#>

$ErrorActionPreference = "SilentlyContinue"
Write-Host "==================== RDP CHECK & FIX ====================" -ForegroundColor Cyan

Write-Host "`n[1] Huidige IP-adressen:" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "169.*" -and $_.IPAddress -ne "127.0.0.1" } |
    Select-Object IPAddress, InterfaceAlias | Format-Table -AutoSize

Write-Host "[2] Remote Desktop inschakelen..." -ForegroundColor Cyan
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' `
    -Name 'fDenyTSConnections' -Value 0
$deny = (Get-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections).fDenyTSConnections
Write-Host ("    fDenyTSConnections = {0}  (0 = RDP toegestaan)" -f $deny)

Write-Host "[3] Firewallregels voor Remote Desktop aanzetten (alle profielen)..." -ForegroundColor Cyan
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Set-NetFirewallRule -DisplayGroup "Remote Desktop" -Enabled True -Profile Any
Get-NetFirewallRule -DisplayGroup "Remote Desktop" |
    Select-Object DisplayName, Enabled, Profile | Format-Table -AutoSize

Write-Host "[4] Netwerkprofiel op Private zetten (Public blokkeert RDP)..." -ForegroundColor Cyan
Get-NetConnectionProfile | ForEach-Object {
    Set-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -NetworkCategory Private
}
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory | Format-Table -AutoSize

Write-Host "[5] RDP-services starten en op automatisch zetten..." -ForegroundColor Cyan
foreach ($svc in "TermService","UmRdpService") {
    Set-Service -Name $svc -StartupType Automatic
    Start-Service -Name $svc
    $s = Get-Service -Name $svc
    Write-Host ("    {0}: {1}" -f $svc, $s.Status)
}

Write-Host "[6] Luistert er iets op poort 3389?" -ForegroundColor Cyan
$listen = Get-NetTCPConnection -LocalPort 3389 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    Write-Host "    JA — poort 3389 luistert. RDP zou nu moeten werken." -ForegroundColor Green
    $listen | Select-Object LocalAddress, LocalPort, State | Format-Table -AutoSize
} else {
    Write-Host "    NEE — poort 3389 luistert nog niet. Herstart de server en draai dit script opnieuw." -ForegroundColor Yellow
}

Write-Host "`n==================== KLAAR ====================" -ForegroundColor Cyan
Write-Host "Test vanaf je Mac:  nc -vz 192.168.2.10 3389   (moet 'succeeded' geven)"
Write-Host "Verbind daarna met de Windows-app (Microsoft Remote Desktop) naar 192.168.2.10."
