<#
    Install Nemo on Windows 11 (Fujitsu Lifebook AH531).

    This is now the primary install path, because the machine already runs
    Windows 11. It works, and Sandy Bridge has SSE4.2 and POPCNT so 24H2 and
    later keep booting -- but two things need handling that do not arise on
    supported hardware:

      * llama.cpp must be the AVX-only build. No AVX2 on this CPU.
      * there is no graphics driver, so OpenGL comes from Mesa in software.

    Run as Administrator.
#>

param(
    [string]$Prefix = "C:\Nemo",
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

# --- sanity ---------------------------------------------------------
Step "checking this machine"
$os  = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_Processor).Name
$gpu = (Get-CimInstance Win32_VideoController).Name
$totalMB = [math]::Round($os.TotalVisibleMemorySize/1024)
$freeMB  = [math]::Round($os.FreePhysicalMemory/1024)
Write-Host "    $cpu"
Write-Host "    $gpu"
Write-Host "    $totalMB MB RAM, $freeMB MB free"

if ($totalMB -lt 7000) {
    Write-Host "    Under 8 GB. Nemo will work in talk mode only." -ForegroundColor Yellow
}
if ($gpu -match "Basic Display") {
    Write-Host "    No graphics driver. KiCad and FreeCAD need Mesa -- handled below." -ForegroundColor Yellow
}

# --- winget packages ------------------------------------------------
Step "installing tools"
$pkgs = @(
    @{ id = "Python.Python.3.12";  name = "Python" },
    @{ id = "Git.Git";             name = "Git" },
    @{ id = "KiCad.KiCad";         name = "KiCad" },
    @{ id = "Graphviz.Graphviz";   name = "Graphviz (WireViz needs it)" }
)
foreach ($p in $pkgs) {
    Write-Host "    $($p.name)"
    winget install --id $p.id --silent --accept-package-agreements `
        --accept-source-agreements --disable-interactivity 2>$null | Out-Null
}
Write-Host "    FreeCAD is ~1.5 GB and only needed for hand edits -- skipping."
Write-Host "    Install later with: winget install FreeCAD.FreeCAD"

# --- python environment ---------------------------------------------
Step "python environment"
New-Item -ItemType Directory -Force -Path $Prefix, "$Prefix\models" | Out-Null
python -m venv "$Prefix\venv"
& "$Prefix\venv\Scripts\pip.exe" install --quiet --upgrade pip wheel
& "$Prefix\venv\Scripts\pip.exe" install --quiet pyyaml wireviz trimesh numpy platformio
Write-Host "    cadquery and skidl are large and slow to build on two cores."
Write-Host "    Install when you need them:"
Write-Host "      $Prefix\venv\Scripts\pip.exe install cadquery skidl"

Step "nemo"
# The distribution folder is the repo root; this script sits one level
# down in manual\. Walking further up was the bug that made this script
# fail silently under $ErrorActionPreference = "Stop".
$repo = Split-Path $PSScriptRoot -Parent
& "$Prefix\venv\Scripts\pip.exe" install --quiet -e $repo

# --- llama.cpp -------------------------------------------------------
Step "llama.cpp"
Write-Host @"
    NemoDoc.cmd installs this automatically. By hand:

      https://github.com/ggml-org/llama.cpp/releases/tag/b11175
      choose:  llama-b11175-bin-win-cpu-x64.zip
      NOT:     "Source code (zip)" -- that contains llama.h and no
               llama-server.exe

    Unzip EVERYTHING to $Prefix\engine\ . The .exe needs the DLLs
    beside it. The package picks its Sandy Bridge backend at runtime, so
    there is no longer a separate AVX build to choose.
"@ -ForegroundColor Yellow

# --- OpenGL ----------------------------------------------------------
Step "OpenGL for KiCad"
Write-Host @"
    Intel never shipped a Windows 11 driver for HD Graphics 3000, so there
    is no hardware OpenGL on this machine. Run:

      .\setup-mesa.ps1

    to install Mesa's software renderer beside KiCad and FreeCAD.
"@ -ForegroundColor Yellow

# --- memory ----------------------------------------------------------
Step "memory"
Write-Host "    Run .\trim.ps1 to recover ~800 MB to 1 GB from Windows."

# --- path ------------------------------------------------------------
Step "PATH"
$paths = @("$Prefix\venv\Scripts", "$Prefix\engine")
$cur = [Environment]::GetEnvironmentVariable("Path", "User")
foreach ($p in $paths) { if ($cur -notlike "*$p*") { $cur = "$cur;$p" } }
[Environment]::SetEnvironmentVariable("Path", $cur, "User")

Write-Host @"

Done. Open a new terminal, then:

  nemo doctor          check the machine
  nemo mode talk       load Qwen3-1.7B
  nemo new chest "RFID card player in a treasure chest"

Keys for the tier 2 reviewer go in the user environment and nowhere else:

  setx NEMO_OPENROUTER_KEY "..."

"@ -ForegroundColor Green
