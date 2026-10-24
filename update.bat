@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [1/4] 실행 중인 프로그램 끄기
call stop.bat
echo [2/4] 새 버전 받기
git pull || goto :error
echo [3/4] 라이브러리 확인
backend\.venv\Scripts\python -m pip install -q -e backend || goto :error
pushd frontend
call npm install --silent || (popd & goto :error)
popd
echo [4/4] 다시 켜기
call start.bat
exit /b 0
:error
echo.
echo 업데이트 중 오류가 났습니다. 이 창을 캡처해서 보내 주세요.
pause
exit /b 1
