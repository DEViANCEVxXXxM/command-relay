@echo off
cd /d "%~dp0.."
python -B -m command_relay
if errorlevel 1 (
  echo Qt Workbench failed. If PySide6 is missing: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
