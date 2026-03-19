@echo off
chcp 65001 >nul 2>&1
title Compilation EditeurPDF
echo ============================================
echo    Compilation de EditeurPDF
echo ============================================
echo.

:: Vérifier que Python est installé
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou n'est pas dans le PATH.
    echo Installez Python 3.10+ depuis https://www.python.org
    pause
    exit /b 1
)

:: Installer les dépendances
echo [1/3] Installation des dependances...
pip install PySide6 PyMuPDF pyinstaller --quiet
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances.
    pause
    exit /b 1
)
echo       OK
echo.

:: Nettoyer les anciens builds
echo [2/3] Nettoyage des anciens builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo       OK
echo.

:: Compiler
echo [3/3] Compilation en cours (cela peut prendre quelques minutes)...
pyinstaller EditeurPDF.spec --noconfirm
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue.
    pause
    exit /b 1
)
echo       OK
echo.

echo ============================================
echo    Compilation terminee !
echo.
echo    L'executable se trouve dans :
echo    dist\EditeurPDF.exe
echo.
echo    Vous pouvez copier ce fichier sur
echo    n'importe quel PC Windows.
echo ============================================
echo.
pause
