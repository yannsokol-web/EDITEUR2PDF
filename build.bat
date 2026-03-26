@echo off
title Build - Editeur PDF
echo.
echo  ==========================================
echo       BUILD - EDITEUR PDF
echo  ==========================================
echo.

echo [1/2] Compilation PyInstaller...
python -m PyInstaller --noconfirm EditeurPDF.spec
if errorlevel 1 (
    echo  ERREUR PyInstaller
    pause
    exit /b 1
)
echo       OK
echo.

echo [2/2] Creation de l installeur (Inno Setup)...
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
if errorlevel 1 (
    echo  ERREUR Inno Setup
    pause
    exit /b 1
)
echo       OK
echo.

echo  ==========================================
echo  Installeur cree dans :
echo  installer_output\InstallEditeurPDF.exe
echo  ==========================================
echo.
pause
