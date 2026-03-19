@echo off
chcp 65001 >nul 2>&1
title Installation EditeurPDF

set "SCRIPT_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\EditeurPDF"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SRC_DIR=%SCRIPT_DIR%dist\EditeurPDF"
set "PROGRESS_FILE=%TEMP%\editeurpdf_progress.txt"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non trouve dans le PATH.
    pause
    exit /b 1
)

echo 0;Preparation... > "%PROGRESS_FILE%"
start "" pythonw "%SCRIPT_DIR%installer_ui.py" "%PROGRESS_FILE%"

echo 5;Installation des dependances... > "%PROGRESS_FILE%"
python -m pip install PySide6 PyMuPDF pyinstaller --quiet
echo 15;Dependances installees > "%PROGRESS_FILE%"

echo 18;Nettoyage... > "%PROGRESS_FILE%"
if exist "%SCRIPT_DIR%build" rmdir /s /q "%SCRIPT_DIR%build" >nul 2>&1
if exist "%SCRIPT_DIR%dist" rmdir /s /q "%SCRIPT_DIR%dist" >nul 2>&1
echo 20;Nettoyage termine > "%PROGRESS_FILE%"

echo 25;Compilation en cours... > "%PROGRESS_FILE%"
python -m PyInstaller "%SCRIPT_DIR%EditeurPDF.spec" --noconfirm >nul 2>&1
if errorlevel 1 (
    echo -1;Erreur lors de la compilation > "%PROGRESS_FILE%"
    pause
    exit /b 1
)
echo 75;Compilation terminee > "%PROGRESS_FILE%"

echo 80;Copie des fichiers... > "%PROGRESS_FILE%"
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%" >nul 2>&1
xcopy "%SRC_DIR%" "%INSTALL_DIR%\" /e /i /q /y >nul
echo 90;Fichiers copies > "%PROGRESS_FILE%"

echo 93;Creation du raccourci... > "%PROGRESS_FILE%"
set "VBS=%TEMP%\create_shortcut.vbs"
> "%VBS%" (
    echo Set ws = CreateObject^("WScript.Shell"^)
    echo Set sc = ws.CreateShortcut^("%DESKTOP%\EditeurPDF.lnk"^)
    echo sc.TargetPath = "%INSTALL_DIR%\EditeurPDF.exe"
    echo sc.WorkingDirectory = "%INSTALL_DIR%"
    echo sc.Description = "Editeur PDF"
    echo sc.IconLocation = "%INSTALL_DIR%\_internal\logoediteurpdf.ico"
    echo sc.Save
)
cscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1

echo 100;Installation terminee ! > "%PROGRESS_FILE%"
