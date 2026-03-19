@echo off
chcp 65001 >nul 2>&1
title Compilation EditeurPDF

echo ============================================
echo    Compilation de EditeurPDF
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non trouve dans le PATH.
    pause
    exit /b 1
)

echo [1/3] Installation des dependances...
python -m pip install PySide6 PyMuPDF pyinstaller --quiet
echo       OK
echo.

echo [2/3] Nettoyage...
if exist build rmdir /s /q build >nul 2>&1
if exist dist rmdir /s /q dist >nul 2>&1
echo       OK
echo.

echo [3/3] Compilation en cours...
python -m PyInstaller EditeurPDF.spec --noconfirm
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)
echo       OK
echo.

echo ============================================
echo    Termine !
echo    Dossier : dist\EditeurPDF\
echo    Executable : dist\EditeurPDF\EditeurPDF.exe
echo.
echo    Lancez install.bat pour creer un raccourci
echo    bureau automatiquement.
echo ============================================
echo.
pause
