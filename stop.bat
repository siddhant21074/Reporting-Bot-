@echo off
REM ===========================================================================
REM  SiteReport Bot - stop the server
REM
REM    stop.bat           stop the server that start.bat launched
REM    stop.bat 8000      also free anything else still holding that port
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PID_FILE=%~dp0storage\run\app.pid"
set "STOPPED="

echo.
echo ============================================================
echo   SiteReport Bot - Stop
echo ============================================================
echo.

REM --- 1. Stop the process start.bat recorded --------------------------------
if exist "%PID_FILE%" (
    set /p APP_PID=<"%PID_FILE%"

    tasklist /fi "PID eq !APP_PID!" 2>nul | findstr /i "python" >nul
    if !errorlevel! equ 0 (
        echo Stopping the server ^(PID !APP_PID!^) ...
        REM /t also stops the uvicorn reloader's child process.
        taskkill /pid !APP_PID! /t /f >nul 2>&1
        if !errorlevel! equ 0 (
            echo   Stopped.
            set "STOPPED=1"
        ) else (
            echo   [ERROR] Could not stop PID !APP_PID!.
            echo           Try running stop.bat as Administrator.
        )
    ) else (
        echo The recorded process ^(PID !APP_PID!^) is not running.
    )
    del "%PID_FILE%" >nul 2>&1
) else (
    echo No running server was recorded by start.bat.
)

REM --- 2. Optionally free a specific port ------------------------------------
REM Covers a server started some other way, or one whose PID file was lost.
if not "%~1"=="" (
    echo.
    echo Checking port %~1 ...
    set "FOUND_PORT="
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING"') do (
        if not "%%P"=="0" (
            echo   Port %~1 is held by PID %%P. Stopping it ...
            taskkill /pid %%P /t /f >nul 2>&1
            if !errorlevel! equ 0 (
                echo   Stopped.
                set "STOPPED=1"
                set "FOUND_PORT=1"
            ) else (
                echo   [ERROR] Could not stop PID %%P.
                echo           Try running stop.bat as Administrator.
            )
        )
    )
    if not defined FOUND_PORT echo   Port %~1 is free.
)

echo.
if defined STOPPED (
    echo   The portal is now offline.
) else (
    echo   Nothing was running.
)
echo.
echo   Start it again with: start.bat
echo.
endlocal
