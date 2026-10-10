@echo off
rem Builds dist\JobHuntr.exe (single file, no console window).
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller --quiet || goto :error
rem numpy gets pulled in by optional imports but JobHuntr never uses it (saves ~10 MB)
python -m PyInstaller --noconfirm --onefile --windowed --name JobHuntr --icon jobhuntr\static\icon.ico ^
  --exclude-module numpy ^
  --add-data "jobhuntr\static;jobhuntr\static" ^
  --add-data "jobhuntr\default_sources.json;jobhuntr" ^
  run_jobhuntr.py || goto :error
echo.
echo Built dist\JobHuntr.exe
exit /b 0
:error
echo Build failed.
exit /b 1
