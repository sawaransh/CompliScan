@echo off
REM CompliScan - Quick Start Script for Windows

echo ========================================
echo   CompliScan - SIH 2026 Prototype
echo ========================================
echo.

REM Check prerequisites
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Python is not installed. Please install Python 3.10+ first.
    pause
    exit /b 1
)
echo ✅ Python found

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Node.js is not installed. Please install Node.js 18+ first.
    pause
    exit /b 1
)
echo ✅ Node.js found

where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ npm is not installed. Please install Node.js (includes npm) first.
    pause
    exit /b 1
)
echo ✅ npm found

echo.
echo Setting up backend...
cd /d "%~dp0backend"

if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat
echo Installing Python dependencies...
pip install -q -r requirements.txt

echo.
echo Setting up frontend...
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo Installing Node dependencies...
    npm install
)

echo.
echo ========================================
echo   Starting CompliScan...
echo ========================================
echo.
echo Backend will run on: http://localhost:8000
echo Frontend will run on: http://localhost:3000
echo.
echo Press Ctrl+C to stop both servers
echo.

REM Start backend in background
cd /d "%~dp0backend"
call venv\Scripts\activate.bat
start "CompliScan Backend" cmd /k "python -m app.main"

REM Wait a moment for backend to start
timeout /t 3 /nobreak >nul

REM Start frontend
cd /d "%~dp0frontend"
start "CompliScan Frontend" cmd /k "npm run dev"

echo.
echo Both servers started in separate windows.
echo Close the command windows to stop the servers.
pause