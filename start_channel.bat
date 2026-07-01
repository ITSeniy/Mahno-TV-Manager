@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ================================================
echo   Mahno TV Manager - запуск канала
echo ================================================
echo.
echo Перед запуском проверь:
echo   1. OBS Studio уже открыт
echo   2. В сцене ON_AIR подставлен реальный контент (программный вывод виден)
echo.
echo Это окно держит канал живым - не закрывай его.
echo Чтобы остановить канал, закрой окно или нажми Ctrl+C.
echo.

".venv\Scripts\python.exe" -m director.supervisor

echo.
echo Канал остановлен.
pause
