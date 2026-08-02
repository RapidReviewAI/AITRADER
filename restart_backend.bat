@echo off
echo 🔄 Restarting ChartPulse AI Backend Bot...

taskkill /FI "WINDOWTITLE eq ChartPulse AI Bot*" /F >nul 2>&1
wmic process where "commandline like '%%backend_bot.py%%'" call terminate >nul 2>&1

timeout /t 1 /nobreak >nul

echo 🚀 Starting fresh instance of backend_bot.py...
cd /d "%~dp0"
python backend_bot.py
