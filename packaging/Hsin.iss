#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif
#ifndef BuildRoot
  #define BuildRoot "..\dist\Hsin"
#endif
#ifndef ReleaseRoot
  #define ReleaseRoot "..\release"
#endif

[Setup]
AppId={{46A5EFC7-C7A1-43F6-8541-0D4F89323ED7}
AppName=Hsin Desktop Sprite
AppVersion={#AppVersion}
AppPublisher=Code Hsin
AppPublisherURL=https://github.com/jjlian197/Code-Hsin
DefaultDirName={localappdata}\Programs\Hsin
DefaultGroupName=Hsin
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseRoot}
OutputBaseFilename=Code-Hsin-v{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Hsin.exe
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
; 安装包使用已验证的同一构建目录，排除便携标记和任何用户数据。
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Excludes: "portable.txt,data\*,.runtime\*,config.local.yaml"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\portable.txt"

[Icons]
Name: "{autoprograms}\Hsin"; Filename: "{app}\Hsin.exe"
Name: "{autodesktop}\Hsin"; Filename: "{app}\Hsin.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Hsin.exe"; Description: "Launch Hsin"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then begin
    if MsgBox('Remove saved Hsin settings and character data? Select No to keep them for reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\Hsin'), True, True, True);
  end;
end;
