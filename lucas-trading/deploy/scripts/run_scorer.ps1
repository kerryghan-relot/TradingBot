# Weekly scorer run — lucas-trading
# ==================================
# Re-ranks all candidate symbols and writes the top-X into
# config/config.json["symbols"].  The running bot hot-reloads the list
# within ~30 s (new symbols subscribed, removed ones liquidated) — no
# restart.
#
# Register as a weekly Windows scheduled task (run once in PowerShell):
#
#   Register-ScheduledTask -TaskName "TradingBot-Scorer" `
#     -Trigger (New-ScheduledTaskTrigger -Weekly `
#         -DaysOfWeek Sunday -At 18:00) `
#     -Action (New-ScheduledTaskAction -Execute "powershell.exe" `
#         -Argument ('-NoProfile -ExecutionPolicy Bypass -File ' +
#             '"C:\Users\Lucas\Documents\TradingBot\lucas-trading\' +
#             'deploy\scripts\run_scorer.ps1"'))
#
# To remove it:
#   Unregister-ScheduledTask -TaskName "TradingBot-Scorer"

# Script lives in lucas-trading/deploy/scripts/ — two levels up is
# lucas-trading/, one more is the repo root (where .venv lives).
$tradingDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repo       = Split-Path -Parent $tradingDir
$python     = Join-Path $repo ".venv\Scripts\python.exe"
$logFile    = Join-Path $tradingDir "scorer_task.log"

Set-Location $tradingDir

"=== Scorer run $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
    Out-File -Append -Encoding utf8 $logFile

& $python -m live.scorer 2>&1 |
    Out-File -Append -Encoding utf8 $logFile

"=== Exit code: $LASTEXITCODE ===" |
    Out-File -Append -Encoding utf8 $logFile
