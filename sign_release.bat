@echo off
setlocal
cd /d "%~dp0"

set EXE_PATH=%~1
if "%EXE_PATH%"=="" set EXE_PATH=dist\WoW_Nemesis_Launcher_v1.8.1.exe

for %%F in ("%EXE_PATH%") do (
  set EXE_DIR=%%~dpF
  set EXE_NAME=%%~nF
)
set RELEASE_ZIP=%EXE_DIR%%EXE_NAME%_signed.zip

if not exist "%EXE_PATH%" (
  echo EXE neexistuje:
  echo %EXE_PATH%
  echo.
  echo Pouzitie:
  echo sign_release.bat dist\WoW_Nemesis_Launcher_v1.8.1.exe
  exit /b 1
)

if "%SIGN_CERT_PFX%"=="" (
  echo Chyba SIGN_CERT_PFX.
  echo Nastav cestu k PFX certifikatu, napriklad:
  echo set SIGN_CERT_PFX=C:\certifikaty\code-signing.pfx
  exit /b 1
)

if "%SIGN_CERT_PASSWORD%"=="" (
  echo Chyba SIGN_CERT_PASSWORD.
  echo Nastav heslo k PFX certifikatu, napriklad:
  echo set SIGN_CERT_PASSWORD=tajne-heslo
  exit /b 1
)

where signtool >nul 2>nul
if errorlevel 1 (
  echo Nenasiel som signtool.exe v PATH.
  echo Nainstaluj Windows SDK a otvor "Developer Command Prompt",
  echo alebo pridaj priecinok s signtool.exe do PATH.
  exit /b 1
)

echo Podpisujem:
echo %EXE_PATH%
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "%SIGN_CERT_PFX%" /p "%SIGN_CERT_PASSWORD%" "%EXE_PATH%"
if errorlevel 1 exit /b 1

signtool verify /pa /v "%EXE_PATH%"
if errorlevel 1 exit /b 1

if exist "%RELEASE_ZIP%" del "%RELEASE_ZIP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%EXE_PATH%' -DestinationPath '%RELEASE_ZIP%' -Force"
if errorlevel 1 exit /b 1

echo.
echo Podpisany release je pripraveny:
echo %RELEASE_ZIP%
endlocal
