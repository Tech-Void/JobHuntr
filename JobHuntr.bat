@echo off
rem Starts JobHuntr from source. After building, you can use dist\JobHuntr.exe instead.
cd /d "%~dp0"
start "" pythonw run_jobhuntr.py %*
