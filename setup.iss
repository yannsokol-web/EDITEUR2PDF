[Setup]
AppName=Editeur PDF
AppVersion=1.4
AppVerName=Editeur PDF 1.4
AppPublisher=Yann Sokol
AppCopyright=Copyright (c) 2026 Yann Sokol. Tous droits réservés.
DefaultDirName={localappdata}\EditeurPDF
DefaultGroupName=Editeur PDF
OutputDir=installer_output
OutputBaseFilename=InstallEditeurPDF
SetupIconFile=logoediteurpdf.ico
UninstallDisplayIcon={app}\logoediteurpdf.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "dist\EditeurPDF\EditeurPDF.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\EditeurPDF\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "logoediteurpdf.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.ini"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Editeur PDF"; Filename: "{app}\EditeurPDF.exe"; IconFilename: "{app}\logoediteurpdf.ico"; WorkingDir: "{app}"
Name: "{group}\Editeur PDF"; Filename: "{app}\EditeurPDF.exe"; IconFilename: "{app}\logoediteurpdf.ico"
Name: "{group}\Desinstaller Editeur PDF"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\EditeurPDF.exe"; Description: "Lancer Editeur PDF"; Flags: nowait postinstall skipifsilent
