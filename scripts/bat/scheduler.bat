@echo off
REM scripts/bat/scheduler.bat
REM ---------------------------------------------------------------
REM Launches the unified scheduler (scripts/scheduler.py).
REM Registered as a user-level Windows Task Scheduler task on each
REM machine (trigger: at log on, restart on failure) - see
REM docs/SCHEDULER.md. Uses the repo .venv when present, else the
REM system python.
REM ---------------------------------------------------------------

cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\scheduler.py
) else (
    python scripts\scheduler.py
)
