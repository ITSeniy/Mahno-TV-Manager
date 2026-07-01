@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ================================================
echo   Обновление медиатеки и сетки вещания
echo ================================================
echo.
echo Запусти это после того, как добавил новые файлы в папки
echo с сериалами/рекламой/заставками - пересканирует библиотеку
echo и досоздаст сетку на 7 дней вперёд.
echo.

".venv\Scripts\python.exe" -m director.scan_library
echo.
".venv\Scripts\python.exe" -m director.generate_schedule --days 7

echo.
echo Готово.
pause
