@echo off
chcp 65001 > nul
cd /d "%~dp0"
if not exist backend\.venv (
  echo 먼저 setup.bat을 실행하세요.
  pause
  exit /b 1
)
echo 빗썸 API 키와 텔레그램을 연결합니다. 키와 토큰은 이 PC의 .env 파일에만 저장됩니다.
if not exist .env copy .env.example .env > nul
rem 엔진이 텔레그램 메시지를 먼저 가져가지 않게 끈 뒤 연결한다
call stop.bat > nul 2>&1
backend\.venv\Scripts\python -m app.connect
if errorlevel 1 (
  echo.
  echo 연결이 끝나지 않았습니다. 위 안내를 확인한 뒤 다시 실행하세요.
  echo 프로그램은 원래 설정으로 다시 켭니다.
  call start.bat
  pause
  exit /b 1
)
echo.
echo 새 설정으로 프로그램을 다시 켭니다.
call start.bat
pause
