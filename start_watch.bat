@echo off
setlocal
cd /d "%~dp0"

rem Use a project venv when present, otherwise the python on PATH.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined HUAWEI_SCALE_PYTHON set "PY=%HUAWEI_SCALE_PYTHON%"

if not exist "scale_config.json" (
  echo [!] scale_config.json not found.
  echo     Copy scale_config.example.json to scale_config.json and set your scale MAC.
  echo     Find the MAC with:  python scan.py --seconds 30 --all
  echo     Or set the HUAWEI_SCALE_MAC environment variable.
  echo.
  pause
  exit /b 1
)

"%PY%" watch.py %*
pause
