; Internal per-user installer. Personal data is preserved unless explicitly confirmed through the guarded cleanup helper.
#ifndef ProductDir
  #error ProductDir must name a verified portable candidate
#endif
#ifndef OutputDir
  #error OutputDir must name a new output directory
#endif
#ifndef BuildVersion
  #define BuildVersion "2026.09.20-l"
#endif

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
Name: "{group}\Sumika"; Filename: "{app}\Sumika.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Sumika {#BuildVersion}"; Filename: "{app}\Sumika.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
var
  DeletePersonalData: Boolean;
  UninstallDataDirectory: String;
  InstallDataDirectory: String;
  InstallDataResolved: Boolean;

function DefaultInstallDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\Apps\Sumika\{#BuildVersion}'
  else
    Result := ExpandConstant('{localappdata}\Programs\Sumika\{#BuildVersion}');
end;

function ResolveInstallDataDirectory: Boolean;
var
  ScriptFile, OutputFile: String;
  ExitCode: Integer;
  Lines: TArrayOfString;
begin
  Result := False;
  ScriptFile := ExpandConstant('{tmp}\resolve-sumika-location.ps1');
  OutputFile := ExpandConstant('{tmp}\install-data-location.txt');
  if not SaveStringToFile(ScriptFile,
    'param([string]$OutputPath)' + #13#10 +
    '$ErrorActionPreference = ''Stop''' + #13#10 +
    '$directory = Join-Path $env:LOCALAPPDATA ''Sumika''' + #13#10 +
    '$locator = Join-Path $env:LOCALAPPDATA ''Sumika-location.json''' + #13#10 +
    'if (Test-Path -LiteralPath $locator) {' + #13#10 +
    '  $data = Get-Content -LiteralPath $locator -Raw -Encoding UTF8 | ConvertFrom-Json' + #13#10 +
    '  if ($data.directory -isnot [string] -or $data.directory -notmatch ''^[A-Za-z]:\\'' -or $data.directory -match ''[\x00-\x1f"*?]'') { throw ''Invalid personal data locator'' }' + #13#10 +
    '  $directory = [IO.Path]::GetFullPath($data.directory)' + #13#10 +
    '}' + #13#10 +
    '[IO.File]::WriteAllText($OutputPath, $directory, [Text.UTF8Encoding]::new($true))' + #13#10,
    False) then Exit;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ScriptFile + '" -OutputPath "' + OutputFile + '"',
    ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then Exit;
  if ExitCode <> 0 then Exit;
  if not LoadStringsFromFile(OutputFile, Lines) then Exit;
  if GetArrayLength(Lines) <> 1 then Exit;
  InstallDataDirectory := Trim(Lines[0]);
  Result := (Length(InstallDataDirectory) > 3) and (Copy(InstallDataDirectory, 2, 2) = ':\');
end;

procedure InitializeWizard;
begin
  InstallDataResolved := ResolveInstallDataDirectory;
  WizardForm.FinishedLabel.Caption :=
    '安装完成。请从开始菜单或桌面快捷方式启动 Sumika。原有个人数据会自动沿用，可在设置中的“数据与存储”查看或迁移。' + #13#10 + #13#10 +
    '安装器不会自动启动或停止旧服务。若 8765 端口被旧版占用，请先从旧版正常退出。';
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
  if not InstallDataResolved then begin
    Result := '无法确认现有个人数据位置。请检查 Sumika-location.json，安装未继续。';
    Exit;
  end;
  DataDir := InstallDataDirectory;
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
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    if DirExists(WizardDirValue) or FileExists(WizardDirValue) then begin
      MsgBox('请选择尚不存在的新安装目录；旧安装会保留，不原地覆盖。', mbError, MB_OK);
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

function ResolveUninstallDataDirectory(var Directory: String): Boolean;
var
  OutputFile, Python, Helper: String;
  ExitCode: Integer;
  Lines: TArrayOfString;
begin
  Result := False;
  Python := ExpandConstant('{app}\runtime\python\python.exe');
  Helper := ExpandConstant('{app}\tools\manage_personal_data.py');
  if not FileExists(Python) or not FileExists(Helper) then Exit;
  OutputFile := ExpandConstant('{tmp}\sumika-personal-data-path.txt');
  if not Exec(Python, '-B "' + Helper + '" resolve --output "' + OutputFile + '"',
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then Exit;
  if ExitCode <> 0 then Exit;
  if not LoadStringsFromFile(OutputFile, Lines) then Exit;
  if GetArrayLength(Lines) <> 1 then Exit;
  Directory := Trim(Lines[0]);
  Result := (Length(Directory) > 3) and (Copy(Directory, 2, 2) = ':\');
end;

function InitializeUninstall: Boolean;
var
  Dialog: TSetupForm;
  KeepLabel: TNewStaticText;
  DeleteCheck: TNewCheckBox;
  ContinueButton, CancelButton: TNewButton;
  CanDelete: Boolean;
begin
  Result := True;
  DeletePersonalData := False;
  if UninstallSilent then Exit;
  CanDelete := ResolveUninstallDataDirectory(UninstallDataDirectory);
  Dialog := CreateCustomForm(ScaleX(510), ScaleY(225), False, False);
  try
    Dialog.Caption := '卸载 Sumika';
    Dialog.ClientWidth := ScaleX(510);
    Dialog.ClientHeight := ScaleY(225);
    KeepLabel := TNewStaticText.Create(Dialog);
    KeepLabel.Parent := Dialog;
    KeepLabel.SetBounds(ScaleX(20), ScaleY(20), ScaleX(470), ScaleY(100));
    KeepLabel.AutoSize := False;
    KeepLabel.WordWrap := True;
    if CanDelete then
      KeepLabel.Caption := '默认保留角色、聊天、记忆和连接配置，以便重新安装后继续使用。' + #13#10 + #13#10 +
        '个人数据目录：' + UninstallDataDirectory
    else
      KeepLabel.Caption := '默认保留个人数据。无法安全确认当前数据目录，因此本次只卸载程序。';
    DeleteCheck := TNewCheckBox.Create(Dialog);
    DeleteCheck.Parent := Dialog;
    DeleteCheck.SetBounds(ScaleX(20), ScaleY(130), ScaleX(470), ScaleY(24));
    DeleteCheck.Caption := '同时删除个人数据（不可恢复）';
    DeleteCheck.Checked := False;
    DeleteCheck.Enabled := CanDelete;
    ContinueButton := TNewButton.Create(Dialog);
    ContinueButton.Parent := Dialog;
    ContinueButton.SetBounds(ScaleX(300), ScaleY(180), ScaleX(90), ScaleY(28));
    ContinueButton.Caption := '继续卸载';
    ContinueButton.ModalResult := mrOk;
    ContinueButton.Default := True;
    CancelButton := TNewButton.Create(Dialog);
    CancelButton.Parent := Dialog;
    CancelButton.SetBounds(ScaleX(400), ScaleY(180), ScaleX(90), ScaleY(28));
    CancelButton.Caption := '取消';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    Result := Dialog.ShowModal = mrOk;
    if Result and DeleteCheck.Checked then begin
      Result := MsgBox('确认永久删除以下目录中的 Sumika 个人数据？' + #13#10 + #13#10 +
        UninstallDataDirectory + #13#10 + #13#10 +
        '包括角色副本、聊天、记忆、连接配置和工作台历史。外部模型库及原始角色卡文件不删除。此操作无法撤销。',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
      DeletePersonalData := Result;
    end;
  finally
    Dialog.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExitCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and DeletePersonalData and not UninstallSilent then begin
    if not Exec(ExpandConstant('{app}\runtime\python\python.exe'),
      '-B "' + ExpandConstant('{app}\tools\manage_personal_data.py') +
      '" cleanup --directory "' + UninstallDataDirectory + '" --confirmed',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      RaiseException('无法启动个人数据清理工具，卸载已中止。请保留程序并检查数据。');
    if ExitCode <> 0 then
      RaiseException('个人数据清理未成功，卸载已中止。请退出 Sumika 后重试，或选择保留个人数据。');
  end;
end;
