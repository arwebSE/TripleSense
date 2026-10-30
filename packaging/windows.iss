#ifndef BundleDir
  #error BundleDir must point to the PyInstaller application folder
#endif

[Setup]
AppId={{E0B8344E-9715-4E9F-B769-0E0C7B51D65A}
AppName=DSShine
AppVersion=0.2.0
AppPublisher=DSShine contributors
AppPublisherURL=https://github.com/arwebSE/DSShine
DefaultDirName={autopf}\DSShine
DefaultGroupName=DSShine
UninstallDisplayIcon={app}\DSShine.exe
PrivilegesRequired=admin
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=DSShine-Setup-0.2.0-Windows-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
LicenseFile={#ProjectRoot}\LICENSE
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
Name: sunshine; Description: "Let DSShine handle controllers (disable Sunshine controller forwarding)"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DSShine"; Filename: "{app}\DSShine.exe"
Name: "{autodesktop}\DSShine"; Filename: "{app}\DSShine.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\_internal\installers\USBip-0.9.8.1-x64.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; StatusMsg: "Installing the controller driver…"; Check: NeedsControllerDriver; Flags: waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Controller"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Discovery"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""DSShine - Controller"" dir=in action=allow program=""{app}\DSShine.exe"" protocol=TCP localport=3250-3251 profile=private remoteip=localsubnet"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""DSShine - Discovery"" dir=in action=allow program=""{app}\DSShine.exe"" protocol=UDP localport=5353 profile=private remoteip=localsubnet"; Flags: runhidden
Filename: "{app}\DSShine.exe"; Description: "Open DSShine"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Controller"""; Flags: runhidden; RunOnceId: RemoveControllerFirewallRule
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Discovery"""; Flags: runhidden; RunOnceId: RemoveDiscoveryFirewallRule

[Code]
function NeedsControllerDriver: Boolean;
begin
  Result := not FileExists(ExpandConstant('{pf64}\USBip\usbip.exe'));
end;

function ControllerValue(const FileName: String): String;
var Lines: TArrayOfString; I, P: Integer; Line: String;
begin
  Result := '__missing__';
  if not LoadStringsFromFile(FileName, Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    Line := Trim(Lines[I]);
    P := Pos('=', Line);
    if (P > 0) and (Lowercase(Trim(Copy(Line, 1, P-1))) = 'controller') then
      Result := Trim(Copy(Line, P+1, Length(Line)));
  end;
end;

procedure SetControllerValue(const FileName, Value: String);
var Lines, Output: TArrayOfString; I, N, P: Integer; Line: String; Found: Boolean;
begin
  if not LoadStringsFromFile(FileName, Lines) then Exit;
  N := 0; Found := False;
  SetArrayLength(Output, GetArrayLength(Lines) + 1);
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    Line := Trim(Lines[I]); P := Pos('=', Line);
    if (P > 0) and (Lowercase(Trim(Copy(Line, 1, P-1))) = 'controller') then begin
      if not Found and (Value <> '__missing__') then begin
        Output[N] := 'controller = ' + Value; N := N + 1;
      end;
      Found := True;
    end else begin Output[N] := Lines[I]; N := N + 1; end;
  end;
  if not Found and (Value <> '__missing__') then begin
    Output[N] := 'controller = ' + Value; N := N + 1;
  end;
  SetArrayLength(Output, N);
  if not SaveStringsToUTF8FileWithoutBOM(FileName, Output, False) then
    RaiseException('Could not update Sunshine controller forwarding.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Config, State, Previous, Backup: String;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('sunshine') then begin
    Config := ExpandConstant('{pf64}\Sunshine\config\sunshine.conf');
    State := ExpandConstant('{app}\sunshine-setting.ini');
    if FileExists(Config) then begin
      Previous := ControllerValue(Config);
      if not FileExists(State) then begin
        SetIniString('Sunshine', 'Previous', Previous, State);
        SetIniString('Sunshine', 'Config', Config, State);
      end;
      Backup := Config + '.dsshine-backup-' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':');
      if not FileCopy(Config, Backup, True) then RaiseException('Could not back up Sunshine configuration.');
      SetControllerValue(Config, 'disabled');
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Config, State, Previous, LoginCommand: String;
begin
  if CurUninstallStep = usUninstall then begin
    State := ExpandConstant('{app}\sunshine-setting.ini');
    Config := GetIniString('Sunshine', 'Config', '', State);
    Previous := GetIniString('Sunshine', 'Previous', '__missing__', State);
    if FileExists(Config) and (ControllerValue(Config) = 'disabled') then
      SetControllerValue(Config, Previous);
    DeleteFile(State);
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'DSShine', LoginCommand) then begin
      if Pos(Lowercase(ExpandConstant('{app}\DSShine.exe')), Lowercase(LoginCommand)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DSShine');
    end;
  end;
end;
