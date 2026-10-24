@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/4] 파이썬 가상환경 만들기
rem 너무 새 버전(3.14 이상)은 라이브러리 설치 파일이 아직 없어 3.13(없으면 3.12)을 쓴다
set "PY="
py -3.13 --version > nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 --version > nul 2>&1 && set "PY=py -3.12"
if not defined PY (
  echo 파이썬 3.13을 설치합니다.
  py install 3.13 || goto :error
  set "PY=py -3.13"
)
rem 예전에 다른 버전으로 만든 가상환경이면 지우고 다시 만든다
if exist backend\.venv (
  backend\.venv\Scripts\python -c "import sys; sys.exit(sys.version_info[:2] not in [(3, 12), (3, 13)])" || rmdir /s /q backend\.venv
)
if not exist backend\.venv (
  %PY% -m venv backend\.venv || goto :error
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
