@echo off
title Discord Bridge
echo.
echo ========================================
echo   Starting Discord Bridge
echo ========================================
echo.

REM Automatically navigates to the folder where this .bat file is located
cd /d "%~dp0"

REM Launches the Discord bridge in a new window
echo Launching Discord bridge...
start "Discord Bridge" cmd /k "python tot_discord_bridge.py"

echo.
echo ========================================
echo   Everything is running!
echo ========================================
pause
