@echo off
REM ===========================================================================
REM  SiteReport Bot - start the server and the portal
REM
REM    start.bat                start in the background, then open the portal
REM    start.bat 9000           ... on a different port
REM    start.bat console        run in this window, Ctrl+C to stop
REM    start.bat console 9000   ... on a different port
REM    start.bat quiet          start without opening the browser
REM
REM  Reload-on-save switches on automatically when ENVIRONMENT is development.
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PID_FILE=%~dp0storage\run\app.pid"
set "LOG_FILE=%~dp0storage\logs\app.log"
set "ERR_FILE=%~dp0storage\logs\app.err.log"

REM --- Preconditions ---------------------------------------------------------
if not exist "%VENV_PY%" (
    echo.
    echo [ERROR] No virtual environment found.
    echo         Run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo [ERROR] No .env file found.
    echo         Run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "storage\run"  mkdir "storage\run"
if not exist "storage\logs" mkdir "storage\logs"

REM --- Arguments -------------------------------------------------------------
set "MODE=background"
set "PORT=8000"
set "OPEN_BROWSER=1"

if /i "%~1"=="console" (
    set "MODE=console"
    set "OPEN_BROWSER=0"
    if not "%~2"=="" set "PORT=%~2"
) else if /i "%~1"=="quiet" (
    set "OPEN_BROWSER=0"
    if not "%~2"=="" set "PORT=%~2"
) else (
    if not "%~1"=="" set "PORT=%~1"
)

REM --- Reload only in development -------------------------------------------
set "RELOAD="
findstr /i /r /c:"^ENVIRONMENT=.*development" ".env" >nul 2>&1
if !errorlevel! equ 0 set "RELOAD=--reload"

REM --- Is the port in use? ----------------------------------------------------
set "PORT_BUSY="
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 set "PORT_BUSY=1"

REM --- Refuse to double-start ------------------------------------------------
REM Both conditions have to hold: a live python process AND something actually
REM listening. Checking the PID alone would block forever once Windows recycles
REM that number onto an unrelated python process.
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /fi "PID eq !OLD_PID!" 2>nul | findstr /i "python" >nul
    if !errorlevel! equ 0 if defined PORT_BUSY (
        echo.
        echo [ERROR] The server is already running as PID !OLD_PID!.
        echo         Open http://localhost:%PORT% or run stop.bat first.
        echo.
        pause
        exit /b 1
    )
    echo Clearing a stale record of PID !OLD_PID! ...
    del "%PID_FILE%" >nul 2>&1
)

REM --- Refuse a port another program is using --------------------------------
if defined PORT_BUSY (
    echo.
    echo [ERROR] Port %PORT% is already in use by another program.
    echo         Choose another:  start.bat 8001
    echo         Or free it:      stop.bat %PORT%
    echo.
    pause
    exit /b 1
)

REM --- Warn when there is no way to sign in ----------------------------------
set "NO_LOGIN="
"%VENV_PY%" scripts\has_admin.py >nul 2>&1
if !errorlevel! neq 0 set "NO_LOGIN=1"

echo.
echo ============================================================
echo   SiteReport Bot
echo ============================================================
echo   Portal   : http://localhost:%PORT%
echo   Health   : http://localhost:%PORT%/health
if defined RELOAD (
    echo   Mode     : development ^(reloads when you edit a file^)
    echo   API docs : http://localhost:%PORT%/docs
) else (
    echo   Mode     : production
)
echo ============================================================
echo.

if defined NO_LOGIN (
    echo [WARN]  No portal login exists yet, so you cannot sign in.
    echo         Create one:  .venv\Scripts\python.exe scripts\make_admin.py --create
    echo.
)

if /i "%MODE%"=="console" goto :run_console
goto :run_background


:run_console
echo Running in this window. Press Ctrl+C to stop.
echo.
"%VENV_PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% %RELOAD%
goto :end


:run_background
echo Starting ...

REM Start-Process reports the PID, which is what stop.bat needs. Output goes to
REM the log files so nothing is lost once the hidden window is gone.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Start-Process -FilePath '%VENV_PY%' " ^
  "-ArgumentList '-m','uvicorn','app.main:app','--host','0.0.0.0','--port','%PORT%' " ^
  "-WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru " ^
  "-RedirectStandardOutput '%LOG_FILE%' -RedirectStandardError '%ERR_FILE%'; " ^
  "$p.Id | Out-File -Encoding ascii -NoNewline '%PID_FILE%'"

REM Wait for the port to answer rather than guessing at a fixed delay: startup
REM builds the database and loads saved settings, which is slower the first time.
set "READY="
for /l %%i in (1,1,20) do (
    if not defined READY (
        powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/health' -UseBasicParsing -TimeoutSec 2)|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
        if !errorlevel! equ 0 (
            set "READY=1"
        ) else (
            powershell -NoProfile -Command "Start-Sleep -Milliseconds 700" >nul 2>&1
        )
    )
)

if not defined READY (
    echo.
    echo [ERROR] The server did not come up. Last lines of the error log:
    echo.
    powershell -NoProfile -Command "if (Test-Path '%ERR_FILE%') { Get-Content '%ERR_FILE%' -Tail 20 }"
    echo.
    if exist "%PID_FILE%" (
        set /p BAD_PID=<"%PID_FILE%"
        taskkill /pid !BAD_PID! /t /f >nul 2>&1
        del "%PID_FILE%" >nul 2>&1
    )
    pause
    exit /b 1
)

set /p NEW_PID=<"%PID_FILE%"

echo.
echo   Running. PID !NEW_PID!
echo.
echo   Portal : http://localhost:%PORT%
echo   Logs   : storage\logs\app.log
echo   Errors : storage\logs\app.err.log
echo   Stop   : stop.bat
echo.

if "%OPEN_BROWSER%"=="1" start "" "http://localhost:%PORT%"

:end
endlocal
