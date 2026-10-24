@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/4] 파이썬 가상환경 만들기
if not exist backend\.venv (
  python -m venv backend\.venv || goto :error
)
echo [2/4] 백엔드 라이브러리 설치
backend\.venv\Scripts\python -m pip install --upgrade pip > nul
backend\.venv\Scripts\python -m pip install -e "backend[dev]" || goto :error
echo [3/4] 화면 라이브러리 설치
pushd frontend
call npm install || (popd & goto :error)
popd
echo [4/4] 설정 파일 준비
if not exist .env copy .env.example .env > nul
echo.
echo 설치가 끝났습니다. .env 파일을 메모장으로 열어 빗썸 API 키를 넣은 뒤 start.bat을 실행하세요.
pause
exit /b 0
:error
echo.
echo 설치 중 오류가 났습니다. 위 메시지를 캡처해서 보내 주세요.
pause
exit /b 1
