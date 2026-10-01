@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" -m owlthread app
) else if exist "%~dp0artifacts\dist\1.7.0\OwlThread\OwlThread.exe" (
  start "" "%~dp0artifacts\dist\1.7.0\OwlThread\OwlThread.exe" app
) else if exist "%~dp0artifacts\dist\OwlThread\OwlThread.exe" (
  start "" "%~dp0artifacts\dist\OwlThread\OwlThread.exe" app
) else (
  echo Install OwlThread first. See README.md for the setup steps.
  pause
)
