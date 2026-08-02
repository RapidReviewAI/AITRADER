# Self-Restarting Launcher for ChartPulse AI Backend Bot
# Kills any lingering Python background processes running backend_bot.py before starting

$ScriptPath = "$PSScriptRoot\backend_bot.py"

Write-Host "🔄 Restarting ChartPulse AI Backend Bot..." -ForegroundColor Cyan

# Terminate existing backend_bot processes if running
$RunningProcesses = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*backend_bot.py*" }
if ($RunningProcesses) {
    Write-Host "🛑 Terminating existing backend bot process(es)..." -ForegroundColor Yellow
    foreach ($proc in $RunningProcesses) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

Write-Host "🚀 Starting fresh instance of backend_bot.py..." -ForegroundColor Green
Set-Location $PSScriptRoot
python backend_bot.py
