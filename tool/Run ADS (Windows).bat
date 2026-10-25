@echo off
rem Double-click to open the point-and-click window in your browser.
rem Or drag a USB/memory-card image onto this file for a quick report on it.
cd /d "%~dp0"
set PY=python
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3
if "%~1"=="" (
    %PY% -m ads gui
) else (
    %PY% start.py %*
)
if errorlevel 1 pause
