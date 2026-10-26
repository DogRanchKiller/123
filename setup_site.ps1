# Register the website for the group over Tailscale. Run once in an elevated PowerShell
# (Run as administrator) from the repo root:
#   powershell -ExecutionPolicy Bypass -File .\setup_site.ps1           # install / update
#   powershell -ExecutionPolicy Bypass -File .\setup_site.ps1 -Remove   # undo everything
# What it does:
#   - Tasks FootballSiteApi (run_api.bat) and FootballSiteWeb (run_site.bat): start at boot
#     as the current user (S4U: no stored password, no console window), no time limit.
#   - Firewall rule FootballSite-Tailscale: inbound TCP 3000 only from 100.64.0.0/10
#     (Tailscale addresses). The API port 8000 listens on 127.0.0.1 only and gets no rule.
# Tailscale itself (install, login, sharing this machine) is done by the user.
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$tasks = @{ "FootballSiteApi" = "run_api.bat"; "FootballSiteWeb" = "run_site.bat" }
$rule = "FootballSite-Tailscale"

function Stop-Site {
    foreach ($name in $tasks.Keys) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $name
        }
    }
    # cmd children (python / node) survive the task stop: end the python / node still holding the ports
    foreach ($port in 3000, 8000) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } |
            Where-Object { $_.ProcessName -in "python", "node" } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

Stop-Site
if ($Remove) {
    foreach ($name in $tasks.Keys) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
    Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
    Write-Host "Removed tasks and firewall rule."
    exit 0
}

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
foreach ($name in $tasks.Keys) {
    $action = New-ScheduledTaskAction -Execute (Join-Path $root $tasks[$name]) -WorkingDirectory $root
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null
}

Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort 3000 -RemoteAddress 100.64.0.0/10 -Profile Any | Out-Null

Start-ScheduledTask -TaskName "FootballSiteApi"
Start-ScheduledTask -TaskName "FootballSiteWeb"
Write-Host "Registered FootballSiteApi / FootballSiteWeb (user $user) and firewall rule $rule."
Write-Host "Logs: logs\api.log, logs\site.log. Site: http://<this machine's Tailscale IP>:3000"
