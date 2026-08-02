@echo off
echo 🔄 Restarting ChartPulse AI Application...

echo 🛑 Terminating existing Dashboard & Bot processes...
wmic process where "commandline like '%%streamlit%%' or commandline like '%%dashboard.py%%' or commandline like '%%backend_bot.py%%'" call terminate >nul 2>&1

timeout /t 1 /nobreak >nul

echo 📊 Starting Dashboard UI...
start powershell -NoExit -Command "Set-Location '%~dp0'; streamlit run dashboard.py"

timeout /t 2 /nobreak >nul

echo 🚀 Starting Backend Trading Bot...
cd /d "%~dp0"
python backend_bot.py
