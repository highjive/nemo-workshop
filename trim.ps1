<#
    Reclaim memory on a Windows 11 install that has 8 GB and a 2011 CPU.

    Windows 11 typically idles around 3.2 GB on this hardware. A trimmed
    XFCE install idles around 1.2 GB. You cannot close that gap entirely,
    but you can recover roughly 800 MB to 1 GB, which is the difference
    between running Qwen3-4B alongside KiCad and not.

    Everything here is reversible and none of it touches security updates
    or Defender's real-time protection. Run as Administrator.
#>

param([switch]$WhatIfOnly)

$ErrorActionPreference = "Continue"
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

$before = (Get-CimInstance Win32_OperatingSystem)
$usedMB = [math]::Round(($before.TotalVisibleMemorySize - $before.FreePhysicalMemory)/1024)
Write-Host "in use before: $usedMB MB`n"

if ($WhatIfOnly) { Write-Host "(dry run -- nothing will change)`n" -ForegroundColor Yellow }

# Search indexing. The single biggest win, and useless on a workshop machine
# where everything lives in one projects folder.
Step "disabling Windows Search indexing (~250-400 MB)"
if (-not $WhatIfOnly) {
    Stop-Service WSearch -Force -ErrorAction SilentlyContinue
    Set-Service WSearch -StartupType Disabled -ErrorAction SilentlyContinue
}

# Widgets, news feed, and the rest of the shell furniture.
Step "disabling Widgets and the news feed (~150-250 MB)"
if (-not $WhatIfOnly) {
    $k = "HKLM:\SOFTWARE\Policies\Microsoft\Dsh"
    New-Item $k -Force | Out-Null
    Set-ItemProperty $k -Name AllowNewsAndInterests -Value 0 -Type DWord
    Get-AppxPackage -AllUsers *WebExperience* |
        Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
}

# Visual effects. On the Basic Display Adapter these are drawn by the CPU,
# so they cost more here than on a machine with a working GPU driver.
Step "switching to best-performance visual effects"
if (-not $WhatIfOnly) {
    Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" `
        -Name VisualFXSetting -Value 2 -Type DWord -ErrorAction SilentlyContinue
    Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name DragFullWindows -Value 0 `
        -ErrorAction SilentlyContinue
}

# Startup apps.
Step "listing startup entries -- disable what you do not need"
Get-CimInstance Win32_StartupCommand |
    Select-Object Name, Location | Format-Table -AutoSize

# Page file. With 8 GB and a SATA SSD, a fixed page file avoids the
# resize stalls that look like the machine hanging.
Step "recommending a fixed 8 GB page file"
Write-Host @"
    Set it by hand: System > About > Advanced system settings >
    Performance Settings > Advanced > Virtual memory > Change.
    Uncheck automatic, set initial and maximum both to 8192 MB.
    A fixed size stops Windows resizing it mid-build.
"@

# Defender exclusions. Not disabling Defender -- excluding the build tree,
# where it otherwise scans every object file PlatformIO emits.
Step "adding Defender exclusions for the build tree"
if (-not $WhatIfOnly) {
    foreach ($p in @("C:\Nemo", "$env:USERPROFILE\nemo-projects",
                     "$env:USERPROFILE\.platformio")) {
        Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue
        Write-Host "    excluded $p"
    }
}

Write-Host "`nReboot, then run 'nemo doctor' again." -ForegroundColor Green
Write-Host "Reverse any of this through Services, Settings, or by removing the registry keys above."
