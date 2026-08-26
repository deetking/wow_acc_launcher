@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name WoW_Nemesis_Launcher_v1.5.0 --paths "vendor" --collect-data customtkinter --hidden-import pyautogui --add-data "assets\nemesis_background_v2.png;assets" --add-data "WowOpenBox-4.8.3;WowOpenBox-4.8.3" main.py
if errorlevel 1 exit /b 1
echo.
echo Hotovo: dist\WoW_Nemesis_Launcher_v1.5.0.exe
endlocal
