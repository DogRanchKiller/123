@echo off
rem Read-only API (python -m server) on 127.0.0.1:8000 for the website. It has no auth,
rem so it never listens on other interfaces; only run_site.bat is reachable from outside.
rem Restarts after a crash (30 s pause). Log: logs\api.log.
rem Started at boot by the FootballSiteApi task (setup_site.ps1).
cd /d "%~dp0"
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
:serve
echo ===== api start %date% %time% ===== >> logs\api.log
python -u -m server --host 127.0.0.1 --port 8000 >> logs\api.log 2>&1
echo ===== api exited code %errorlevel% %date% %time%, restart in 30 s ===== >> logs\api.log
ping -n 31 127.0.0.1 > nul
goto serve
