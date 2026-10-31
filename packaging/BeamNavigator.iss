; Beam Navigator for Windows: the installer around dist\BeamNavigator.exe (decision 45).
; Built by packaging/build_windows.py, which passes the version:
;     ISCC.exe /DAppVersion=1.2.0 packaging\BeamNavigator.iss
; Installs for the current user only (no administrator prompt), adds a Start menu entry,
; offers a desktop icon, and registers an uninstaller. The data folder (stations, nets,
; history) lives elsewhere and is never touched by installing, updating or uninstalling.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (packaging/build_windows.py does)
#endif

[Setup]
; Never change AppId: Windows uses it to find an installed copy to update or remove.
AppId={{1215C06F-B505-44B5-9992-1DB60B0C4D65}
AppName=Beam Navigator
AppVersion={#AppVersion}
AppVerName=Beam Navigator {#AppVersion}
AppPublisher=Terry Rossi, N2LQH
AppPublisherURL=https://github.com/n2lqh/beam-navigator
AppSupportURL=https://github.com/n2lqh/beam-navigator
AppCopyright=Copyright (C) 2026 Terry Rossi, N2LQH
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Beam Navigator
DefaultGroupName=Beam Navigator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=BeamNavigatorSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\BeamNavigator.exe
UninstallDisplayName=Beam Navigator
; Ask to close a running copy, so an update can replace the program file.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\BeamNavigator.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Beam Navigator"; Filename: "{app}\BeamNavigator.exe"
Name: "{autodesktop}\Beam Navigator"; Filename: "{app}\BeamNavigator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BeamNavigator.exe"; Description: "{cm:LaunchProgram,Beam Navigator}"; Flags: nowait postinstall skipifsilent
