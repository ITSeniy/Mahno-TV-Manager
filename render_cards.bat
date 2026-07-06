@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ================================================
echo   Рендер карточек эфира (программа передач, погода)
echo ================================================
echo.
echo Отрисовывает ещё не готовые карточки на ближайшие сутки
echo через Playwright и ntsc-rs. Обычно это делает сам канал в
echo окно профилактики (05:00-10:00 МСК), но можно и вручную.
echo Сетка должна быть уже сгенерирована (update_library.bat).
echo.

".venv\Scripts\python.exe" -m director.render_cards

echo.
echo Готово.
pause
