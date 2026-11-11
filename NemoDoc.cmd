@echo off
REM ====================================================================
REM  NemoDoc -- double-click this. It is the only thing you need to run.
REM
REM  Checks the machine, installs or repairs whatever is missing, and
REM  launches Nemo if everything passes. Safe to run every time; it skips
REM  anything already done.
REM
REM  The -ExecutionPolicy Bypass below is why this wrapper exists. Windows
REM  refuses to run .ps1 files by default, which is the single most common
REM  reason a PowerShell installer appears to do nothing at all.
REM ====================================================================
setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo PowerShell was not found. It ships with Windows, so something is wrong
  echo with this install. Try: sfc /scannow
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0NemoDoc.ps1" %*
set RC=%ERRORLEVEL%

if %RC% NEQ 0 (
  echo.
  echo NemoDoc finished with problems. See the list above, or C:\Nemo\nemodoc.log
  pause
)
exit /b %RC%
