#ifndef BundleDir
  #error BundleDir must point to the PyInstaller application folder
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by tools/build_app.py
#endif

[Setup]
AppId={{8999F462-DC15-4AF6-8B14-9D1348FC1530}
AppName=TripleSense
AppVersion={#AppVersion}
AppPublisher=TripleSense contributors
AppPublisherURL=https://github.com/arwebSE/TripleSense
DefaultDirName={autopf}\TripleSense
DefaultGroupName=TripleSense
UsePreviousAppDir=no
UsePreviousGroup=no
UninstallDisplayIcon={app}\TripleSense.exe
PrivilegesRequired=admin
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=TripleSense-Setup-{#AppVersion}-Windows-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#ProjectRoot}\src\assets\triplesense.ico
LicenseFile={#ProjectRoot}\LICENSE
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TripleSense"; Filename: "{app}\TripleSense.exe"; IconFilename: "{app}\_internal\triplesense\assets\triplesense.ico"; AppUserModelID: "me.triplesense.app"
Name: "{autodesktop}\TripleSense"; Filename: "{app}\TripleSense.exe"; IconFilename: "{app}\_internal\triplesense\assets\triplesense.ico"; Tasks: desktopicon; AppUserModelID: "me.triplesense.app"

[Run]
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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var LoginCommand: String;
begin
  if CurUninstallStep = usUninstall then begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'TripleSense', LoginCommand) then begin
      if Pos(Lowercase(ExpandConstant('{app}\TripleSense.exe')), Lowercase(LoginCommand)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'TripleSense');
    end;
  end;
end;
