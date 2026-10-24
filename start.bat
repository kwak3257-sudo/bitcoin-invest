@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist backend\.venv (
  echo 먼저 setup.bat을 실행하세요.
  pause
  exit /b 1
)
echo API 서버, 매매 엔진, 화면을 각각 새 창에서 켭니다. 창을 닫으면 해당 프로그램이 멈춥니다.
start "API 서버" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "매매 엔진" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m app.engine"
start "화면" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 6 > nul
start http://localhost:5173
