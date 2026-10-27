@echo off
rem Website (next start) for the group over Tailscale. Listens only on this machine's
rem Tailscale IPv4 (100.x), not on LAN or public interfaces; the firewall rule from
rem setup_site.ps1 also only allows 100.64.0.0/10. Reads the API at 127.0.0.1:8000.
rem SITE_BIND overrides the address (e.g. set SITE_BIND=127.0.0.1 for a local check).
rem Builds once at start (picks up code after git pull), restarts after a crash.
rem Log: logs\site.log. Started at boot by the FootballSiteWeb task (setup_site.ps1).
cd /d "%~dp0"
if not exist logs mkdir logs
set "PATH=%ProgramFiles%\Tailscale;%PATH%"
set API_URL=http://127.0.0.1:8000
set NEXT_TELEMETRY_DISABLED=1
set PORT=3000
set WAITED=
echo ===== site start %date% %time% ===== >> logs\site.log

:addr
set ADDR=%SITE_BIND%
if not defined ADDR for /f %%i in ('tailscale ip -4 2^>nul') do set ADDR=%%i
if defined ADDR goto build
if not defined WAITED echo waiting for Tailscale IPv4, install and log in to Tailscale >> logs\site.log
set WAITED=1
ping -n 31 127.0.0.1 > nul
goto addr

:build
echo bind %ADDR%:%PORT% >> logs\site.log
cd web
call npm run build >> ..\logs\site.log 2>&1
if errorlevel 1 (
  echo ===== build failed %date% %time% ===== >> ..\logs\site.log
  exit /b 1
)

:serve
call npx --no-install next start --hostname %ADDR% --port %PORT% >> ..\logs\site.log 2>&1
echo ===== site exited code %errorlevel% %date% %time%, restart in 30 s ===== >> ..\logs\site.log
ping -n 31 127.0.0.1 > nul
goto serve
