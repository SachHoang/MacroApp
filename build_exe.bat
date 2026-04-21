@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean macro_studio.spec
echo.
echo Build xong. Kiem tra file EXE tai dist\StudioMacro.exe
endlocal
