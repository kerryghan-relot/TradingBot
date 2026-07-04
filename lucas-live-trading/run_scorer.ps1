# Weekly scorer run — lucas-live-trading
# ========================================
# Re-ranks all candidate symbols and writes the top-X into
# config.json["symbols"].  The running bot hot-reloads the list within
# ~30 s (new symbols subscribed, removed ones liquidated) — no restart.
#
# Register as a weekly Windows scheduled task (run once in PowerShell):
#
#   Register-ScheduledTask -TaskName "TradingBot-Scorer" `
#     -Trigger (New-ScheduledTaskTrigger -Weekly `
#         -DaysOfWeek Sunday -At 18:00) `
#     -Action (New-ScheduledTaskAction -Execute "powershell.exe" `
#         -Argument ('-NoProfile -ExecutionPolicy Bypass -File ' +
#             '"C:\Users\Lucas\Documents\TradingBot\' +
#             'lucas-live-trading\run_scorer.ps1"'))
#
# To remove it:
#   Unregister-ScheduledTask -TaskName "TradingBot-Scorer"

$liveDir = $PSScriptRoot
$repo    = Split-Path -Parent $liveDir
$python  = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $liveDir "scorer_task.log"

Set-Location $liveDir

"=== Scorer run $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
    Out-File -Append -Encoding utf8 $logFile

& $python (Join-Path $liveDir "scorer.py") 2>&1 |
    Out-File -Append -Encoding utf8 $logFile

"=== Exit code: $LASTEXITCODE ===" |
    Out-File -Append -Encoding utf8 $logFile
