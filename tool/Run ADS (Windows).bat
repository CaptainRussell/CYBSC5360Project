@echo off
rem Drag a drive image onto this file, or double-click it and drop the image in.
cd /d "%~dp0"
where py >/dev/null 2>nul
if %errorlevel%==0 (py -3 start.py %*) else (python start.py %*)
