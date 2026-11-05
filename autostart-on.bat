@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 윈도우에 로그인하면 start.bat이 자동으로 실행되게 시작프로그램 폴더에 등록한다 (관리자 권한 필요 없음)
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
  echo @echo off
  echo rem coin-invest autostart. Run autostart-off.bat to remove.
  echo timeout /t 30 /nobreak ^> nul
  echo call "%~dp0start.bat"
) > "%STARTUP%\coin-invest-autostart.bat"
rem 전원이 연결돼 있을 때 PC가 절전 모드로 들어가지 않게 한다 (화면 끄기는 그대로)
powercfg /change standby-timeout-ac 0 > nul 2>&1
echo PC를 켜고 로그인하면 30초 뒤 프로그램이 자동으로 켜집니다.
echo 전원이 연결돼 있을 때는 PC가 절전 모드로 들어가지 않게 바꿨습니다. 화면은 꺼져도 괜찮아요.
echo 끄려면 autostart-off.bat을 더블클릭하세요.
pause
