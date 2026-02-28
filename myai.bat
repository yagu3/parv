@echo off
setlocal enabledelayedexpansion
title OpenClaw ^& Llama.cpp Interactive CLI
color 0A

:: --- SETTINGS FILE SETUP ---
set "CONFIG_FILE=ai_preferences.txt"
set "JSON_FILE=openclaw_config.json"
set "PORT_LLAMA=8080"
set "PORT_CLAW=18789"
set "AUTH_TOKEN=b35761a4ed1f1e01b139aa4ddd4cd7b45bc51631b1483d0f"

:: Load preferences if they exist
if exist "%CONFIG_FILE%" (
    for /f "usebackq delims=" %%x in ("%CONFIG_FILE%") do set "%%x"
)

:: --- INTERACTIVE PROMPTS FOR MISSING SETUP ---
echo ==================================================
echo       OpenClaw + Llama.cpp CLI Environment
echo ==================================================
echo.

if "%LLAMA_EXE%"=="" (
    set /p LLAMA_EXE="Drag and drop 'llama-server.exe' here and press Enter: "
    set LLAMA_EXE=!LLAMA_EXE:"=!
)
if "%GGUF_MODEL%"=="" (
    set /p GGUF_MODEL="Drag and drop your '.gguf' model file here: "
    set GGUF_MODEL=!GGUF_MODEL:"=!
)
if "%OPENCLAW_EXE%"=="" (
    set /p OPENCLAW_EXE="Drag and drop your 'OpenClaw.exe' here: "
    set OPENCLAW_EXE=!OPENCLAW_EXE:"=!
)
if "%WORKSPACE_DIR%"=="" (
    set /p WORKSPACE_DIR="Enter path for OpenClaw Workspace (e.g. C:\clawd): "
    set WORKSPACE_DIR=!WORKSPACE_DIR:"=!
)

:: Save preferences so you don't have to type them again
(
echo LLAMA_EXE=%LLAMA_EXE%
echo GGUF_MODEL=%GGUF_MODEL%
echo OPENCLAW_EXE=%OPENCLAW_EXE%
echo WORKSPACE_DIR=%WORKSPACE_DIR%
) > "%CONFIG_FILE%"

:: Get just the model file name (e.g., model.gguf)
for %%F in ("%GGUF_MODEL%") do set "MODEL_NAME=%%~nxF"

:: Replace backslashes with forward slashes for JSON formatting
set "WORKSPACE_JSON=!WORKSPACE_DIR:\=/!"

echo.
echo [*] Preferences loaded.

:: --- PROCESS MANAGEMENT (START & HIDE) ---

:: 1. Start Llama.cpp Server
tasklist /FI "IMAGENAME eq llama-server.exe" 2>NUL | find /I /N "llama-server.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [*] llama-server.exe is already running. Skipping...
) else (
    echo [*] Starting llama-server.exe in the background...
    powershell -WindowStyle Hidden -Command "Start-Process -NoNewWindow -FilePath '%LLAMA_EXE%' -ArgumentList '-m \"%GGUF_MODEL%\" -c 8192 --port %PORT_LLAMA%'"
)

:: 2. Generate OpenClaw JSON Config using PowerShell (to ensure valid formatting)
echo [*] Generating %JSON_FILE%...
powershell -NoProfile -Command "$config = @'{ \"messages\": { \"ackReactionScope\": \"group-mentions\" }, \"models\": { \"providers\": { \"llamacpp\": { \"baseUrl\": \"http://127.0.0.1:%PORT_LLAMA%/v1\", \"apiKey\": \"local\", \"api\": \"openai-responses\", \"models\": [ { \"id\": \"%MODEL_NAME%\", \"name\": \"%MODEL_NAME%\", \"reasoning\": true, \"input\": [\"text\"], \"contextWindow\": 128000, \"maxTokens\": 8192 } ] } } }, \"agents\": { \"defaults\": { \"model\": { \"primary\": \"llamacpp/%MODEL_NAME%\" }, \"maxConcurrent\": 4, \"workspace\": \"%WORKSPACE_JSON%\" } }, \"gateway\": { \"mode\": \"local\", \"auth\": { \"mode\": \"token\", \"token\": \"%AUTH_TOKEN%\" }, \"port\": %PORT_CLAW%, \"bind\": \"loopback\", \"tailscale\": { \"mode\": \"off\" } } }'@; $config | Out-File -Encoding utf8 '%JSON_FILE%'"

:: 3. Start OpenClaw
for %%F in ("%OPENCLAW_EXE%") do set "OC_EXE_NAME=%%~nxF"
tasklist /FI "IMAGENAME eq %OC_EXE_NAME%" 2>NUL | find /I /N "%OC_EXE_NAME%">NUL
if "%ERRORLEVEL%"=="0" (
    echo [*] OpenClaw is already running. Skipping...
) else (
    echo [*] Starting OpenClaw in the background...
    :: Adjust the argument "-c" based on how OpenClaw accepts custom configs. 
    powershell -WindowStyle Hidden -Command "Start-Process -NoNewWindow -FilePath '%OPENCLAW_EXE%' -ArgumentList '--config \"%CD%\%JSON_FILE%\"'"
)

echo [*] Waiting 5 seconds for servers to warm up...
timeout /t 5 /nobreak > nul
cls

:: --- INTERACTIVE CHAT LOOP ---
echo ==================================================
echo   System Ready! Using model: %MODEL_NAME%
echo   Type 'exit' to quit. Type 'cls' to clear screen.
echo ==================================================
echo.

:CHAT_LOOP
set "USER_INPUT="
set /p USER_INPUT="You: "

if /I "%USER_INPUT%"=="exit" goto CLEANUP
if /I "%USER_INPUT%"=="cls" (
    cls
    echo ==================================================
    echo   System Ready! Using model: %MODEL_NAME%
    echo   Type 'exit' to quit. Type 'cls' to clear screen.
    echo ==================================================
    goto CHAT_LOOP
)
if "%USER_INPUT%"=="" goto CHAT_LOOP

echo.
echo AI is thinking...

:: Use PowerShell to send the prompt to OpenClaw via API, parse the JSON response, and print ONLY the text.
powershell -NoProfile -Command "$ErrorActionPreference = 'SilentlyContinue'; $body = @{ model = '%MODEL_NAME%'; messages = @( @{ role = 'user'; content = '%USER_INPUT%' } ) } | ConvertTo-Json; $headers = @{ Authorization = 'Bearer %AUTH_TOKEN%' }; try { $response = Invoke-RestMethod -Uri 'http://127.0.0.1:%PORT_CLAW%/v1/chat/completions' -Method Post -Headers $headers -Body $body -ContentType 'application/json'; Write-Host "`nOpenClaw: " -ForegroundColor Cyan -NoNewline; Write-Host $response.choices[0].message.content } catch { Write-Host "`n[!] Failed to get response. Is OpenClaw ready?" -ForegroundColor Red }"

echo.
echo --------------------------------------------------
goto CHAT_LOOP


:: --- CLEANUP ON EXIT ---
:CLEANUP
echo.
set /p KILL_PROCS="Do you want to shut down the background Llama and OpenClaw processes? (Y/N): "
if /I "%KILL_PROCS%"=="Y" (
    echo Killing Llama.cpp...
    taskkill /F /IM llama-server.exe >nul 2>&1
    echo Killing OpenClaw...
    taskkill /F /IM %OC_EXE_NAME% >nul 2>&1
    echo Done.
)
exit