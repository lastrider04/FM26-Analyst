@echo off
rem Double-click to start the FM26 Analyst dashboard + Ctrl+Alt+S capture hotkey.
rem Keep this window open while you play; close it to stop.
cd /d "%~dp0"
title FM26 Analyst
".venv\Scripts\python.exe" run.py
pause
