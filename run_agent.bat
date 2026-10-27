@echo off
rem Chat service for the website (python -m agent.serve) on 127.0.0.1:8100. Only the
rem Next.js /api/chat route and login action reach it; no firewall rule, never listens
rem on other interfaces. Needs .venv-ml and AGENT_PROVIDER / AGENT_MODEL / key /
rem AGENT_SERVICE_TOKEN in .env (filled in by the user). Invite codes:
rem   .venv-ml\Scripts\python -m agent.access add NAME
rem Restarts after a crash (30 s pause). Log: logs\agent.log. Not registered as a boot
rem task by setup_site.ps1; start it by hand or add a task.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
:serve
echo ===== agent start %date% %time% ===== >> logs\agent.log
.venv-ml\Scripts\python -u -m agent.serve --port 8100 >> logs\agent.log 2>&1
echo ===== agent exited code %errorlevel% %date% %time%, restart in 30 s ===== >> logs\agent.log
ping -n 31 127.0.0.1 > nul
goto serve
