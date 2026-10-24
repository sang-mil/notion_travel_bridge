@echo off
setlocal
set "SCRIPT=%~dp0quick_start.ps1"
if not exist "%SCRIPT%" (
  echo Cannot find quick_start.ps1 in this folder.
  echo Keep QuickStart.bat and quick_start.ps1 together.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Quick Start exited with an error. Review the messages above.
  pause
)
endlocal & exit /b %RESULT%
