@echo off
chcp 65001 > nul
rem 이 폴더에서 켠 API 서버, 매매 엔진, 화면을 끈다 (다른 파이썬·노드 프로그램은 건드리지 않음)
powershell -NoProfile -Command "$d = '%~dp0'.TrimEnd('\'); Get-CimInstance Win32_Process | Where-Object { ($_.Name -in 'python.exe','node.exe') -and $_.CommandLine -and ($_.CommandLine -like '*app.engine*' -or $_.CommandLine -like '*uvicorn app.main*' -or ($_.CommandLine -like '*vite*' -and $_.CommandLine -like ('*' + $d + '*'))) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo 켜져 있던 프로그램을 껐습니다.
