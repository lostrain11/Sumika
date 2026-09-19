; Internal per-user installer. Personal data is never part of Files/UninstallDelete.
#ifndef ProductDir
  #error ProductDir must name a verified portable candidate
#endif
#ifndef OutputDir
  #error OutputDir must name a new output directory
#endif
#define BuildVersion "2026.09.20-k"

[Setup]
AppId=Sumika.Internal.{#BuildVersion}
AppName=Sumika
AppVersion={#BuildVersion}
AppPublisher=Sumika
DefaultDirName={code:DefaultInstallDir}
DefaultGroupName=Sumika {#BuildVersion}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=no
DisableProgramGroupPage=yes
AllowNoIcons=yes
UsePreviousAppDir=no
UsePreviousTasks=no
UsePreviousLanguage=no
OutputDir={#OutputDir}
OutputBaseFilename=Sumika-Setup-{#BuildVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\Sumika.exe
SetupLogging=yes

[Languages]
Name: "zhcn"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式（Sumika {#BuildVersion}）"; Flags: unchecked

[Files]
Source: "{#ProductDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Sumika"; Filename: "{app}\Sumika.exe"; Parameters: "-DataDirectory ""{code:PersonalDataDir}"""; WorkingDir: "{app}"
Name: "{autodesktop}\Sumika {#BuildVersion}"; Filename: "{app}\Sumika.exe"; Parameters: "-DataDirectory ""{code:PersonalDataDir}"""; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  DataPage: TInputDirWizardPage;

function DefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\Apps\Sumika\{#BuildVersion}'
  else
    Result := ExpandConstant('{localappdata}\Programs\Sumika\{#BuildVersion}');
end;

function PersonalDataDir(Param: String): String;
begin
  Result := RemoveBackslashUnlessRoot(DataPage.Values[0]);
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectDir, '个人数据位置',
    '沿用原有角色、聊天、记忆和连接配置',
    '默认使用现有 Sumika 个人目录。安装过程不会复制、改写或删除该目录；卸载也会保留。模型仍从原路径读取，无需重新下载。选择新的空目录会作为全新用户启动。',
    False, '');
  DataPage.Add('个人数据目录：');
  DataPage.Values[0] := ExpandConstant('{param:DATADIR|{localappdata}\Sumika}');
  WizardForm.FinishedLabel.Caption :=
    '安装完成。请从开始菜单或桌面快捷方式启动 Sumika，以使用刚才选择的个人数据目录。' + #13#10 + #13#10 +
    '安装器不会自动启动或停止旧服务。若 8765 端口被旧版占用，请先从旧版正常退出。旧源码版的工作台历史可能需要单独迁移；角色卡和模型配置无需重复导入。';
end;

function IsNested(A, B: String): Boolean;
begin
  A := Lowercase(AddBackslash(ExpandFileName(A)));
  B := Lowercase(AddBackslash(ExpandFileName(B)));
  Result := Pos(B, A) = 1;
end;

function ValidateLocations: String;
var
  DataDir, AppDir: String;
begin
  Result := '';
  DataDir := PersonalDataDir('');
  AppDir := WizardDirValue;
  if (Length(DataDir) < 3) or (Copy(DataDir, 2, 2) <> ':\') or
     (Pos('"', DataDir) > 0) or (Pos('*', DataDir) > 0) or (Pos('?', DataDir) > 0) then
    Result := '请选择有效的本机绝对路径作为个人数据目录。'
  else if IsNested(DataDir, AppDir) or IsNested(AppDir, DataDir) then
    Result := '程序目录与个人数据目录必须分开，不能互相包含。'
  else if FileExists(DataDir) then
    Result := '个人数据路径是文件，请选择目录。'
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    if DirExists(WizardDirValue) or FileExists(WizardDirValue) then begin
      MsgBox('请选择尚不存在的新安装目录；旧安装会保留，不原地覆盖。', mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = DataPage.ID then begin
    Error := ValidateLocations;
    if Error <> '' then begin
      MsgBox(Error, mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := ValidateLocations;
  if (Result = '') and (DirExists(WizardDirValue) or FileExists(WizardDirValue)) then
    Result := '目标安装目录已存在，请选择新目录。未覆盖已有文件。';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + '个人数据（保留原位）：' + NewLine +
    Space + PersonalDataDir('') + NewLine + NewLine + MemoTasksInfo;
end;
