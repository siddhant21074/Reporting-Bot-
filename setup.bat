@echo off
REM ===========================================================================
REM  SiteReport Bot - one-time setup for Windows
REM
REM  Builds the virtual environment, installs dependencies, prepares storage,
REM  writes .env, creates the database and the first portal login.
REM
REM  Run this once. After that use start.bat and stop.bat.
REM  Safe to re-run: nothing you have already configured is overwritten.
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   SiteReport Bot - Setup
echo ============================================================
echo.

REM --- 1. Find a supported Python -------------------------------------------
REM 3.11 to 3.13. Python 3.14 has no prebuilt pydantic-core wheel yet, so pip
REM tries to compile it and fails without a C toolchain.

set "PY_CMD="
set "PY_VER="

for %%V in (3.13 3.12 3.11) do (
    if not defined PY_CMD (
        py -%%V --version >nul 2>&1
        if !errorlevel! equ 0 (
            set "PY_CMD=py -%%V"
            set "PY_VER=%%V"
        )
    )
)

if not defined PY_CMD (
    python --version >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2" %%a in ('python --version 2^>^&1') do set "FOUND_VER=%%a"
        echo [ERROR] Found Python !FOUND_VER!, but 3.11, 3.12 or 3.13 is required.
    ) else (
        echo [ERROR] Python is not installed, or not on your PATH.
    )
    echo.
    echo     Install Python 3.12 from https://www.python.org/downloads/
    echo     Tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/7] Python %PY_VER% found.
echo.

REM --- 2. Virtual environment ------------------------------------------------
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    echo [2/7] Virtual environment already exists.
) else (
    echo [2/7] Creating the virtual environment ...
    %PY_CMD% -m venv .venv
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo       Created .venv
)
echo.

REM --- 3. Dependencies -------------------------------------------------------
echo [3/7] Installing dependencies. The first run takes a few minutes ...
echo.
"%VENV_PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV_PY%" -m pip install -r requirements.txt --disable-pip-version-check
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] Dependency installation failed. The reason is above.
    pause
    exit /b 1
)
echo.
echo       Dependencies installed.
echo.

REM --- 4. Storage folders ----------------------------------------------------
echo [4/7] Preparing storage folders ...
for %%D in (logs media reports temp fonts run templates) do (
    if not exist "storage\%%D" mkdir "storage\%%D"
)
echo       Done.
echo.

REM --- 5. Configuration ------------------------------------------------------
REM ensure_env.py copies the template, generates SECRET_KEY when it is blank,
REM and lists whatever credentials are still missing. It never overwrites a
REM value you have already set.
echo [5/7] Checking configuration ...
"%VENV_PY%" scripts\ensure_env.py
set "ENV_STATUS=!errorlevel!"
if !ENV_STATUS! equ 1 (
    echo.
    echo [ERROR] Could not prepare .env
    pause
    exit /b 1
)
echo.

REM --- 6. Database -----------------------------------------------------------
REM SQLite by default, so there is nothing to install. Point DATABASE_URL at
REM PostgreSQL in .env when you deploy.
echo [6/7] Preparing the database ...
"%VENV_PY%" -c "import asyncio,sys;sys.path.insert(0,'.');from app.db.base import init_database;asyncio.run(init_database())" >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] Could not create the database. Check DATABASE_URL in .env
    echo.
    "%VENV_PY%" -c "import asyncio,sys;sys.path.insert(0,'.');from app.db.base import init_database;asyncio.run(init_database())"
    pause
    exit /b 1
)
echo       Ready.
echo.

REM --- 7. Portal login -------------------------------------------------------
echo [7/7] Checking the portal login ...
"%VENV_PY%" scripts\has_admin.py >nul 2>&1
if !errorlevel! equ 0 (
    echo       An administrator login already exists.
) else (
    echo.
    echo       No portal login yet. Let's create the administrator account.
    echo       This is what you will sign in to the dashboard with.
    echo.
    "%VENV_PY%" scripts\make_admin.py --create
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] The login was not created. Try one of these:
        echo.
        echo           .venv\Scripts\python.exe scripts\make_admin.py --create
        echo           .venv\Scripts\python.exe scripts\make_admin.py --create --password "your password"
        echo           .venv\Scripts\python.exe scripts\make_admin.py --create --random
        echo.
        echo         Note: at the hidden prompt your typing does not appear on
        echo         screen at all. That is normal - type it and press Enter.
    )
)
echo.

REM --- Done ------------------------------------------------------------------
echo ============================================================
echo   Setup complete
echo ============================================================
echo.

if !ENV_STATUS! equ 2 (
    echo   Before the bot can send or receive, open .env and fill in the
    echo   credentials listed above.
    echo.
    echo   The portal will still start without them - the dashboard shows
    echo   exactly what is missing on its System status panel.
    echo.
)

echo   Start the server:  start.bat
echo   Then open:         http://localhost:8000
echo   Stop the server:   stop.bat
echo.
echo   Try report generation without WhatsApp:
echo     .venv\Scripts\python.exe scripts\cli_test.py --text "Fixed two bugs today."
echo.
pause
endlocal
