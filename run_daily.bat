@echo off
rem Daily job: update data, score finished matches, archive predictions, report,
rem then scrape multi-bookmaker odds (book_odds) for the next 30 hours,
rem then refresh FotMob lineups / player xG for finished matches (fotmob.db).
rem Called by Windows Task Scheduler (task FootballPredictDaily); can also be run by hand.
cd /d "%~dp0"
set PYTHONPATH=.
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
echo ===== start %date% %time% ===== >> logs\daily.log
python -u -m football_prediction.live >> logs\daily.log 2>&1
python -u -m football_prediction.data.oddsportal --hours 30 >> logs\daily.log 2>&1
python -u -m football_prediction.data.fotmob >> logs\daily.log 2>&1
echo ===== done %date% %time% ===== >> logs\daily.log
