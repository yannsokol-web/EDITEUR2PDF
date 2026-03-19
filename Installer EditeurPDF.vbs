CreateObject("WScript.Shell").Run Chr(34) & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\installer.bat" & Chr(34), 0, False
