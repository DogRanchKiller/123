# Stop scrape_history.py once stage 1 (2526/2425/2324 of the 8 leagues) is done.
# The last stage-1 item is T1 2324; collect_history prints "T1 2324" on its summary line.
param([int]$ProcId = 32804)
$log = Join-Path $PSScriptRoot "log_scrape.txt"
while ($true) {
    if (-not (Get-Process -Id $ProcId -ErrorAction SilentlyContinue)) { break }
    $hit = Select-String -Path $log -Pattern "^T1 2324" -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($hit) {
        Stop-Process -Id $ProcId
        Add-Content -Path $log -Value "stage1 done, stopped by stop_after_stage1.ps1 at $(Get-Date -Format s)"
        break
    }
    Start-Sleep -Seconds 30
}
