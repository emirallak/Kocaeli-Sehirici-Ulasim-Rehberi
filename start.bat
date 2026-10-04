@echo off
setlocal
title Kocaeli Rota - Server
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "KOCAELI_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto python_ready
)
if exist "venv\Scripts\python.exe" (
    set "KOCAELI_PYTHON=%~dp0venv\Scripts\python.exe"
    goto python_ready
)
where python >nul 2>&1
if not errorlevel 1 (
    set "KOCAELI_PYTHON=python"
    goto python_ready
)
where py >nul 2>&1
if not errorlevel 1 (
    set "KOCAELI_PYTHON=py"
    goto python_ready
)
echo Python was not found. Install Python and run this file again.
goto finished

:python_ready
"%KOCAELI_PYTHON%" -c "import fastapi, pydantic, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Application dependencies are missing. Run:
    echo "%KOCAELI_PYTHON%" -m pip install -r requirements.txt
    goto finished
)
if not defined KOCAELI_PORT set "KOCAELI_PORT=8000"
echo Kocaeli Rota: http://127.0.0.1:%KOCAELI_PORT%/
echo Line information: http://127.0.0.1:%KOCAELI_PORT%/line-info
echo First startup may take a moment while transit data loads.
echo Keep this window open to see logs. Press Ctrl+C to stop the server.
echo.
"%KOCAELI_PYTHON%" -m uvicorn api.index:app --host 127.0.0.1 --port "%KOCAELI_PORT%"

:finished
echo.
echo Server stopped or could not start. You may close this window.
pause
endlocal
