@echo off
setlocal
cd /d "%~dp0"

set APP_VERSION=1.12
set APP_NAME=WoW_Nemesis_Launcher_v%APP_VERSION%
set RELEASE_DIR=dist\%APP_NAME%
set RELEASE_ZIP=dist\%APP_NAME%_release.zip

python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --noconfirm --clean --onedir --noconsole --noupx --name "%APP_NAME%" --version-file "version_info.txt" --paths "vendor" --collect-data customtkinter --hidden-import pyautogui --hidden-import pyperclip --exclude-module mouseinfo --exclude-module pyscreeze --exclude-module pymsgbox --exclude-module pytweening --exclude-module numpy --exclude-module cv2 --exclude-module charset_normalizer --exclude-module requests --exclude-module urllib3 --exclude-module httpx --exclude-module httpcore --exclude-module certifi --exclude-module webbrowser --exclude-module urllib.request --exclude-module http.client --exclude-module http.server --exclude-module multiprocessing --exclude-module socket --exclude-module ssl --add-data "assets\nemesis_background_v2.png;assets" main.py
if errorlevel 1 exit /b 1

if exist "%RELEASE_DIR%\README.txt" del "%RELEASE_DIR%\README.txt"
(
  echo WoW Nemesis Launcher v%APP_VERSION%
  echo.
  echo Spustenie:
  echo - otvor "%APP_NAME%.exe"
  echo - pri prvom spusteni nastav cestu k WoW.exe
  echo.
  echo Bezpecnost:
  echo - hesla su ulozene lokalne cez Windows DPAPI
  echo - launcher neupravuje WoW klienta ani necita pamat hry
  echo - false-positive AV hlasenia mozu vzniknut pri Python/PyInstaller aplikaciach
) > "%RELEASE_DIR%\README.txt"

if exist "%RELEASE_ZIP%" del "%RELEASE_ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath '%RELEASE_ZIP%' -Force"
if errorlevel 1 exit /b 1

echo.
echo Hotovo:
echo %RELEASE_DIR%\%APP_NAME%.exe
echo %RELEASE_ZIP%
endlocal
