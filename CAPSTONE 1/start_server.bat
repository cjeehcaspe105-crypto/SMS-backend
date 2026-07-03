@echo off
title VMC Attendance System - Server
color 0A

echo.
echo  ============================================
echo   VMC Attendance System - Local Server
echo   Villagers Montessori College
echo  ============================================
echo.

:: ── Auto-detect Python ──────────────────────────────────────
set PYTHON=

:: Check if python is already in PATH
where python >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=python
    goto :found_python
)

:: Try common install locations for the current user
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
    goto :found_python
)
if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe" (
    set PYTHON=%LOCALAPPDATA%\Programs\Python\Python39\python.exe
    goto :found_python
)
:: Try system-wide installs
if exist "C:\Python312\python.exe" ( set PYTHON=C:\Python312\python.exe & goto :found_python )
if exist "C:\Python311\python.exe" ( set PYTHON=C:\Python311\python.exe & goto :found_python )
if exist "C:\Python310\python.exe" ( set PYTHON=C:\Python310\python.exe & goto :found_python )

echo [ERROR] Python not found on this system.
echo         Please install Python 3.9+ from https://www.python.org/downloads/
echo         Make sure to check "Add Python to PATH" during installation.
pause
exit /b 1

:found_python
echo [INFO] Using Python: %PYTHON%

:: ── Navigate to project directory ──────────────────────────
cd /d "%~dp0"

:: ── Install dependencies if needed ──────────────────────────
echo [INFO] Checking dependencies...
"%PYTHON%" -m pip install flask flask-cors --quiet --disable-pip-version-check
echo [INFO] Dependencies OK.
echo.

:: ── Initialize database if vmc.db is missing ───────────────
if not exist "vmc.db" (
    echo [INFO] Database not found. Initializing...
    "%PYTHON%" database.py
    echo [INFO] Database created.
    echo.
)

:: ── Start the Flask server ─────────────────────────────────
echo [INFO] Starting server on http://localhost:5000
echo [INFO] Press CTRL+C to stop the server.
echo.
echo  Open your browser and go to: http://localhost:5000
echo  Default login  -> username: admin  password: admin123
echo.
echo  ============================================
echo.

"%PYTHON%" server.py

pause
