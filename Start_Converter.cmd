@echo off
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Please run Setup.cmd first, then open Start_Converter.cmd again.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0dxf_to_gcode_gui.py"
if errorlevel 1 pause
