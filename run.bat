@echo off
title YaguAI Launcher
:: Check for Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3 is required.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
:: Run the main script
python "%~dp0myai.py" %*
if errorlevel 1 (
    echo.
    echo [!] Script exited with an error.
    pause
)
