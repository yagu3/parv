@echo off
title YaguAI
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found! Install from python.org
    pause
    exit /b 1
)
python main.py
pause
