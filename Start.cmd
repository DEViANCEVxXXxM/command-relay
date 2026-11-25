@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if errorlevel 1 (
  echo Python GUI launcher not found on PATH. Open Start.pyw or run tools\Start-Debug.cmd.
  pause
  exit /b 1
)
start "" pythonw.exe "%~dp0Start.pyw"
if errorlevel 1 (
  echo Could not start Command Relay. Run tools\Start-Debug.cmd.
  pause
  exit /b 1
)
