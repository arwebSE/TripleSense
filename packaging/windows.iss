#ifndef BundleDir
  #error BundleDir must point to the PyInstaller application folder
#endif

[Setup]
AppId={{E0B8344E-9715-4E9F-B769-0E0C7B51D65A}
AppName=TripleSense
AppVersion=0.5.0
AppPublisher=TripleSense contributors
AppPublisherURL=https://github.com/arwebSE/TripleSense
DefaultDirName={autopf}\TripleSense
DefaultGroupName=TripleSense
UsePreviousGroup=no
UninstallDisplayIcon={app}\TripleSense.exe
PrivilegesRequired=admin
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=TripleSense-Setup-0.5.0-Windows-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#ProjectRoot}\src\dualsensedriver\assets\dsshine.ico
LicenseFile={#ProjectRoot}\LICENSE
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TripleSense"; Filename: "{app}\TripleSense.exe"; IconFilename: "{app}\_internal\dualsensedriver\assets\dsshine.ico"; AppUserModelID: "me.dsshine.app"
Name: "{autodesktop}\TripleSense"; Filename: "{app}\TripleSense.exe"; IconFilename: "{app}\_internal\dualsensedriver\assets\dsshine.ico"; Tasks: desktopicon; AppUserModelID: "me.dsshine.app"

[InstallDelete]
Type: files; Name: "{app}\DSShine.exe"
Type: files; Name: "{group}\DSShine.lnk"
Type: files; Name: "{commonprograms}\DSShine\DSShine.lnk"
Type: files; Name: "{autodesktop}\DSShine.lnk"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Controller"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DSShine - Discovery"""; Flags: runhidden
Filename: "{app}\_internal\installers\USBip-0.9.8.1-x64.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; StatusMsg: "Installing the controller driver…"; Check: NeedsControllerDriver; Flags: waituntilterminated
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""TripleSense - Controller"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""TripleSense - Discovery"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""TripleSense - Controller"" dir=in action=allow program=""{app}\TripleSense.exe"" protocol=TCP localport=3250-3251 profile=private,public remoteip=localsubnet,100.64.0.0/10"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""TripleSense - Discovery"" dir=in action=allow program=""{app}\TripleSense.exe"" protocol=UDP localport=5353,3252 profile=private,public remoteip=localsubnet,100.64.0.0/10"; Flags: runhidden
Filename: "{app}\TripleSense.exe"; Description: "Open TripleSense"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""TripleSense - Controller"""; Flags: runhidden; RunOnceId: RemoveControllerFirewallRule
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""TripleSense - Discovery"""; Flags: runhidden; RunOnceId: RemoveDiscoveryFirewallRule

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

// Preserve uninstall restoration for settings changed by older previews.
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
      'TripleSense', LoginCommand) then begin
      if Pos(Lowercase(ExpandConstant('{app}\TripleSense.exe')), Lowercase(LoginCommand)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'TripleSense');
    end;
  end;
end;
