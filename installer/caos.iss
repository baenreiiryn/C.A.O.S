#define MyAppName "C.A.O.S Trade Company"
#define MyAppVersion "0.8.3"
#define MyAppPublisher "C.A.O.S"
#define MyAppExeName "CAOS-Trade-Company.exe"

[Setup]
AppId={{B3A457B2-2A55-4D8B-9D53-9F3C6F9D1A71}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\CAOS
DefaultGroupName=C.A.O.S
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\installer-output
OutputBaseFilename=CAOS-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "autostart"; Description: "Start C.A.O.S Trade Company when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\CAOS-Trade-Company.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\caos.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\ollama-runtime\*"; DestDir: "{app}\ollama"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "THIRD_PARTY_OLLAMA_LICENSE.txt"; DestDir: "{app}\ollama"; DestName: "LICENSE-ollama.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\C.A.O.S Trade Company"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\C.A.O.S CLI"; Filename: "{cmd}"; Parameters: "/K cd /d ""{app}"""; WorkingDir: "{app}"
Name: "{autodesktop}\C.A.O.S Trade Company"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\C.A.O.S Trade Company"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch C.A.O.S Trade Company"; Flags: nowait postinstall skipifsilent
