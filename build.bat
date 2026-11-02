@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --onedir --noconsole --noupx --name WoW_Nemesis_Launcher_v1.12 --version-file "version_info.txt" --paths "vendor" --collect-data customtkinter --hidden-import pyautogui --hidden-import pyperclip --exclude-module mouseinfo --exclude-module pyscreeze --exclude-module pymsgbox --exclude-module pytweening --exclude-module numpy --exclude-module cv2 --exclude-module charset_normalizer --exclude-module requests --exclude-module urllib3 --exclude-module httpx --exclude-module httpcore --exclude-module certifi --exclude-module webbrowser --exclude-module urllib.request --exclude-module http.client --exclude-module http.server --exclude-module multiprocessing --exclude-module socket --exclude-module ssl --add-data "assets\nemesis_background_v2.png;assets" main.py
if errorlevel 1 exit /b 1
echo.
echo Hotovo: dist\WoW_Nemesis_Launcher_v1.12\WoW_Nemesis_Launcher_v1.12.exe
endlocal
