@echo off
title VMC Attendance System - Setup
color 0B

echo.
echo  ============================================
echo   VMC Attendance System - First-Time Setup
echo   Villagers Montessori College
echo  ============================================
echo.

:: ── Locate Python ──────────────────────────────────────────
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

echo [ERROR] Python not found on this system.
echo         Please install Python 3.9+ from https://www.python.org/downloads/
pause
exit /b 1

:found_python
echo [OK] Python found: %PYTHON%

:: ── Navigate to project directory ──────────────────────────
cd /d "%~dp0"

:: ── Install dependencies ────────────────────────────────────
echo.
echo [INFO] Installing required Python packages...
"%PYTHON%" -m pip install flask flask-cors --quiet
echo [OK] Packages installed.

:: ── Initialize the database ────────────────────────────────
echo.
echo [INFO] Initializing database (vmc.db)...
"%PYTHON%" database.py
echo [OK] Database ready.

:: ── Seed sample data ───────────────────────────────────────
echo.
echo [INFO] Seeding sample student data...
"%PYTHON%" seed_db.py

echo.
echo  ============================================
echo   Setup complete! 
echo   Run start_server.bat to launch the app.
echo   Then open: http://localhost:5000
echo   Login: admin / admin123
echo  ============================================
echo.
pause
