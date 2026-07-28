#define AppName "TTS Dataset Studio"
#ifndef AppVersion
  #define AppVersion "0.2.0-alpha.1"
#endif
#ifndef SourceDir
  #error SourceDir must be supplied with /DSourceDir=...
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied with /DReleaseDir=...
#endif

[Setup]
AppId={{5B82BF42-6C95-4F8A-B04C-4E3C66D22A91}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Yukikaze1945
AppPublisherURL=https://github.com/Yukikaze1945/TTS-Dataset-Studio
DefaultDirName={localappdata}\Programs\TTS Dataset Studio
DefaultGroupName=TTS Dataset Studio
OutputDir={#ReleaseDir}
OutputBaseFilename=TTS-Dataset-Studio-v{#AppVersion}-setup-x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TTS Dataset Studio.exe
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
Name: "contextmenu"; Description: "添加到音视频文件右键菜单"; GroupDescription: "Windows 集成："; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TTS Dataset Studio"; Filename: "{app}\TTS Dataset Studio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\TTS Dataset Studio"; Filename: "{app}\TTS Dataset Studio.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\Applications\TTS Dataset Studio.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "TTS Dataset Studio"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Applications\TTS Dataset Studio.exe"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\TTS Dataset Studio.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Applications\TTS Dataset Studio.exe\shell\open\command"; ValueType: string; ValueData: """{app}\TTS Dataset Studio.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\audio\shell\TTSDatasetStudio"; ValueType: string; ValueData: "使用 TTS Dataset Studio 打开"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\audio\shell\TTSDatasetStudio"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\TTS Dataset Studio.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\audio\shell\TTSDatasetStudio\command"; ValueType: string; ValueData: """{app}\TTS Dataset Studio.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\video\shell\TTSDatasetStudio"; ValueType: string; ValueData: "使用 TTS Dataset Studio 打开"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\video\shell\TTSDatasetStudio"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\TTS Dataset Studio.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\video\shell\TTSDatasetStudio\command"; ValueType: string; ValueData: """{app}\TTS Dataset Studio.exe"" ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\TTS Dataset Studio.exe"; Description: "启动 TTS Dataset Studio"; Flags: nowait postinstall skipifsilent
