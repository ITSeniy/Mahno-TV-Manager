@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ================================================
echo   Рендер фона карточек — «шёлковое полотно» REN-TV
echo ================================================
echo.
echo Отрисовывает бесшовную петлю анимированного полотна (WebGL)
echo в файл cloth_bg_path из config.json. Это разовый ассет —
echo перегенерировать нужно только при смене оформления, а не
echo каждый эфирный день. Поверх него ложатся карточки-заставки.
echo.

".venv\Scripts\python.exe" -m director.render_cloth_bg

echo.
echo Готово.
pause
