@echo off
setlocal
REM start.cmd - launch the backend and frontend development servers.
REM Set VC_START_DRY_RUN=1 to resolve and print commands without modifying files
REM or opening windows.

set "ROOT=%~dp0"
cd /d "%ROOT%" || exit /b 1
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "FRONTEND=%ROOT%frontend"

if /i "%VC_START_DRY_RUN%"=="1" (
    echo ROOT=%CD%
    echo BACKEND="%PYTHON%" -m uvicorn backend.main:app --reload --port 8000
    echo FRONTEND_DIR=%FRONTEND%
    echo FRONTEND=npm run dev
    exit /b 0
)

if not exist "%PYTHON%" (
    echo [ERROR] Missing "%PYTHON%".
    echo Run the Installation commands in README.md first.
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm is not available on PATH. Install Node.js 22.18 or newer.
    exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
    echo [ERROR] Frontend dependencies are missing.
    echo Run: cd /d "%FRONTEND%" ^&^& npm ci
    exit /b 1
)

echo.
echo   ^<^< WEIPING_COUNCIL ^>^>
echo.

if not exist "%ROOT%.env" (
    echo   [WARN] .env not found. Copying .env.example...
    copy "%ROOT%.env.example" "%ROOT%.env" >nul || exit /b 1
    echo   [WARN] Add provider API keys to "%ROOT%.env"
    echo.
)

echo   Starting backend on http://localhost:8000 ...
start "vc-backend" /D "%ROOT%" "%ComSpec%" /d /k ""%PYTHON%" -m uvicorn backend.main:app --reload --port 8000"
if errorlevel 1 exit /b 1

timeout /t 2 /nobreak >nul
echo   Starting frontend on http://localhost:5173 ...
start "vc-frontend" /D "%FRONTEND%" "%ComSpec%" /d /k "npm run dev"
if errorlevel 1 exit /b 1

echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   API docs: http://localhost:8000/docs
echo.
echo   CLI:  "%PYTHON%" vc.py
echo.
endlocal
