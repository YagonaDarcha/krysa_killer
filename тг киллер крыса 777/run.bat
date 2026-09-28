@echo off
chcp 65001 >nul
cd /d "%~dp0"
:loop
python bot.py
echo Бот остановился, перезапуск через 5 секунд...
timeout /t 5 /nobreak >nul
goto loop
