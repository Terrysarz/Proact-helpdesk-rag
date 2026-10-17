# Uninstall-AdobeReader.ps1
# -----------------------------------------------------------------------------
# Verwijdert Adobe Acrobat Reader DC zodra de aangemelde gebruiker GEEN lid
# (meer) is van de groep App-AdobeReader. Reader DC laat zich stil verwijderen
# via msiexec, dus hier is geen cleaner-tool voor nodig.
#
# Draaien: geplande taak (GPO) die BIJ AANMELDEN start en als
#          NT AUTHORITY\SYSTEM loopt (geen admin-prompt, want al verhoogd).
#
# Let op bij de install-kant: laat Reader via GPSI alleen uitrollen onder
# GEBRUIKERSconfiguratie, security-gefilterd op App-AdobeReader. Dan stopt de
# uitrol zodra iemand uit de groep is en reinstalleert hij NIET nadat dit
# script hem heeft verwijderd. (Een COMPUTER-toegewezen uitrol zet hem na een
# herstart gewoon terug; die vecht dan met dit script.)
# -----------------------------------------------------------------------------

$GroupName    = "App-AdobeReader"
# Bekende ProductCode van Reader DC; wordt zo nodig overschreven door wat echt
# in het register staat (robuuster over versies heen).
$ProductCode  = "{AC76BA86-7AD7-1033-7B44-AC0F074E4100}"
$NameMatch    = "Adobe Acrobat Reader*"
$LogFile      = "C:\Windows\Temp\Uninstall-AdobeReader.log"

function Log($m) { "$(Get-Date -Format s)  $m" | Out-File -FilePath $LogFile -Append -Encoding utf8 }

function Get-ReaderUninstall {
    # Zoekt de echte ProductCode/uninstall van een geinstalleerde Reader DC.
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($k in $keys) {
        $hit = Get-ItemProperty $k -ErrorAction SilentlyContinue |
               Where-Object { $_.DisplayName -like $NameMatch } | Select-Object -First 1
        if ($hit) { return $hit.PSChildName }   # dit is de {ProductCode}
    }
    return $null
}

try {
    # 1) Wie is er interactief aangemeld? (SYSTEM draait de taak.)
    $who = $null
    for ($i = 0; $i -lt 10 -and -not $who; $i++) {
        $who = (Get-CimInstance Win32_ComputerSystem).UserName
        if (-not $who) { Start-Sleep -Seconds 3 }
    }
    if (-not $who) { Log "Geen aangemelde gebruiker; stop."; return }
    $sam = $who.Split('\')[-1]
    Log "Gebruiker: $who"

    # 2) Zit de gebruiker in App-AdobeReader?
    $inGroup = $false
    $searcher = [ADSISearcher]"(&(objectClass=user)(sAMAccountName=$sam))"
    $null = $searcher.PropertiesToLoad.Add("memberof")
    $res = $searcher.FindOne()
    if ($res) {
        foreach ($g in $res.Properties["memberof"]) {
            if ($g -match "CN=$GroupName,") { $inGroup = $true; break }
        }
    }

    # 3) Staat Reader geinstalleerd? (en haal de echte ProductCode op)
    $code = Get-ReaderUninstall
    $installed = [bool]$code
    if ($code) { $ProductCode = $code }
    Log "Lid van $GroupName : $inGroup | Reader geinstalleerd : $installed | code: $ProductCode"

    # 4) Niet in de groep EN toch geinstalleerd -> stil verwijderen.
    if ((-not $inGroup) -and $installed) {
        Log "Verwijderen Reader ($ProductCode)..."
        $p = Start-Process msiexec.exe -ArgumentList '/x', $ProductCode, '/qn', '/norestart' -Wait -PassThru
        Log "Uninstall exitcode $($p.ExitCode)."
    } else {
        Log "Geen actie nodig."
    }
}
catch {
    Log "FOUT: $($_.Exception.Message)"
}
