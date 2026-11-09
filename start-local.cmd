@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create .venv and install facade/requirements.txt first. See facade/README.md.
  pause
  exit /b 1
)
set "HF_HOME=%~dp0.facade-data\model-cache"
echo NASH DVOR: http://127.0.0.1:8000/
echo Keep this window open. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn facade.app:app --host 127.0.0.1 --port 8000 --no-access-log
pause
