@echo off
rem Compatibility entry point; the standard build includes a complete ZIP.
call "%~dp0build.bat"
exit /b %errorlevel%
