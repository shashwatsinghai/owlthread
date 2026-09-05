@echo off
title OwlThread Desktop
echo ========================================================
echo               OwlThread Windows Desktop
echo          Ambient Memory Engine Command Center
echo ========================================================
echo.
echo Launching OwlThread Desktop Application...
python -m owlthread.cli app
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error code %errorlevel%.
    pause
)
