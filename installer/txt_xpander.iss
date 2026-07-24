; Inno Setup script for Txt Xpander — per-user install, no admin required.
;
; Build: run build_release.bat first (produces dist\Txt Xpander), then
; build_installer.bat (compiles this script into installer\).
;
; User data lives in %USERPROFILE%\.txt_xpander and is intentionally NOT removed
; on uninstall — the installer only manages the program files under {app}.

#define MyAppName "Txt Xpander"
#define MyAppVersion "3.3.0"
#define MyAppChannel "beta"
#define MyAppPublisher "Project Contributors"
#define MyAppExeName "Txt Xpander.exe"
#define MyAppIcon "..\source\txt_xpander.ico"
#define MyDistDir "..\dist\Txt Xpander"

[Setup]
; Stable AppId so future versions upgrade in place instead of installing twice.
AppId={{B2D4F6A8-1C3E-4A5B-8D9F-0E1A2B3C4D5E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} {#MyAppChannel}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no administrator/UAC prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=.
OutputBaseFilename=TxtXpanderSetup-{#MyAppVersion}-{#MyAppChannel}
Compression=lzma2
SolidCompression=yes
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion} {#MyAppChannel}
WizardStyle=modern
; Detect a running instance (matches the app's Local\TxtXpanderSingleton mutex)
; so install/uninstall can ask the user to close it first.
AppMutex=TxtXpanderSingleton

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "startup"; Description: "Iniciar o {#MyAppName} automaticamente com o Windows"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
