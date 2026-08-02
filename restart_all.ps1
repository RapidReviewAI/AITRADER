# Master Launcher for ChartPulse AI (Backend Bot + Streamlit Dashboard)
# Restarts both the dashboard and the backend bot cleanly in sequence

Set-Location $PSScriptRoot

Write-Host "🔄 Restarting ChartPulse AI Application..." -ForegroundColor Cyan

# 1. Terminate existing Streamlit / Dashboard processes
$StreamlitProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*streamlit*dashboard.py*" -or $_.CommandLine -like "*dashboard.py*" }
if ($StreamlitProcs) {
    Write-Host "🛑 Terminating existing Dashboard process..." -ForegroundColor Yellow
    foreach ($proc in $StreamlitProcs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# 2. Terminate existing Backend Bot processes
$BackendProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*backend_bot.py*" }
if ($BackendProcs) {
    Write-Host "🛑 Terminating existing Backend Bot process..." -ForegroundColor Yellow
    foreach ($proc in $BackendProcs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 1

# 3. Launch Dashboard UI in a separate standalone window
Write-Host "📊 Launching Dashboard UI..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit -Command `"Set-Location '$PSScriptRoot'; streamlit run dashboard.py`""

Start-Sleep -Seconds 2

# 4. Launch Backend Trading Bot in current terminal
Write-Host "🚀 Launching Backend Trading Bot..." -ForegroundColor Green
python backend_bot.py
