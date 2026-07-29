@echo off
REM Запуск Last Asylum Bot (GUI Start/Stop). Кликни дважды по этому файлу.
REM Использует Python из локального venv проекта — устанавливать ничего не нужно.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [!] Не найден .venv\Scripts\python.exe
  echo     Сначала создай окружение:  python -m venv .venv  ^&^&  .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m src.app

if errorlevel 1 (
  echo.
  echo [!] Бот завершился с ошибкой. Смотри сообщения выше.
  pause
)
