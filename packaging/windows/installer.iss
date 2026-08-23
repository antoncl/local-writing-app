; Inno Setup script for the Local Writing App (ADR-0072 S5).
; Built in CI on the windows runner:
;   iscc packaging\windows\installer.iss /DMyAppVersion=<version>
; Per-user install (no admin). Paths here are relative to this .iss file.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Local Writing App"
#define MyAppExe "local-writing-app.exe"
#define IconSrc "..\icons\icon.ico"

[Setup]
; A stable AppId so upgrades/uninstall track the same product. Do not change it.
AppId={{B8E7B0A2-3C4D-4E5F-9A1B-2C3D4E5F6A7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={localappdata}\Programs\LocalWritingApp
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist-installer
OutputBaseFilename=local-writing-app-windows-x64-setup
SetupIconFile={#IconSrc}
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; The frozen onedir, and the icon for the shortcut / Add-Remove-Programs entry.
Source: "..\..\dist\local-writing-app\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "{#IconSrc}"; DestDir: "{app}"; DestName: "icon.ico"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\icon.ico"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
