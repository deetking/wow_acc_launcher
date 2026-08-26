@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name WoW_Nemesis_Launcher_v1.7.5 --paths "vendor" --collect-data customtkinter --hidden-import pyautogui --hidden-import pyperclip --add-data "assets\nemesis_background_v2.png;assets" main.py
if errorlevel 1 exit /b 1
echo.
echo Hotovo: dist\WoW_Nemesis_Launcher_v1.7.5.exe
endlocal
