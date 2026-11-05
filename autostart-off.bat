@echo off
chcp 65001 > nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\coin-invest-autostart.bat" 2> nul
echo 자동 시작을 껐습니다.
pause
