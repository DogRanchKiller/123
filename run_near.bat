@echo off
rem Near-kickoff job: for matches kicking off within 1.5 hours, scrape multi-bookmaker
rem odds (OddsPortal) and lineups (FotMob HTML), then archive *_t1 predictions.
rem Meant for Windows Task Scheduler every 30-60 minutes; exits quickly when nothing is near.
cd /d "%~dp0"
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo ===== near %date% %time% ===== >> logs\near.log
python -u -m football_prediction.live --near >> logs\near.log 2>&1
