<#
    Software OpenGL for KiCad and FreeCAD on Windows 11.

    Intel never shipped a Windows 11 driver for HD Graphics 3000, and there
    is no way to obtain one. Windows falls back to the Basic Display Adapter,
    which provides no OpenGL beyond version 1.1. KiCad's accelerated canvas
    needs 3.0 and FreeCAD's 3D view needs 2.1, so both are broken out of the
    box on this machine.

    Mesa's llvmpipe renderer implements OpenGL 4.5 in software on the CPU.
    Dropping its opengl32.dll next to an application makes that application
    -- and only that application -- use it. This is slow on two Sandy Bridge
    cores, but it is the difference between a working CAD viewport and none.

    Run as Administrator.
#>

param(
    [string]$MesaZip = "",
    [switch]$Revert
)

$ErrorActionPreference = "Stop"

$targets = @(
    "C:\Program Files\KiCad\9.0\bin",
    "C:\Program Files\KiCad\bin",
    "C:\Program Files\FreeCAD 1.0\bin",
    "C:\Nemo\tools\kicad\bin"
) | Where-Object { Test-Path $_ }

if ($targets.Count -eq 0) {
    Write-Host "No KiCad or FreeCAD install found. Install them first." -ForegroundColor Yellow
    exit 1
}

if ($Revert) {
    foreach ($t in $targets) {
        $dll = Join-Path $t "opengl32.dll"
        if (Test-Path $dll) {
            Remove-Item $dll -Force
            Write-Host "removed $dll"
        }
    }
    Write-Host "Reverted. Applications will use the system OpenGL again -- which on this machine means none."
    exit 0
}

if (-not $MesaZip) {
    Write-Host @"
This script does not download Mesa for you, because the build you want
depends on your CPU and the project moves.

  1. Get a Windows Mesa3D build (pal1000's mesa-dist-win is the usual
     source: https://github.com/pal1000/mesa-dist-win/releases)
  2. Choose the MSVC x64 package. Pick the 'desktop OpenGL drivers' variant.
  3. Re-run:  .\setup-mesa.ps1 -MesaZip C:\path\to\mesa.7z-or-zip

Note for this CPU: choose llvmpipe, not the newer softpipe or the
Zink/Vulkan variants. Sandy Bridge has no AVX2, so a Mesa build compiled
for AVX2 will fault exactly the same way an AVX2 llama.cpp build does.
"@ -ForegroundColor Cyan
    exit 0
}

if (-not (Test-Path $MesaZip)) { throw "not found: $MesaZip" }

$staging = Join-Path $env:TEMP "nemo-mesa"
Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $staging | Out-Null

if ($MesaZip -like "*.zip") {
    Expand-Archive -Path $MesaZip -DestinationPath $staging
} else {
    $7z = Get-Command 7z -ErrorAction SilentlyContinue
    if (-not $7z) { throw "7-Zip needed for .7z archives. Install it, or unpack by hand and point -MesaZip at a .zip." }
    & 7z x $MesaZip "-o$staging" -y | Out-Null
}

$dll = Get-ChildItem $staging -Recurse -Filter "opengl32.dll" |
       Where-Object { $_.FullName -match "x64" } |
       Select-Object -First 1
if (-not $dll) { $dll = Get-ChildItem $staging -Recurse -Filter "opengl32.dll" | Select-Object -First 1 }
if (-not $dll) { throw "no opengl32.dll in that archive" }

foreach ($t in $targets) {
    Copy-Item $dll.FullName (Join-Path $t "opengl32.dll") -Force
    Write-Host "installed software OpenGL into $t" -ForegroundColor Green
}

Write-Host @"

Done. Set these before launching, to force llvmpipe and keep it predictable:

  setx GALLIUM_DRIVER llvmpipe
  setx LP_NUM_THREADS 2          # two cores; more just thrashes

Expect FreeCAD's viewport to be usable for single parts and painful for
large assemblies. KiCad's schematic editor will be fine. If the 3D board
viewer is unbearable, that is expected -- it is rendering on the CPU.

Undo with:  .\setup-mesa.ps1 -Revert
"@ -ForegroundColor Cyan
