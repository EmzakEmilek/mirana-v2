@echo off
rem Spusti Miranu cez supervisor (restart pri pade). Zatvorenie okna alebo Ctrl+C = koniec.
chcp 65001 >nul
title MIRANA
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"venv\Scripts\python.exe" run.py
pause
