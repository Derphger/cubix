[Setup]
AppName=Cubix
AppVersion=1.0
DefaultDirName={autopf}\Cubix
DefaultGroupName=Cubix
OutputDir=installer
OutputBaseFilename=Cubix-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName=Cubix

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "dist\Cubix\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Cubix"; Filename: "{app}\Cubix.exe"
Name: "{autodesktop}\Cubix"; Filename: "{app}\Cubix.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Cubix.exe"; Description: "Launch Cubix"; Flags: nowait postinstall skipifsilent
