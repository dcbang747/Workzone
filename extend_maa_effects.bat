@echo off
REM Batch script to run extend_maa_effects.py
REM This script rebuilds the MAA effects in effects_to_change.txt
REM to include every culturally-recruitable Men-At-Arms type from the
REM lotr_*_regiment_types.txt files.

setlocal enabledelayedexpansion

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0

REM Change to that directory
cd /d "%SCRIPT_DIR%"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.7+ and ensure it's in your system PATH.
    pause
    exit /b 1
)

REM Run the script
echo Running extend_maa_effects.py...
echo.
python extend_maa_effects.py

REM Check if script succeeded
if errorlevel 1 (
    echo.
    echo ERROR: Script failed with exit code %ERRORLEVEL%.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo SUCCESS: effects_to_change.txt has been updated.
pause
exit /b 0
