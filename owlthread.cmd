@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m owlthread %*
) else if exist "%~dp0artifacts\dist\OwlThread\owlthread-cli.exe" (
  "%~dp0artifacts\dist\OwlThread\owlthread-cli.exe" %*
) else (
  python -m owlthread %*
)
