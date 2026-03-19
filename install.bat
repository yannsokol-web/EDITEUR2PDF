@echo off
chcp 65001 >nul 2>&1
title Installation EditeurPDF

echo ============================================
echo    Installation de EditeurPDF
echo ============================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\EditeurPDF"
set "EXE_PATH=%INSTALL_DIR%\EditeurPDF.exe"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SRC_DIR=%~dp0dist\EditeurPDF"

if not exist "%SRC_DIR%\EditeurPDF.exe" (
    echo [ERREUR] EditeurPDF.exe non trouve.
    echo Lancez d'abord build.bat pour compiler.
    pause
    exit /b 1
)

echo [1/2] Copie des fichiers...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%" >nul 2>&1
xcopy "%SRC_DIR%" "%INSTALL_DIR%\" /e /i /q /y >nul
echo       OK
echo.

echo [2/2] Creation du raccourci bureau...
set "VBS=%TEMP%\create_shortcut.vbs"
(
    echo Set ws = CreateObject("WScript.Shell"^)
    echo Set sc = ws.CreateShortcut("%DESKTOP%\EditeurPDF.lnk"^)
    echo sc.TargetPath = "%EXE_PATH%"
    echo sc.WorkingDirectory = "%INSTALL_DIR%"
    echo sc.Description = "Editeur PDF"
    echo If CreateObject("Scripting.FileSystemObject"^).FileExists("%INSTALL_DIR%\Logo.ico"^) Then
    echo     sc.IconLocation = "%INSTALL_DIR%\Logo.ico"
    echo End If
    echo sc.Save
) > "%VBS%"
cscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1
echo       OK
echo.

echo ============================================
echo    Installation terminee !
echo    Un raccourci "EditeurPDF" a ete cree
echo    sur votre bureau.
echo ============================================
echo.
pause
