@echo off
rem FM26 Analyst setup: checks for Python, installs what the app needs into .venv, and adds shortcuts.
rem   install.bat --no-shortcuts   installs without adding shortcuts (and doesn't offer to start)
rem Safe to run again (e.g. after updating to a new version): your data in the data\ folder is kept.
setlocal
cd /d "%~dp0"
title FM26 Analyst setup
echo.
echo  FM26 Analyst setup
echo  ------------------
echo.

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo  Python 3.10 or newer wasn't found.
  echo.
  echo  Install it, then run install.bat again:
  echo    - from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^), or
  echo    - in a terminal:  winget install Python.Python.3.12
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% -c "import platform; print(platform.python_version())"') do echo  Using Python %%v

if not exist ".venv\Scripts\python.exe" (
  echo  Creating the app's Python environment ^(.venv^)...
  %PY% -m venv .venv || goto :fail
)
echo  Installing packages ^(this takes a minute the first time^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

if /i "%~1"=="--no-shortcuts" (
  echo.
  echo  Done. Start the app with .venv\Scripts\pythonw.exe launch.py
  exit /b 0
)
echo  Adding "FM26 Analyst" shortcuts to the Desktop and Start menu...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcut.ps1" >nul || goto :fail

echo.
echo  Done. Open FM26 Analyst from the Desktop or Start menu.
echo  On first start, load your save in FM26 and choose your club on the Overview page.
echo.
choice /c YN /m " Start FM26 Analyst now"
if errorlevel 2 exit /b 0
start "" ".venv\Scripts\pythonw.exe" "%~dp0launch.py"
exit /b 0

:fail
echo.
echo  Setup didn't finish - see the message above. Fix it and run install.bat again.
pause
exit /b 1
