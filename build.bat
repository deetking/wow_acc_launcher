@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name WoW_Nemesis_Launcher_v1.6.0 --paths "vendor" --collect-data customtkinter --hidden-import pyautogui --hidden-import pyperclip --add-data "assets\nemesis_background_v2.png;assets" --add-data "WOB2025;WOB2025" main.py
if errorlevel 1 exit /b 1
echo.
echo Hotovo: dist\WoW_Nemesis_Launcher_v1.6.0.exe
endlocal
