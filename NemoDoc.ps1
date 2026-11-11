<#
    NemoDoc -- check, install, repair, launch.

    Run this every time. It is the only thing you need to run.

    Each pass it walks the same list of components, tests each one, fixes
    what is broken or missing, and re-tests. If everything passes it starts
    Nemo. If anything fails it stops and tells you exactly what, rather than
    launching something half-built.

    Written for a Fujitsu Lifebook AH531 running Windows 11: two Sandy
    Bridge cores, 8 GB DDR3-1333, Intel HD Graphics with no driver. Three
    things on that machine need handling that do not arise elsewhere, and
    NemoDoc handles all three automatically:

      * the llama.cpp build must match the CPU's instruction set
      * KiCad needs a software OpenGL renderer, because Windows has none
      * memory is tight enough that the mode is chosen by what is free

    Targets Windows PowerShell 5.1, which is what Windows 11 ships. No
    PowerShell 7 syntax anywhere in here.

    Usage:
      NemoDoc.cmd                double-click, or run from a terminal
      .\NemoDoc.ps1 -CheckOnly   diagnose without changing anything
      .\NemoDoc.ps1 -NoLaunch    fix everything, do not start Nemo
      .\NemoDoc.ps1 -Mode design choose the mode instead of auto-selecting
      .\NemoDoc.ps1 -SkipModels  do not download GGUFs this pass (nor the Artist's)
      .\NemoDoc.ps1 -SkipGames   do not download RetroArch for the Gaming department (430 MB)
      .\NemoDoc.ps1 -SkipPrint   do not download OrcaSlicer for the Print Shop (171 MB)
      .\NemoDoc.ps1 -SkipFilm    do not download ffmpeg for the Film Studio (35 MB)
      .\NemoDoc.ps1 -SkipDrawings  do not download CADCraft for the Workshop's drawings (74 MB)
      .\NemoDoc.ps1 -SkipBooks   do not download WordCraft for books and the pack PDF (118 MB)
      .\NemoDoc.ps1 -SkipArtist  do not download the Artist's image model (2 GB);
                                story covers then say what is missing
#>

[CmdletBinding()]
param(
    [string]$Prefix    = "C:\Nemo",
    [string]$Mode      = "",
    [switch]$CheckOnly,
    [switch]$NoLaunch,
    [switch]$SkipModels,
    [switch]$SkipArtist,
    [switch]$SkipGames,
    [switch]$SkipPrint,
    [switch]$SkipFilm,
    [switch]$SkipGpu,
    [switch]$SkipPcb,
    [switch]$SkipDrawings,
    [switch]$SkipBooks,
    [switch]$Force
)

# Do NOT stop on first error. The whole point is to survey everything, fix
# what can be fixed, and report the rest. A single failed download should
# not abort the run.
$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"   # much faster downloads on 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root    = $PSScriptRoot
$LogPath = Join-Path $Prefix "nemodoc.log"
$Script:Findings = @()

# ====================================================================
#  Output
# ====================================================================

function Say {
    param([string]$Text, [string]$Colour = "Gray")
    Write-Host $Text -ForegroundColor $Colour
}
function Head {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("-" * $Text.Length) -ForegroundColor DarkCyan
}
function Log {
    param([string]$Text)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Text
    try { Add-Content -Path $LogPath -Value $line -ErrorAction SilentlyContinue } catch {}
}
function Note {
    param([string]$Status, [string]$Name, [string]$Detail = "")
    $Script:Findings += [PSCustomObject]@{ Status = $Status; Name = $Name; Detail = $Detail }
    Log "$Status $Name -- $Detail"
    switch ($Status) {
        "OK"   { Say ("  [ ok ] {0}" -f $Name) "Green" }
        "FIX"  { Say ("  [fixed] {0}" -f $Name) "Green" }
        "WARN" { Say ("  [warn] {0}" -f $Name) "Yellow"; Say ("         $Detail") "DarkYellow" }
        "FAIL" { Say ("  [FAIL] {0}" -f $Name) "Red";    Say ("         $Detail") "DarkYellow" }
        "INFO" { Say ("  [    ] {0}: {1}" -f $Name, $Detail) "Gray" }
    }
}

# ====================================================================
#  Elevation
# ====================================================================

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin) -and -not $CheckOnly) {
    Say "NemoDoc needs Administrator to install KiCad and Python. Relaunching..." "Yellow"
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    foreach ($kv in $PSBoundParameters.GetEnumerator()) {
        if ($kv.Value -is [switch]) { if ($kv.Value) { $argList += "-$($kv.Key)" } }
        else { $argList += @("-$($kv.Key)", "`"$($kv.Value)`"") }
    }
    try {
        Start-Process powershell -Verb RunAs -ArgumentList $argList
    } catch {
        Say "Could not elevate. Right-click NemoDoc.cmd and choose Run as administrator." "Red"
        Read-Host "Press Enter to close"
    }
    exit
}

New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
Log "=== NemoDoc pass started ==="

# ====================================================================
#  Helpers
# ====================================================================

function Refresh-Path {
    # winget and MSI installers change the machine PATH, but the running
    # process keeps its own copy. Without this, every tool installed during
    # this pass appears missing for the rest of it.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine, $user | Where-Object { $_ }) -join ";"
}

function Find-Exe {
    param([string[]]$Names, [string[]]$ExtraDirs)
    foreach ($n in $Names) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    foreach ($d in $ExtraDirs) {
        if (-not $d) { continue }
        foreach ($n in $Names) {
            $p = Join-Path $d $n
            if (Test-Path $p) { return $p }
        }
    }
    return $null
}

function Get-File {
    param([string]$Url, [string]$Dest, [string]$Label)
    # BITS first: it resumes, shows progress, and survives a flaky link --
    # which matters when a model file is gigabytes and the Wi-Fi is 2011
    # vintage. WebClient as the fallback.
    $tmp = "$Dest.part"
    if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
    Say "        downloading $Label" "DarkGray"
    try {
        Import-Module BitsTransfer -ErrorAction Stop
        Start-BitsTransfer -Source $Url -Destination $tmp -Description $Label -ErrorAction Stop
    } catch {
        try {
            $wc = New-Object System.Net.WebClient
            $wc.Headers.Add("User-Agent", "NemoDoc")
            $wc.DownloadFile($Url, $tmp)
        } catch {
            Log "download failed $Url : $($_.Exception.Message)"
            return $false
        }
    }
    if (-not (Test-Path $tmp)) { return $false }
    if ((Get-Item $tmp).Length -lt 1024) {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        return $false
    }
    Move-Item $tmp $Dest -Force
    return $true
}

function Install-Package {
    param([string]$WingetId, [string]$DirectUrl, [string]$Label, [string[]]$SilentArgs)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say "        winget: $WingetId" "DarkGray"
        $out = winget install --id $WingetId --silent --accept-package-agreements `
                  --accept-source-agreements --disable-interactivity 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Refresh-Path
            return $true
        }
        # winget was found and ran, but did not actually install the package.
        # This used to be discarded ($null = ... ; return $true unconditionally),
        # so a real failure looked identical to success: the caller's own
        # after-the-fact check (Find-KiCad, etc.) would then correctly report
        # FAIL, but "see the summary below" had nothing to show, and the
        # $DirectUrl fallback just below was never reached even when one
        # existed (Python's python.org installer, in particular). D100: five
        # identical, undiagnosable KiCad failures in the operator's own log
        # were this exact gap.
        $tail = (($out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) -join " | ")
        Note "WARN" "winget $Label" ("exit ${LASTEXITCODE}: " + $(if ($tail) { $tail } else { "no output" }))
    }
    if (-not $DirectUrl) { return $false }
    # winget is absent on plenty of bypass installs, because App Installer
    # comes from the Store and the Store is often missing. Fall back.
    $file = Join-Path $env:TEMP (Split-Path $DirectUrl -Leaf)
    if (-not (Get-File $DirectUrl $file $Label)) { return $false }
    Say "        running installer for $Label" "DarkGray"
    if ($file -like "*.msi") {
        Start-Process msiexec -ArgumentList @("/i", "`"$file`"", "/qn", "/norestart") -Wait
    } else {
        Start-Process $file -ArgumentList $SilentArgs -Wait
    }
    Refresh-Path
    return $true
}

function Expand-Zip {
    param([string]$Zip, [string]$Dest)
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Dest)
        return $true
    } catch {
        try { Expand-Archive -Path $Zip -DestinationPath $Dest -Force; return $true }
        catch { return $false }
    }
}

# ====================================================================
#  1. System survey
# ====================================================================

Head "System"

$cpuInfo = Get-CimInstance Win32_Processor | Select-Object -First 1
$osInfo  = Get-CimInstance Win32_OperatingSystem
$gpuInfo = Get-CimInstance Win32_VideoController | Select-Object -First 1
$totalMB = [math]::Round($osInfo.TotalVisibleMemorySize / 1024)
$freeMB  = [math]::Round($osInfo.FreePhysicalMemory / 1024)

Note "INFO" "CPU" $cpuInfo.Name
Note "INFO" "GPU" $gpuInfo.Name
Note "INFO" "Memory" ("{0} MB installed, {1} MB free" -f $totalMB, $freeMB)

# CPU feature bits. IsProcessorFeaturePresent is the documented way to ask,
# and it is exactly what decides which llama.cpp build will run.
$sig = @"
using System;
using System.Runtime.InteropServices;
public class NemoCpu {
    [DllImport("kernel32.dll")]
    public static extern bool IsProcessorFeaturePresent(uint feature);
}
"@
if (-not ("NemoCpu" -as [type])) { Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue }

$HasSse42 = $false; $HasAvx = $false; $HasAvx2 = $false
try {
    $HasSse42 = [NemoCpu]::IsProcessorFeaturePresent(38)
    $HasAvx   = [NemoCpu]::IsProcessorFeaturePresent(39)
    $HasAvx2  = [NemoCpu]::IsProcessorFeaturePresent(40)
} catch { }

if ($HasAvx2) {
    $IsaTag = "avx2"
    Note "INFO" "Instruction set" "AVX2 present"
} elseif ($HasAvx) {
    $IsaTag = "avx"
    Note "INFO" "Instruction set" "AVX but no AVX2 -- Sandy Bridge Core. llama.cpp will load its sandybridge backend."
} elseif ($HasSse42) {
    $IsaTag = "noavx"
    Note "WARN" "No AVX at all" ("This is a Sandy Bridge Celeron or Pentium, where Intel fused AVX " +
        "off along with Turbo and hyper-threading. llama.cpp will load its sse42 backend. Expect " +
        "roughly half the throughput of a Core i5 of the same generation.")
} else {
    $IsaTag = "noavx"
    Note "WARN" "Instruction set unknown" "Falling back to the SSE-only build, which runs anywhere."
}

# Memory channels. Capacity is only half the story: a single stick halves
# bandwidth, and token generation is bandwidth-bound.
$dimms = @(Get-CimInstance Win32_PhysicalMemory)
if ($dimms.Count -ge 2) {
    Note "OK" "Dual channel" ("{0} DIMMs populated" -f $dimms.Count)
} elseif ($dimms.Count -eq 1) {
    Note "WARN" "Single channel" ("One DIMM populated. A matched second stick roughly doubles " +
        "token throughput on this machine -- a bigger difference than the extra capacity.")
}

if ($totalMB -lt 5000) {
    Note "FAIL" "Not enough memory" ("{0} MB installed. Windows alone wants around 3.2 GB. Fit a " +
        "matched pair of 4 GB DDR3-1333 SO-DIMMs before going further." -f $totalMB)
} elseif ($totalMB -lt 7000) {
    Note "WARN" "Under 8 GB" "Tiny mode only. The design and build modes will not load."
}

$freeDiskGB = [math]::Round((Get-PSDrive -Name ($Prefix.Substring(0,1))).Free / 1GB, 1)
if ($freeDiskGB -lt 12) {
    Note "WARN" "Disk space" ("{0} GB free on {1}. Models alone are about 6.5 GB." -f $freeDiskGB, $Prefix.Substring(0,1))
} else {
    Note "INFO" "Disk space" ("{0} GB free" -f $freeDiskGB)
}

# ====================================================================
#  2. Components
# ====================================================================

Head "Components"

$Venv      = Join-Path $Prefix "venv"
$VenvPy    = Join-Path $Venv "Scripts\python.exe"
$VenvPip   = Join-Path $Venv "Scripts\pip.exe"
$EngineDir = Join-Path $Prefix "engine"
$ModelDir  = Join-Path $Prefix "models"

function Step {
    param(
        [string]$Name,
        [scriptblock]$Test,
        [scriptblock]$Fix,
        [bool]$Required = $true
    )
    if (& $Test) { Note "OK" $Name ""; return $true }
    if ($CheckOnly) {
        $sev = "WARN"
        if ($Required) { $sev = "FAIL" }
        Note $sev $Name "missing (check-only, not fixing)"
        return $false
    }
    Say ("  ...... fixing {0}" -f $Name) "DarkGray"
    try { & $Fix } catch { Log "fix threw for $Name : $($_.Exception.Message)" }
    Refresh-Path
    if (& $Test) { Note "FIX" $Name "installed"; return $true }
    if ($Required) { Note "FAIL" $Name "could not install automatically -- see the summary below" }
    else           { Note "WARN" $Name "not installed; optional" }
    return $false
}

# --- Python ---------------------------------------------------------
$PyExe = $null
Step "Python 3.11+" {
    # D202: Python's own install manager (python.org, 2025 on) puts it in
    # %LOCALAPPDATA%\Python\pythoncore-3.N-64; the AH531's 3.14 is there and
    # was not found, so NemoDoc would have installed a second Python.
    $core = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Python") -Directory `
                 -Filter "pythoncore-3.*" -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending | ForEach-Object { $_.FullName })
    # Each candidate is asked its version: the Microsoft Store stub is on PATH
    # by default and is not Python, and it must not hide one that is.
    $dirs = @("$env:LOCALAPPDATA\Programs\Python\Python312",
              "$env:LOCALAPPDATA\Programs\Python\Python311",
              "C:\Python312", "C:\Python311") + $core
    $cands = @(Find-Exe @("python.exe", "python3.exe") @()) +
             @($dirs | ForEach-Object { Join-Path $_ "python.exe" } | Where-Object { Test-Path $_ })
    foreach ($c in ($cands | Where-Object { $_ })) {
        $v = & $c -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if (-not $v) { continue }
        $parts = "$v".Trim().Split(".")
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { $script:PyExe = $c; return $true }
    }
    $script:PyExe = $null
    return $false
} {
    Install-Package "Python.Python.3.12" `
        "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" `
        "Python 3.12" @("/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_pip=1")
} $true | Out-Null

# --- KiCad ----------------------------------------------------------
function Find-KiCad {
    # KiCad installs into a folder named for its major version and never
    # adds itself to PATH. An earlier revision looked only in 9.0 and 8.0,
    # so the current release (10.x) was installed but reported missing.
    # Search every version folder and every install root, newest first.
    $roots = @("$env:ProgramFiles\KiCad", "${env:ProgramFiles(x86)}\KiCad",
               "$env:LOCALAPPDATA\Programs\KiCad")
    $hits = @()
    foreach ($r in $roots) {
        if ($r -and (Test-Path $r)) {
            $hits += Get-ChildItem -Path $r -Filter "kicad-cli.exe" -Recurse `
                       -Depth 3 -ErrorAction SilentlyContinue
        }
    }
    # Registry, for installs to a non-default drive or folder.
    $keys = @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
              "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
              "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*")
    foreach ($k in $keys) {
        Get-ItemProperty $k -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "KiCad*" -and $_.InstallLocation } |
            ForEach-Object {
                $c = Join-Path $_.InstallLocation "bin\kicad-cli.exe"
                if (Test-Path $c) { $hits += Get-Item $c }
            }
    }
    $onPath = Get-Command kicad-cli.exe -ErrorAction SilentlyContinue
    if ($onPath) { $hits += Get-Item $onPath.Source }
    if ($hits.Count -eq 0) { return $null }
    # Sort on the version FOLDER under KiCad, numerically, so 10.0 beats 9.0.
    # An earlier revision used every digit in the path: "Program Files (x86)"
    # sorted as version 86, and a username with digits in it outranked a
    # real 10.0 install.
    return ($hits | Sort-Object {
        $m = [regex]::Match($_.FullName, '[\\/]KiCad[\\/](\d+(?:\.\d+)*)[\\/]')
        if ($m.Success) {
            ($m.Groups[1].Value -split '\.' | ForEach-Object { "{0:D6}" -f [int]$_ }) -join "."
        } else { "000000" }
    } | Select-Object -Last 1).FullName
}

$Script:KiCadCli = $null
Step "KiCad" {
    $script:KiCadCli = Find-KiCad
    return ($null -ne $script:KiCadCli)
} {
    Install-Package "KiCad.KiCad" $null "KiCad" @()
} $true | Out-Null

if ($KiCadCli) {
    Note "INFO" "KiCad found" $KiCadCli
    # Put its bin folder on the user PATH, so Nemo and anything else can
    # call kicad-cli without knowing the version folder. Also exported for
    # this session, and as NEMO_KICAD_CLI for an exact match.
    $kbin = Split-Path $KiCadCli -Parent
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    # D201: -CheckOnly changes nothing, the user PATH included.
    if ($userPath -notlike "*$kbin*" -and $CheckOnly) {
        Note "INFO" "KiCad not on PATH" "would add $kbin (check-only, not fixing)"
    } elseif ($userPath -notlike "*$kbin*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$kbin", "User")
        Note "FIX" "KiCad added to PATH" $kbin
    }
    [Environment]::SetEnvironmentVariable("NEMO_KICAD_CLI", $KiCadCli, "User")
    $env:NEMO_KICAD_CLI = $KiCadCli
    Refresh-Path
}

# --- Graphviz -------------------------------------------------------
Step "Graphviz" {
    $null -ne (Find-Exe @("dot.exe") @(
        "C:\Program Files\Graphviz\bin", "C:\Program Files (x86)\Graphviz\bin"))
} {
    Install-Package "Graphviz.Graphviz" $null "Graphviz" @()
} $true | Out-Null

# --- Git (optional) -------------------------------------------------
Step "Git" {
    $null -ne (Find-Exe @("git.exe") @("C:\Program Files\Git\cmd"))
} {
    Install-Package "Git.Git" $null "Git" @("/VERYSILENT", "/NORESTART")
} $false | Out-Null

# --- virtual environment --------------------------------------------
Step "Python environment" {
    Test-Path $VenvPip
} {
    if ($PyExe) { & $PyExe -m venv $Venv }
} $true | Out-Null

# --- python dependencies --------------------------------------------
Step "Python packages" {
    if (-not (Test-Path $VenvPy)) { return $false }
    $probe = & $VenvPy -c "import yaml, trimesh, numpy, scipy, rtree, cryptography, pypdf; print('ok')" 2>$null
    return ($probe -eq "ok")
} {
    & $VenvPip install --quiet --upgrade pip wheel
    # Installed one at a time: on two Sandy Bridge cores a combined install
    # that fails halfway gives no clue which package broke.
    foreach ($pkg in @("pyyaml", "cryptography", "pypdf", "numpy", "scipy", "rtree", "trimesh", "wireviz", "platformio")) {
        Say "        pip: $pkg" "DarkGray"
        & $VenvPip install --quiet $pkg 2>&1 | Out-Null
    }
} $true | Out-Null

# --- schematic and enclosure tools ----------------------------------
# D134: the electrical step writes a SKiDL script and the enclosure step a
# CadQuery one, and nothing installed either library, so on a fresh install
# both steps could only skip. Their own step, and optional: CadQuery brings
# a large geometry kernel, and a failure here must not stop Nemo launching.
# Run on the AH531 with SKiDL 2.3.0 and CadQuery 2.8.0; later releases are
# not verified. Looked up rather than imported: importing SKiDL writes log
# files into the working directory, and importing CadQuery takes half a
# minute on this CPU.
Step "Schematic and enclosure tools (SKiDL, CadQuery)" {
    if (-not (Test-Path $VenvPy)) { return $false }
    Push-Location $env:TEMP
    try {
        $probe = & $VenvPy -I -c "import importlib.util as u; print('ok' if u.find_spec('skidl') and u.find_spec('cadquery') and u.find_spec('OCP') else 'no')" 2>$null
    } finally { Pop-Location }
    return ($probe -eq "ok")
} {
    foreach ($pkg in @("skidl", "cadquery")) {
        Say "        pip: $pkg" "DarkGray"
        & $VenvPip install --quiet $pkg 2>&1 | Out-Null
    }
} $false | Out-Null

# --- casting, for the Theatre -------------------------------------
# pychromecast finds a Chromecast and tells it what to play (nemo/cast.py).
# Optional: without it the Theatre still plays here and opens Chrome.
# 14.0.10 is the version Nemo was written against (2026-10-21).
Step "Casting (pychromecast)" {
    if (-not (Test-Path $VenvPy)) { return $false }
    $probe = & $VenvPy -I -c "import importlib.util as u; print('ok' if u.find_spec('pychromecast') else 'no')" 2>$null
    return ($probe -eq "ok")
} {
    Say "        pip: pychromecast" "DarkGray"
    & $VenvPip install --quiet "pychromecast==14.0.10" 2>&1 | Out-Null
} $false | Out-Null

# --- the Science department ---------------------------------------
# sympy (algebra), Pint (units) and openpyxl (spreadsheets), with what they
# need, at the versions approved and checked against PyPI's hashes on
# 2026-10-22 (nemo/science.py); typing_extensions 4.16.0 added 2026-11-04
# (D208: Pint, flexcache and flexparser import it). About 7.5 MB, pure
# Python. Optional: without
# them the Science department says what is missing.
Step "Science (sympy, Pint, openpyxl)" {
    if (-not (Test-Path $VenvPy)) { return $false }
    $probe = & $VenvPy -I -c "import importlib.util as u; print('ok' if all(u.find_spec(m) for m in ('sympy','pint','openpyxl','typing_extensions')) else 'no')" 2>$null
    return ($probe -eq "ok")
} {
    Say "        pip: sympy, Pint, openpyxl" "DarkGray"
    & $VenvPip install --quiet --no-deps "openpyxl==3.1.5" "et-xmlfile==2.0.0" "sympy==1.14.0" "mpmath==1.3.0" "Pint==0.26.2" "flexcache==0.3" "flexparser==0.4" "platformdirs==4.13.5" "typing_extensions==4.16.0" 2>&1 | Out-Null
} $false | Out-Null

# --- nemo itself ----------------------------------------------------
# Installed from a copy under $Prefix\app, so Nemo keeps working after the
# downloaded folder is deleted. An earlier revision pointed at the download.
$AppDir  = Join-Path $Prefix "app"
$NemoCmd = Join-Path $Venv "Scripts\nemo.cmd"

function Test-NemoInstalled {
    # Must test the INSTALLATION, not the folder NemoDoc happens to run from.
    # NemoDoc.cmd starts in the NemoWin folder, which contains nemo\, so a
    # plain 'python -c "import nemo"' succeeded there with nothing installed.
    # The step was marked done, the fix never ran, and no 'nemo' command was
    # ever created. -I stops Python adding the working directory to its path,
    # and running from TEMP removes it twice over.
    if (-not (Test-Path $VenvPy))  { return $false }
    if (-not (Test-Path $NemoCmd)) { return $false }
    Push-Location $env:TEMP
    try {
        $where = & $VenvPy -I -c "import nemo, os; print(os.path.dirname(os.path.dirname(nemo.__file__)))" 2>$null
    } finally { Pop-Location }
    if (-not $where) { return $false }
    return ((Resolve-Path $where.Trim()).Path -eq (Resolve-Path $AppDir -ErrorAction SilentlyContinue).Path)
}

# Refresh the installed copy whenever NemoDoc runs from a different folder,
# so running a newer download's NemoDoc updates Nemo.
if ((Resolve-Path $Root).Path -ne (Resolve-Path $AppDir -ErrorAction SilentlyContinue).Path) {
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    $null = robocopy $Root $AppDir /MIR /NFL /NDL /NJH /NJS /NP /XD __pycache__
    if ($LASTEXITCODE -ge 8) { Log "robocopy to $AppDir failed with $LASTEXITCODE" }
    $global:LASTEXITCODE = 0
}

Step "Nemo package" { Test-NemoInstalled } {
    # A .pth file rather than a pip build: no build backend, nothing to
    # compile on a slow CPU, and edits under $AppDir take effect directly.
    $site = Join-Path $Venv "Lib\site-packages"
    Set-Content -Path (Join-Path $site "nemo.pth") -Value $AppDir -Encoding ASCII
    Set-Content -Path $NemoCmd -Encoding ASCII -Value @"
@echo off
"$VenvPy" -m nemo.cli %*
"@
} $true | Out-Null

# The desktop interface needs Tk, which ships with Python on Windows unless
# the 'tcl/tk' option was switched off at install time.
Step "Desktop interface (Tk)" {
    if (-not (Test-Path $VenvPy)) { return $false }
    Push-Location $env:TEMP
    try { $null = & $VenvPy -I -c "import tkinter" 2>$null; $ok = ($LASTEXITCODE -eq 0) }
    finally { Pop-Location }
    return $ok
} {
    Note "WARN" "Tk missing" ("Python was installed without tcl/tk. Re-run the Python " +
        "installer, choose Modify, and tick 'tcl/tk and IDLE'. The command line still works.")
} $false | Out-Null

# A Start menu and desktop shortcut, so Nemo opens like any other program.
$VenvPyw = Join-Path $Venv "Scripts\pythonw.exe"
if (Test-Path $VenvPyw) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath("Programs"),
                       [Environment]::GetFolderPath("Desktop"))) {
        # D133: Windows answers with an empty string for a folder the
        # profile does not have. Unguarded, that was seven red errors per
        # folder in a pass that then said "Everything checks out".
        if (-not $dir -or -not (Test-Path $dir)) {
            Note "WARN" "Nemo shortcut" "No Start menu or Desktop folder in this profile; start Nemo with 'nemo gui' instead."
            continue
        }
        $lnk = $shell.CreateShortcut((Join-Path $dir "Nemo.lnk"))
        $lnk.TargetPath       = $VenvPyw
        $lnk.Arguments        = "-m nemo.gui --prompt"     # opens at the home screen
        $lnk.WorkingDirectory = $env:USERPROFILE
        $lnk.Description      = "Nemo"
        # Nemo's cog, not Python's icon (owner, 2026-10-29).
        $ico = Join-Path $AppDir "nemo\data\logo\nemo.ico"
        if (Test-Path $ico) { $lnk.IconLocation = "$ico,0" }
        $lnk.Save()
    }
}

# Graphviz on the user PATH too. WireViz runs 'dot' by name; Nemo now passes
# the path to it directly, but other tools expect it on PATH as well.
$dotExe = Find-Exe @("dot.exe") @("C:\Program Files\Graphviz\bin", "C:\Program Files (x86)\Graphviz\bin")
if ($dotExe) {
    $gbin = Split-Path $dotExe -Parent
    $up = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($up -split ";") -notcontains $gbin -and $CheckOnly) {
        Note "INFO" "Graphviz not on PATH" "would add $gbin (check-only, not fixing)"
    } elseif (($up -split ";") -notcontains $gbin) {
        [Environment]::SetEnvironmentVariable("Path", (($up, $gbin) | Where-Object { $_ }) -join ";", "User")
        Note "FIX" "Graphviz added to PATH" $gbin
    }
}

# 'nemo' in every new terminal, not only the one NemoDoc opens.
$scripts  = Join-Path $Venv "Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
# D201: a check-only pass added the (not yet made) venv's Scripts folder to the
# user PATH on the AH531, 2026-10-29. Only a real pass, and only once it exists.
if (($userPath -split ";") -notcontains $scripts -and ($CheckOnly -or -not (Test-Path $scripts))) {
    Note "INFO" "nemo not on PATH" ("would add $scripts" + $(if ($CheckOnly) { " (check-only, not fixing)" } else { " once the Python environment is made" }))
} elseif (($userPath -split ";") -notcontains $scripts) {
    [Environment]::SetEnvironmentVariable("Path", (($userPath, $scripts) | Where-Object { $_ }) -join ";", "User")
    Note "FIX" "nemo added to PATH" $scripts
}
Refresh-Path

# llama.cpp no longer publishes per-instruction-set Windows builds. There
# is one CPU package, which carries a backend for each CPU generation --
# including ggml-cpu-sandybridge.dll for a Sandy Bridge Core chip and
# ggml-cpu-sse42.dll for a Celeron or Pentium -- and selects the right one
# at runtime. An earlier revision searched for an "-avx-" asset that no
# longer exists, and the project's "latest" release now points at a tag
# with no binaries in it, so it found nothing at all.
#
# Pinned rather than "latest", because "latest" is exactly what changed
# underneath this script. The build below was downloaded and inspected:
# it contains both backends this machine could need. The hash is checked
# before anything is unpacked.
$LlamaBuild  = "b11175"
$LlamaAsset  = "llama-$LlamaBuild-bin-win-cpu-x64.zip"
$LlamaUrl    = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaBuild/$LlamaAsset"
$LlamaSha256 = "174dcd380f2519ddc48e5ccac183dde246e8579a0b315d3062c3ed4f0889ede1"

Step "llama.cpp ($LlamaBuild, runtime CPU dispatch)" {
    $exe = Join-Path $EngineDir "llama-server.exe"
    if (-not (Test-Path $exe)) { return $false }
    # The exe is now a thin launcher. Without its DLLs beside it -- the
    # usual result of copying just the .exe -- it will not start.
    foreach ($dll in @("llama.dll", "ggml.dll", "ggml-base.dll", "llama-server-impl.dll")) {
        if (-not (Test-Path (Join-Path $EngineDir $dll))) { return $false }
    }
    if (-not (Get-ChildItem $EngineDir -Filter "ggml-cpu-*.dll" -ErrorAction SilentlyContinue)) {
        return $false
    }
    # Does it actually run on this CPU? The only honest test.
    $null = & $exe --version 2>&1
    return ($LASTEXITCODE -eq 0)
} {
    New-Item -ItemType Directory -Force -Path $EngineDir | Out-Null
    $zip = Join-Path $env:TEMP $LlamaAsset
    if (Get-File $LlamaUrl $zip "llama.cpp $LlamaBuild") {
        $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $LlamaSha256) {
            Log "llama.cpp hash mismatch: expected $LlamaSha256 got $actual"
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            Say "        download did not match the expected hash; refusing to install it" "Red"
            return
        }
        Expand-Zip $zip $EngineDir | Out-Null
        Set-Content (Join-Path $EngineDir "build.txt") $LlamaBuild -Encoding ASCII
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }
} $true | Out-Null

# --- llama.cpp on the GPU (the desktop profile) ---------------------
# Owner, 2026-11-04: a machine with an NVIDIA card that can hold the design
# model (7000 MiB measured, qwen3-8b at 16k context) runs the models on it
# (nemo/machine.py). The CUDA build of the same release, and the CUDA
# runtime it needs, into $Prefix\engine-cuda beside the CPU engine, which
# stays. Hashes are GitHub's own; a test holds this list to
# nemo/machine.py's CUDA_ENGINE. Nemo looks in C:\Nemo\engine-cuda; with
# another -Prefix set paths.llama_server_gpu in config.yaml. Never on a
# machine without such a card: the laptop is not asked.
$EngineCudaDir = Join-Path $Prefix "engine-cuda"
$CudaFiles = @(
    @{ file = "llama-b11175-bin-win-cuda-13.4-x64.zip"; sha256 = "d4eb4db7bd9227f5b9be1e6abd9fb0416b0e87280a14c7fbea352779ac585684"; bytes = 150242012 },
    @{ file = "cudart-llama-bin-win-cuda-13.4-x64.zip"; sha256 = "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668"; bytes = 423535356 }
)
$NvidiaMiB = 0
$Smi = Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
if (Test-Path $Smi) {
    $NvidiaMiB = (& $Smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null |
                  ForEach-Object { [int]([double]$_) } | Measure-Object -Maximum).Maximum
}
if ($NvidiaMiB -ge 7000 -and -not $SkipGpu) {
    Step "llama.cpp on the GPU (CUDA 13.4, $LlamaBuild)" {
        $exe = Join-Path $EngineCudaDir "llama-server.exe"
        if (-not (Test-Path $exe)) { return $false }
        foreach ($dll in @("ggml-cuda.dll", "cudart64_13.dll", "cublas64_13.dll")) {
            if (-not (Test-Path (Join-Path $EngineCudaDir $dll))) { return $false }
        }
        $null = & $exe --version 2>&1
        return ($LASTEXITCODE -eq 0)
    } {
        New-Item -ItemType Directory -Force -Path $EngineCudaDir | Out-Null
        foreach ($c in $CudaFiles) {
            $zip = Join-Path $env:TEMP $c.file
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            if (-not (Get-File "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaBuild/$($c.file)" $zip $c.file)) { return }
            $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $c.sha256) {
                Log "$($c.file) hash mismatch: expected $($c.sha256) got $actual"
                Remove-Item $zip -Force -ErrorAction SilentlyContinue
                Say "        $($c.file) did not match the expected hash; refusing to install it" "Red"
                return
            }
            Expand-Zip $zip $EngineCudaDir | Out-Null
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
        }
        Set-Content (Join-Path $EngineCudaDir "build.txt") "$LlamaBuild-cuda-13.4" -Encoding ASCII
    } $false | Out-Null
} elseif ($NvidiaMiB -gt 0) {
    Note "INFO" "GPU" ("an NVIDIA card with {0} MiB: under the 7000 the design model needs, so the models stay on the CPU." -f $NvidiaMiB)
}

$stray = Get-ChildItem $Prefix -Recurse -Filter "llama.h" -ErrorAction SilentlyContinue |
         Select-Object -First 1
if ($stray) {
    Note "WARN" "Source code found in $($stray.DirectoryName)" (
        "llama.h is a C header from the llama.cpp SOURCE archive. Nemo never " +
        "uses it and it contains no llama-server.exe. It is harmless but " +
        "unneeded; delete that folder if you like.")
}

# --- software OpenGL ------------------------------------------------
$NeedsMesa = $gpuInfo.Name -match "Basic Display|Basic Render"
if ($NeedsMesa) {
    $kicadBin = Find-Exe @("kicad-cli.exe") @(
        "C:\Program Files\KiCad\9.0\bin", "C:\Program Files\KiCad\bin")
    if ($kicadBin) {
        $kicadDir = Split-Path $kicadBin -Parent
        if (Test-Path (Join-Path $kicadDir "opengl32.dll")) {
            Note "OK" "Software OpenGL" ""
        } else {
            Note "WARN" "Software OpenGL" ("Windows is using {0}, so there is no hardware OpenGL " -f $gpuInfo.Name +
                "and KiCad's canvas will not work. Mesa cannot be fetched automatically -- its builds are " +
                "not published through an API. Download mesa-dist-win (MSVC x64, desktop OpenGL, llvmpipe, " +
                "NOT an AVX2 build) and run setup-mesa.ps1 -MesaZip <file>.")
        }
    }
} else {
    Note "INFO" "Graphics" ("{0} reports a real driver; no software OpenGL needed." -f $gpuInfo.Name)
}

# --- models ---------------------------------------------------------
$Models = @(
    @{ name = "qwen3-1.7b";       repo = "unsloth/Qwen3-1.7B-GGUF";                 file = "Qwen3-1.7B-Q4_K_M.gguf" },
    @{ name = "qwen3-4b";         repo = "Qwen/Qwen3-4B-GGUF";                      file = "Qwen3-4B-Q4_K_M.gguf" },
    @{ name = "qwen2.5-coder-3b"; repo = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF";     file = "qwen2.5-coder-3b-instruct-q4_k_m.gguf" },
    @{ name = "gemma3-1b";        repo = "unsloth/gemma-3-1b-it-GGUF";              file = "gemma-3-1b-it-Q4_K_M.gguf" }
)

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
$haveModels = 0
foreach ($m in $Models) {
    $dest = Join-Path $ModelDir ($m.name + ".gguf")
    if (Test-Path $dest) { $haveModels++; continue }
    if ($SkipModels -or $CheckOnly) { continue }
    # On 8 GB the 4B model is the largest that fits; on less, only the 1B.
    if ($totalMB -lt 7000 -and $m.name -ne "gemma3-1b") { continue }
    $url = "https://huggingface.co/$($m.repo)/resolve/main/$($m.file)"
    if (Get-File $url $dest $m.name) { $haveModels++ }
}
if ($haveModels -gt 0) {
    Note "OK" "Models" ("{0} of {1} present" -f $haveModels, $Models.Count)
} else {
    Note "FAIL" "Models" ("None found in {0}. Nemo cannot run without at least one GGUF." -f $ModelDir)
}

# --- the Artist: story covers --------------------------------------
# stable-diffusion.cpp's CPU build, SD-Turbo and the tiny TAESD decoder, in
# $Prefix\artist, where nemo/artist.py looks (beside the engine's prefix).
# Optional: Nemo runs without them and a cover says what is missing, so
# nothing here FAILs the pass. 2 GB, so -SkipArtist (or -SkipModels) leaves
# them. Each file is hash-checked before it is put where Nemo looks. The
# list is nemo/artist.py's (ENGINE_ZIP, SOURCES); a test holds this copy
# and fetch-models.sh's to it.
$ArtistDir   = Join-Path $Prefix "artist"
$ArtistBuild = "master-929-3f8527a"
$ArtistFiles = @(
    @{ file = "sd-master-3f8527a-bin-win-cpu-x64.zip"; url = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-929-3f8527a/sd-master-3f8527a-bin-win-cpu-x64.zip"; sha256 = "5e7caca2080321b25a12c1fa4175cb7d953f2b182309f8f73bfc9c725231d26c"; bytes = 17486440 },
    @{ file = "sd_turbo-f16-q8_0.gguf"; url = "https://huggingface.co/Green-Sky/SD-Turbo-GGUF/resolve/main/sd_turbo-f16-q8_0.gguf"; sha256 = "d50be7655f0a554cf8041c145d88b210bd5f3c545423119dee62ae08cae51580"; bytes = 2023745376 },
    @{ file = "taesd.safetensors"; url = "https://huggingface.co/madebyollin/taesd/resolve/main/diffusion_pytorch_model.safetensors"; sha256 = "db169d69145ec4ff064e49d99c95fa05d3eb04ee453de35824a6d0f325513549"; bytes = 9793292 }
)
$SdExe = Join-Path $ArtistDir "sd\sd-cli.exe"

function Test-ArtistFile {
    param($A)
    if ($A.file -like "*.zip") {
        # The engine is the zip unpacked: sd-cli.exe, its DLLs, and it runs.
        if (-not (Test-Path $SdExe)) { return $false }
        foreach ($dll in @("stable-diffusion.dll", "ggml.dll", "ggml-base.dll")) {
            if (-not (Test-Path (Join-Path $ArtistDir "sd\$dll"))) { return $false }
        }
        $null = & $SdExe --version 2>&1
        return ($LASTEXITCODE -eq 0)
    }
    # A model file of the wrong size is a cut-short copy, not the model.
    $dest = Join-Path $ArtistDir $A.file
    return ((Test-Path $dest) -and ((Get-Item $dest).Length -eq $A.bytes))
}

function Get-ArtistFile {
    param($A)
    # Fetched under another name, hash-checked, and only then put where
    # Nemo looks: a file that fails the check is deleted, never used.
    $staged = Join-Path $ArtistDir ($A.file + ".unchecked")
    if ($A.file -like "*.zip") { $staged = Join-Path $env:TEMP $A.file }
    Remove-Item $staged -Force -ErrorAction SilentlyContinue
    if (-not (Get-File $A.url $staged $A.file)) { return "download failed" }
    $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $A.sha256) {
        Log "$($A.file) hash mismatch: expected $($A.sha256) got $actual"
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        return "did not match the expected hash, so it was deleted"
    }
    if ($A.file -like "*.zip") {
        $ok = Expand-Zip $staged (Join-Path $ArtistDir "sd")
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not $ok) { return "could not be unpacked" }
        Set-Content (Join-Path $ArtistDir "sd\build.txt") $ArtistBuild -Encoding ASCII
    } else {
        Move-Item $staged (Join-Path $ArtistDir $A.file) -Force
    }
    return ""
}

$artistMissing = @()
foreach ($a in $ArtistFiles) {
    if (Test-ArtistFile $a) { continue }
    if ($SkipArtist -or $SkipModels -or $CheckOnly) { $artistMissing += $a.file; continue }
    New-Item -ItemType Directory -Force -Path (Join-Path $ArtistDir "sd") | Out-Null
    $diskMB = [math]::Round((Get-Item $ArtistDir).PSDrive.Free / 1MB)
    if ($diskMB -lt ([math]::Ceiling($a.bytes / 1MB) + 500)) {
        $artistMissing += ("{0} (only {1} MB free on the disk)" -f $a.file, $diskMB)
        continue
    }
    $why = Get-ArtistFile $a
    if ($why -or -not (Test-ArtistFile $a)) {
        if (-not $why) { $why = "was fetched but does not check out" }
        $artistMissing += ("{0} ({1})" -f $a.file, $why)
    } else {
        Note "FIX" "Artist: $($a.file)" "hash checked"
    }
}
if ($artistMissing.Count -eq 0) {
    Note "OK" "Artist (story covers)" ("stable-diffusion.cpp {0}, SD-Turbo, TAESD in {1}" -f $ArtistBuild, $ArtistDir)
} elseif ($SkipArtist -or $SkipModels -or $CheckOnly) {
    Note "INFO" "Artist (story covers)" ("not installed: {0}. Run NemoDoc without -SkipArtist to fetch them (about 2 GB)." -f ($artistMissing -join ", "))
} else {
    Note "WARN" "Artist (story covers)" ("missing: {0}. Nemo runs without them; story covers say so. Run NemoDoc again to retry." -f ($artistMissing -join ", "))
}

# The Artist on the GPU (owner, 2026-11-04): where the language models run
# on an NVIDIA card (the 7000 MiB test above), the same release's CUDA 12
# build and its runtime go into $ArtistDir\sd-cuda. A full-screen scene in
# about 9 s there, against 11 minutes for a small one on the AH531. Hashes
# are GitHub's; a test holds this list to nemo/artist.py's SD_CUDA.
$SdCudaDir = Join-Path $ArtistDir "sd-cuda"
$SdCudaFiles = @(
    @{ file = "sd-master-3f8527a-bin-win-cuda12-x64.zip"; sha256 = "217d6dead9abd3f827fc338268555cc179234e7e6330ef21ecb1c985e19d2dc7"; bytes = 337915440 },
    @{ file = "cudart-sd-bin-win-cu12-x64.zip"; sha256 = "fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d"; bytes = 563452046 }
)
if ($NvidiaMiB -ge 7000 -and -not $SkipGpu -and -not $SkipArtist -and -not $SkipModels) {
    Step "Artist on the GPU (stable-diffusion.cpp $ArtistBuild, CUDA 12)" {
        $exe = Join-Path $SdCudaDir "sd-cli.exe"
        if (-not (Test-Path $exe)) { return $false }
        foreach ($dll in @("ggml-cuda.dll", "cudart64_12.dll", "cublas64_12.dll")) {
            if (-not (Test-Path (Join-Path $SdCudaDir $dll))) { return $false }
        }
        $null = & $exe --version 2>&1
        return ($LASTEXITCODE -eq 0)
    } {
        New-Item -ItemType Directory -Force -Path $SdCudaDir | Out-Null
        foreach ($c in $SdCudaFiles) {
            $zip = Join-Path $env:TEMP $c.file
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            if (-not (Get-File "https://github.com/leejet/stable-diffusion.cpp/releases/download/$ArtistBuild/$($c.file)" $zip $c.file)) { return }
            $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $c.sha256) {
                Log "$($c.file) hash mismatch: expected $($c.sha256) got $actual"
                Remove-Item $zip -Force -ErrorAction SilentlyContinue
                Say "        $($c.file) did not match the expected hash; refusing to install it" "Red"
                return
            }
            Expand-Zip $zip $SdCudaDir | Out-Null
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
        }
        Set-Content (Join-Path $SdCudaDir "build.txt") "$ArtistBuild-cuda12" -Encoding ASCII
    } $false | Out-Null
}

# Hearing on the GPU (owner, 2026-11-04): whisper.cpp's CUDA 12.4 build into
# $Prefix\tools\whisper and its small English model into models\speech, on
# the same NVIDIA machines. It heard "ESP32" and "2000 mAh" where Vosk heard
# "e s p thirty two" and "million power". Hashes are GitHub's and Hugging
# Face's; a test holds this list to nemo/speech.py's WHISPER_SOURCES.
$WhisperDir = Join-Path $Prefix "tools\whisper"
$WhisperFiles = @(
    @{ file = "whisper-bin-win-cuda-12.4.0-x64.zip"; sha256 = "afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a"; bytes = 684913404; url = "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-win-cuda-12.4.0-x64.zip" },
    @{ file = "ggml-small.en.bin"; sha256 = "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"; bytes = 487614201; url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin" }
)
$WhisperModel = Join-Path $ModelDir "speech\ggml-small.en.bin"
if ($NvidiaMiB -ge 7000 -and -not $SkipGpu -and -not $SkipModels) {
    Step "Hearing on the GPU (whisper.cpp small.en)" {
        $exe = Join-Path $WhisperDir "Release\whisper-cli.exe"
        return ((Test-Path $exe) -and (Test-Path $WhisperModel) -and
                ((Get-Item $WhisperModel).Length -eq $WhisperFiles[1].bytes))
    } {
        foreach ($w in $WhisperFiles) {
            $staged = Join-Path $env:TEMP $w.file
            Remove-Item $staged -Force -ErrorAction SilentlyContinue
            if (-not (Get-File $w.url $staged $w.file)) { return }
            $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $w.sha256) {
                Log "$($w.file) hash mismatch: expected $($w.sha256) got $actual"
                Remove-Item $staged -Force -ErrorAction SilentlyContinue
                Say "        $($w.file) did not match the expected hash; refusing to install it" "Red"
                return
            }
            if ($w.file -like "*.zip") {
                New-Item -ItemType Directory -Force -Path $WhisperDir | Out-Null
                Expand-Zip $staged $WhisperDir | Out-Null
                Remove-Item $staged -Force -ErrorAction SilentlyContinue
            } else {
                New-Item -ItemType Directory -Force -Path (Split-Path $WhisperModel) | Out-Null
                Move-Item $staged $WhisperModel -Force
            }
        }
    } $false | Out-Null
}

# The PCB Designer (owner, 2026-11-04): Freerouting 2.5.0 routes the copper,
# and it is built for Java 25 (class files 69: the JDK 21 Ghidra uses cannot
# run it). Both into $Prefix\tools; optional, -SkipPcb leaves them. Hashes are
# GitHub's and Adoptium's; a test holds them to nemo/pcb.py.
$PcbFiles = @(
    @{ file = "freerouting-2.5.0.jar"; sha256 = "f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7"; bytes = 64599107; url = "https://github.com/freerouting/freerouting/releases/download/v2.5.0/freerouting-2.5.0.jar" },
    @{ file = "OpenJDK25U-jre_x64_windows_hotspot_25.0.5_8.zip"; sha256 = "da78d54a2fcdbba1e92d5e3f07dd30236f96297891c4a21a781c3f38f5c0beae"; bytes = 58589419; url = "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jre_x64_windows_hotspot_25.0.5_8.zip" }
)
$ToolsDir = Join-Path $Prefix "tools"
$FreeroutingJar = Join-Path $ToolsDir "freerouting\freerouting-2.5.0.jar"
if (-not $SkipPcb) {
    Step "PCB routing (Freerouting 2.5.0, Java 25)" {
        return ((Test-Path $FreeroutingJar) -and
                (Get-ChildItem $ToolsDir -Filter "jdk-25*" -Directory -ErrorAction SilentlyContinue))
    } {
        foreach ($f in $PcbFiles) {
            $staged = Join-Path $env:TEMP $f.file
            Remove-Item $staged -Force -ErrorAction SilentlyContinue
            if (-not (Get-File $f.url $staged $f.file)) { return }
            $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $f.sha256) {
                Log "$($f.file) hash mismatch: expected $($f.sha256) got $actual"
                Remove-Item $staged -Force -ErrorAction SilentlyContinue
                Say "        $($f.file) did not match the expected hash; refusing to install it" "Red"
                return
            }
            if ($f.file -like "*.zip") {
                Expand-Zip $staged $ToolsDir | Out-Null
                Remove-Item $staged -Force -ErrorAction SilentlyContinue
            } else {
                New-Item -ItemType Directory -Force -Path (Split-Path $FreeroutingJar) | Out-Null
                Move-Item $staged $FreeroutingJar -Force
            }
        }
    } $false | Out-Null
}

# The Workshop's drawings (owner, 2026-11-11: "yes download cadcraft-cli and
# do stage 1"): CADCraft 0.19.0 draws the enclosure as DXF, PDF at 1:1 and
# PNG (nemo/drawings.py). Portable zip into $Prefix\tools\cadcraft; optional,
# -SkipDrawings leaves it. The hash is GitHub's, repeated in the release's
# SHA256SUMS.txt; a test holds it to nemo/drawings.py's SOURCES.
$CadcraftZip = @{ file = "cadcraft-0.19.0-windows-x64-portable.zip"; sha256 = "38fa68aafef23e0ebbef78721180634e8a24ce6f7c590bbaabf003e7e9d88731"; bytes = 74495039; url = "https://github.com/storytold/cadcraft/releases/download/v0.19.0/cadcraft-0.19.0-windows-x64-portable.zip" }
$CadcraftCli = Join-Path $ToolsDir "cadcraft\cadcraft-cli.exe"
if (-not $SkipDrawings) {
    Step "Workshop drawings (CADCraft 0.19.0)" {
        if (-not (Test-Path $CadcraftCli)) { return $false }
        return ((& $CadcraftCli --version 2>$null) -match "0\.19\.0")
    } {
        $f = $CadcraftZip
        $staged = Join-Path $env:TEMP $f.file
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not (Get-File $f.url $staged $f.file)) { return }
        $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $f.sha256) {
            Log "$($f.file) hash mismatch: expected $($f.sha256) got $actual"
            Remove-Item $staged -Force -ErrorAction SilentlyContinue
            Say "        $($f.file) did not match the expected hash; refusing to install it" "Red"
            return
        }
        $unpacked = Join-Path $ToolsDir "cadcraft-0.19.0-windows-x64-portable"
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Zip $staged $ToolsDir | Out-Null
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $ToolsDir "cadcraft") -Recurse -Force -ErrorAction SilentlyContinue
        Rename-Item $unpacked "cadcraft"
    } $false | Out-Null
}

# Books and the pack PDF (owner, 2026-11-11, stage 4 of the ArtCraft plan):
# WordCraft 0.17.0 binds a story as book.docx and book.pdf and turns a
# project's BUILD.md into pack.pdf (nemo/books.py). Portable zip into
# $Prefix\tools\wordcraft; optional, -SkipBooks leaves it. GitHub's hash; a
# test holds it to nemo/books.py's SOURCES.
$WordcraftZip = @{ file = "wordcraft-0.17.0-windows-x64-portable.zip"; sha256 = "ad05af39d62504ddb382f93f9b7e2e7e9ce92938d132c18c4fb43e10822108ce"; bytes = 117678204; url = "https://github.com/storytold/wordcraft/releases/download/v0.17.0/wordcraft-0.17.0-windows-x64-portable.zip" }
$WordcraftCli = Join-Path $ToolsDir "wordcraft\wordcraft-cli.exe"
if (-not $SkipBooks) {
    Step "Books and the pack PDF (WordCraft 0.17.0)" {
        if (-not (Test-Path $WordcraftCli)) { return $false }
        return ((& $WordcraftCli --version 2>$null) -match "0\.17\.0")
    } {
        $f = $WordcraftZip
        $staged = Join-Path $env:TEMP $f.file
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not (Get-File $f.url $staged $f.file)) { return }
        $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $f.sha256) {
            Log "$($f.file) hash mismatch: expected $($f.sha256) got $actual"
            Remove-Item $staged -Force -ErrorAction SilentlyContinue
            Say "        $($f.file) did not match the expected hash; refusing to install it" "Red"
            return
        }
        $unpacked = Join-Path $ToolsDir "wordcraft-0.17.0-windows-x64-portable"
        Remove-Item $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Zip $staged $ToolsDir | Out-Null
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $ToolsDir "wordcraft") -Recurse -Force -ErrorAction SilentlyContinue
        Rename-Item $unpacked "wordcraft"
    } $false | Out-Null
}

# --- Gaming: RetroArch and one core per console --------------------
# RetroArch 1.22.2 from libretro's buildbot into $Prefix\games, where
# nemo/gaming.py looks (beside the engine's prefix). Only the cores Nemo's
# emulators use are kept from the cores archive. Optional, like the Artist:
# 430 MB, so -SkipGames (or -SkipModels) leaves it. libretro publishes no
# hashes; these pin the files fetched on 2026-10-21, and a test holds them
# to nemo/gaming.py's SOURCES. Games are never downloaded.
$GamesDir  = Join-Path $Prefix "games"
$GamesBase = "https://buildbot.libretro.com/stable/1.22.2/windows/x86_64"
$GameFiles = @(
    @{ file = "RetroArch.7z"; sha256 = "b2139b1d0f9d4526dc6b5ce23cbb3efdc766096fa6f2c3df016818b486ac6372"; bytes = 202509078 },
    @{ file = "RetroArch_cores.7z"; sha256 = "86b871e11b9b4772ac644b40a38f2c8e9449da1f355eae7da08aa061148547b0"; bytes = 229761684 }
)
$GameCores = @("nestopia", "snes9x", "genesis_plus_gx", "gambatte", "mgba", "stella2014")
$RetroArchExe = Join-Path $GamesDir "RetroArch-Win64\retroarch.exe"
# The PlayStation core, "pcsx_rearmed", on its own from the nightly folder
# (re-fetched 2026-11-06), pinned as fetched; a test holds it to gaming.PS1_CORE.
$Ps1Core = @{ file = "pcsx_rearmed_libretro.dll.zip"; sha256 = "b759a011dc8f2b3190225c5accd8b34b2f9d8e0bd82f4365d29a6c783a3cc21c"; bytes = 847073 }

function Test-Games {
    if (-not (Test-Path $RetroArchExe)) { return $false }
    foreach ($c in $GameCores) {
        if (-not (Test-Path (Join-Path $GamesDir "RetroArch-Win64\cores\${c}_libretro.dll"))) { return $false }
    }
    return $true
}

$gamesWhy = ""
if (-not (Test-Games) -and -not ($SkipGames -or $SkipModels -or $CheckOnly)) {
    New-Item -ItemType Directory -Force -Path $GamesDir | Out-Null
    $diskMB = [math]::Round((Get-Item $GamesDir).PSDrive.Free / 1MB)
    if ($diskMB -lt 1500) { $gamesWhy = "only $diskMB MB free on the disk" }
    $tarExe = Join-Path $env:SystemRoot "System32\tar.exe"    # Windows' own bsdtar reads 7z
    foreach ($g in $GameFiles) {
        if ($gamesWhy) { break }
        $staged = Join-Path $env:TEMP $g.file
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not (Get-File "$GamesBase/$($g.file)" $staged $g.file)) { $gamesWhy = "$($g.file): download failed"; break }
        $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $g.sha256) {
            Log "$($g.file) hash mismatch: expected $($g.sha256) got $actual"
            Remove-Item $staged -Force -ErrorAction SilentlyContinue
            $gamesWhy = "$($g.file) did not match the expected hash, so it was deleted"; break
        }
        Push-Location $GamesDir
        try {
            if ($g.file -eq "RetroArch.7z") { & $tarExe -xf $staged }
            else { & $tarExe -xf $staged @($GameCores | ForEach-Object { "RetroArch-Win64/cores/${_}_libretro.dll" }) }
        } finally { Pop-Location }
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
    }
}
$Ps1Dll = Join-Path $GamesDir "RetroArch-Win64\cores\pcsx_rearmed_libretro.dll"
if ((Test-Path $RetroArchExe) -and -not (Test-Path $Ps1Dll) -and -not ($SkipGames -or $SkipModels -or $CheckOnly)) {
    $staged = Join-Path $env:TEMP $Ps1Core.file
    if (Get-File "https://buildbot.libretro.com/nightly/windows/x86_64/latest/$($Ps1Core.file)" $staged $Ps1Core.file) {
        if ((Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower() -eq $Ps1Core.sha256) {
            & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $staged -C (Split-Path $Ps1Dll)
        } else {
            Note "WARN" "Gaming (PlayStation)" "libretro's PS1 core has changed since Nemo pinned it, so it was not installed."
        }
    }
    Remove-Item $staged -Force -ErrorAction SilentlyContinue
}
if (Test-Games) {
    Note "OK" "Gaming (RetroArch)" ("RetroArch 1.22.2 and {0} cores in {1}" -f $GameCores.Count, $GamesDir)
} elseif ($SkipGames -or $SkipModels -or $CheckOnly) {
    Note "INFO" "Gaming (RetroArch)" "not installed. Run NemoDoc without -SkipGames to fetch it (about 430 MB)."
} else {
    if (-not $gamesWhy) { $gamesWhy = "was fetched but does not check out" }
    Note "WARN" "Gaming (RetroArch)" "not installed: $gamesWhy. Nemo runs without it; the emulators say so. Run NemoDoc again to retry."
}

# --- Film Studio: ffmpeg --------------------------------------------
# GyanD's ffmpeg 9.0.2 essentials build (a fixed release, not a nightly) into
# $Prefix\tools, where nemo/filmstudio.py looks. 35 MB (about 315 MB
# unpacked), so -SkipFilm (or -SkipModels) leaves it. The hash is GitHub's
# own for the file; a test holds it to nemo/filmstudio.py's SOURCE.
$FfmpegDir  = Join-Path $Prefix "tools"
$FfmpegFile = @{ file = "ffmpeg-9.0.2-essentials_build.7z"; sha256 = "4705843ccaaf54257c16ad90f3e952ece33c17df964ecf7bfdbb0f49c7171077"; bytes = 35430500 }
$FfmpegUrl  = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/$($FfmpegFile.file)"
$FfmpegExe  = Join-Path $FfmpegDir "ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"

$filmWhy = ""
if (-not (Test-Path $FfmpegExe) -and -not ($SkipFilm -or $SkipModels -or $CheckOnly)) {
    New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null
    $diskMB = [math]::Round((Get-Item $FfmpegDir).PSDrive.Free / 1MB)
    if ($diskMB -lt 600) { $filmWhy = "only $diskMB MB free on the disk" }
    else {
        $staged = Join-Path $env:TEMP $FfmpegFile.file
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not (Get-File $FfmpegUrl $staged $FfmpegFile.file)) { $filmWhy = "download failed" }
        else {
            $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $FfmpegFile.sha256) {
                Log "$($FfmpegFile.file) hash mismatch: expected $($FfmpegFile.sha256) got $actual"
                $filmWhy = "the download did not match the expected hash, so it was deleted"
            } else {
                & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $staged -C $FfmpegDir
            }
        }
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
    }
}
if (Test-Path $FfmpegExe) {
    Note "OK" "Film Studio (ffmpeg)" "ffmpeg 9.0.2 in $FfmpegDir"
} elseif ($SkipFilm -or $SkipModels -or $CheckOnly) {
    Note "INFO" "Film Studio (ffmpeg)" "not installed. Run NemoDoc without -SkipFilm to fetch it (about 35 MB)."
} else {
    if (-not $filmWhy) { $filmWhy = "was fetched but ffmpeg.exe is not there" }
    Note "WARN" "Film Studio (ffmpeg)" "not installed: $filmWhy. Nemo runs without it; the Film Studio says so. Run NemoDoc again to retry."
}

# --- Print Shop: OrcaSlicer -----------------------------------------
# OrcaSlicer 2.4.2's portable zip from its GitHub release into
# $Prefix\tools\OrcaSlicer, where nemo/printshop.py looks. It carries
# Anycubic's Kobra 3 profiles. 171 MB (about 410 MB unpacked), so
# -SkipPrint (or -SkipModels) leaves it. The hash is GitHub's own for the
# file; a test holds it to nemo/printshop.py's SOURCE.
$OrcaDir  = Join-Path $Prefix "tools\OrcaSlicer"
$OrcaFile = @{ file = "OrcaSlicer_Windows_V2.4.2_x64_portable.zip"; sha256 = "feba3009dfb9d268779cca5758a1a5bc3b7d0722bf8fa48d5c57340de975d6be"; bytes = 171367668 }
$OrcaUrl  = "https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v2.4.2/$($OrcaFile.file)"
$OrcaExe  = Join-Path $OrcaDir "orca-slicer.exe"

$printWhy = ""
if (-not (Test-Path $OrcaExe) -and -not ($SkipPrint -or $SkipModels -or $CheckOnly)) {
    New-Item -ItemType Directory -Force -Path $OrcaDir | Out-Null
    $diskMB = [math]::Round((Get-Item $OrcaDir).PSDrive.Free / 1MB)
    if ($diskMB -lt 800) { $printWhy = "only $diskMB MB free on the disk" }
    else {
        $staged = Join-Path $env:TEMP $OrcaFile.file
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
        if (-not (Get-File $OrcaUrl $staged $OrcaFile.file)) { $printWhy = "download failed" }
        else {
            $actual = (Get-FileHash -Path $staged -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $OrcaFile.sha256) {
                Log "$($OrcaFile.file) hash mismatch: expected $($OrcaFile.sha256) got $actual"
                $printWhy = "the download did not match the expected hash, so it was deleted"
            } else {
                & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $staged -C $OrcaDir
            }
        }
        Remove-Item $staged -Force -ErrorAction SilentlyContinue
    }
}
if (Test-Path $OrcaExe) {
    Note "OK" "Print Shop (OrcaSlicer)" "OrcaSlicer 2.4.2 in $OrcaDir"
} elseif ($SkipPrint -or $SkipModels -or $CheckOnly) {
    Note "INFO" "Print Shop (OrcaSlicer)" "not installed. Run NemoDoc without -SkipPrint to fetch it (about 171 MB)."
} else {
    if (-not $printWhy) { $printWhy = "was fetched but orca-slicer.exe is not there" }
    Note "WARN" "Print Shop (OrcaSlicer)" "not installed: $printWhy. Nemo runs without it; the Print Shop says so. Run NemoDoc again to retry."
}

# --- config ---------------------------------------------------------
function Set-EnginePath {
    # D132: the shipped config names C:/Nemo/engine/llama-server.exe. With
    # -Prefix anywhere else the engine was downloaded to the new prefix and
    # the config still pointed at C:\Nemo: found on the real laptop, where a
    # C:\NemoClean install started the engine of the C:\Nemo one. On a
    # machine with no C:\Nemo the pass says "Everything checks out" and the
    # mode then fails to start.
    param([string]$ConfigFile, [string]$EngineFolder)
    $exe  = ((Join-Path $EngineFolder "llama-server.exe") -replace "\\", "/")
    $text = [IO.File]::ReadAllText($ConfigFile)
    $text = [regex]::Replace($text, '(?m)^(\s*llama_server:[ \t]*)[^\r\n]*',
                             ('${1}' + $exe.Replace('$', '$$')))
    [IO.File]::WriteAllText($ConfigFile, $text, (New-Object Text.UTF8Encoding $false))
}

Step "Config" {
    Test-Path (Join-Path $env:USERPROFILE ".nemo\config.yaml")
} {
    $dest = Join-Path $env:USERPROFILE ".nemo"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $src = Join-Path $Root "config.yaml"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $dest "config.yaml") -Force
        Set-EnginePath (Join-Path $dest "config.yaml") $EngineDir
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $dest "models") | Out-Null
    # The mode manager looks for GGUFs under ~/.nemo/models; point it at the
    # real folder rather than copying gigabytes twice.
    $link = Join-Path $dest "models"
    if ((Get-ChildItem $link -ErrorAction SilentlyContinue).Count -eq 0) {
        cmd /c rmdir "`"$link`"" 2>$null
        cmd /c mklink /J "`"$link`"" "`"$ModelDir`"" 2>$null | Out-Null
    }
} $true | Out-Null

# ====================================================================
#  3. Verdict
# ====================================================================

Head "Summary"

$fails = @($Script:Findings | Where-Object { $_.Status -eq "FAIL" })
$warns = @($Script:Findings | Where-Object { $_.Status -eq "WARN" })
$fixed = @($Script:Findings | Where-Object { $_.Status -eq "FIX" })

if ($fixed.Count) { Say ("  fixed this pass: {0}" -f (($fixed | ForEach-Object { $_.Name }) -join ", ")) "Green" }
if ($warns.Count) { Say ("  warnings: {0}"      -f $warns.Count) "Yellow" }

if ($fails.Count -gt 0) {
    Say ""
    Say "  Not launching. These need attention first:" "Red"
    foreach ($f in $fails) {
        Say ("   * {0}" -f $f.Name) "Red"
        if ($f.Detail) { Say ("     {0}" -f $f.Detail) "DarkYellow" }
    }
    Say ""
    Say "  Run NemoDoc again after fixing -- it will skip everything already done." "Gray"
    Say ("  Full log: {0}" -f $LogPath) "DarkGray"
    Log "=== pass ended with $($fails.Count) failures ==="
    if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" }
    exit 1
}

Say "  Everything checks out." "Green"
Log "=== pass clean ==="

if ($CheckOnly -or $NoLaunch) {
    $why = "-NoLaunch"
    if ($CheckOnly) { $why = "-CheckOnly" }
    Say ("  Launch skipped ({0})." -f $why) "Gray"
    exit 0
}

# ====================================================================
#  4. Launch
# ====================================================================

Head "Starting Nemo"

if (-not $Mode) {
    # Pick by what is actually free right now, not by what is installed.
    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
    # D136: these are what `nemo mode` itself will ask for (model, tools
    # and 300 MB, from config.yaml). Talk was 2200 here against a model
    # measured at 2070 MB; a test keeps the two in step.
    if     ($free -gt 3800) { $Mode = "design" }
    elseif ($free -gt 2800) { $Mode = "talk" }
    else                    { $Mode = "tiny" }
    # Without AVX -- a Sandy Bridge Pentium or Celeron -- a 4B model is too
    # slow to be an everyday default. Design mode stays one click away.
    if (-not $HasAvx -and $Mode -eq "design") {
        $Mode = "talk"
        Say "  No AVX on this CPU: starting in talk mode; choose Design in the window when you need it." "Gray"
    }

    # Picking by free memory alone assumes every mode's model was actually
    # downloaded. It is not: the model loop above skips qwen3-4b/1.7b/coder
    # on anything under 7000 MB total (only gemma3-1b is unconditional), a
    # threshold that has nothing to do with $free above. A machine that
    # lands here -- total just under 7000 MB, but currently with 4000+ MB
    # free -- picked "talk" or "design", was told "Everything checks out",
    # and then failed to launch on a model that was never fetched. Step
    # down to whatever mode's model is actually on disk before handing off.
    $ModeModel = [ordered]@{ design = "qwen3-4b"; talk = "qwen3-1.7b"; tiny = "gemma3-1b" }
    $order = @("design", "talk", "tiny")
    $want = $order.IndexOf($Mode)
    $chosen = $null
    for ($i = $want; $i -lt $order.Count; $i++) {
        $candidate = $order[$i]
        if (Test-Path (Join-Path $ModelDir ($ModeModel[$candidate] + ".gguf"))) {
            $chosen = $candidate
            break
        }
    }
    if (-not $chosen) {
        # Nothing at or below the intended mode is present; the "Models"
        # check above would already have FAILed if nothing at all had
        # downloaded, so this means something above $Mode exists but
        # nothing at or below it does -- state it plainly rather than
        # falling through to the same opaque "no GGUF" error.
        Say ("  No model on disk for {0} mode or anything simpler. Run NemoDoc " -f $Mode) "Red"
        Say "  again to retry the download, or place a GGUF under $ModelDir yourself." "Red"
        if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" }
        exit 1
    }
    if ($chosen -ne $Mode) {
        Say ("  {0} mode's model ({1}) is not on disk -- starting {2} instead, which is." -f `
            $Mode, $ModeModel[$Mode], $chosen) "Yellow"
        $Mode = $chosen
    }
    Say ("  {0} MB free -- selecting {1} mode" -f $free, $Mode) "Gray"
}

& $NemoCmd mode $Mode
if ($LASTEXITCODE -ne 0) {
    Say "  Mode failed to start. Run 'nemo doctor' for detail." "Red"
    if ($Host.Name -eq "ConsoleHost") { Read-Host "Press Enter to close" }
    exit 1
}

$projects = Join-Path $env:USERPROFILE "nemo-projects"
New-Item -ItemType Directory -Force -Path $projects | Out-Null

Say ""
Say "  Nemo is up in $Mode mode." "Green"
# Credits (owner, 2026-11-11): who made everything Nemo is built from, in
# the Storeroom (nemo/credits.py), and the link to it.
$credits = (& $NemoCmd credits 2>$null) | Select-String "^Credits: " | Select-Object -Last 1
if ($credits) { Say ("  Who made what Nemo is built from: " + ($credits.Line -replace "^Credits: ", "")) "Gray" }
Say ""
Say "    nemo new <name> `"<brief>`"   start a project" "Gray"
Say "    nemo run                      run the pipeline" "Gray"
Say "    nemo check                    rerun the checks" "Gray"
Say "    nemo mode off                 free the memory" "Gray"
Say ""

# Open the desktop interface. pythonw has no console window; the command
# line remains available as 'nemo' in any terminal.
if (Test-Path $VenvPyw) {
    Start-Process -FilePath $VenvPyw -ArgumentList "-m", "nemo.gui" -WorkingDirectory $env:USERPROFILE
    Say "  The Nemo window is opening. Next time, use the Nemo shortcut." "Gray"
} else {
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-NoProfile", "-Command",
        "Set-Location '$projects'; `$env:Path = '$scripts;' + `$env:Path; & '$NemoCmd' status"
    )
}
