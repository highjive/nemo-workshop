; Inno Setup script for Nemo on Windows.
;
; Primary build. The target machine runs Windows 11 via a bypass install on
; a 2nd-gen Core CPU. That works and keeps working -- Sandy Bridge has SSE4.2
; and POPCNT, which is what 24H2 and later require to boot -- but two things
; need handling that do not arise on supported hardware: the AVX-only
; llama.cpp build, and software OpenGL, because no Windows 11 driver for
; HD Graphics 3000 exists or ever will.

#define AppName    "Nemo"
#define AppVersion "0.1.0"
#define AppDir     "C:\Nemo"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={#AppDir}
DefaultGroupName={#AppName}
OutputBaseFilename=nemo-setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
DisableDirPage=no
WizardStyle=modern

[Types]
Name: "full";    Description: "Everything (needs ~9 GB)"
Name: "compact"; Description: "Tools only, download models later"
Name: "custom";  Description: "Choose components"; Flags: iscustom

[Components]
Name: "core";   Description: "Nemo core and parts library";   Types: full compact custom; Flags: fixed
Name: "engine"; Description: "llama.cpp (AVX-only build)";    Types: full compact custom
Name: "models"; Description: "Three GGUF models (~5.6 GB)";   Types: full
Name: "eda";    Description: "KiCad and WireViz";             Types: full compact custom
Name: "cad";    Description: "CadQuery and FreeCAD";          Types: full custom

[Files]
Source: "payload\nemo\*";   DestDir: "{app}\core\nemo";  Flags: recursesubdirs; Components: core
Source: "payload\parts\*";  DestDir: "{app}\parts";      Flags: recursesubdirs; Components: core
Source: "payload\python\*"; DestDir: "{app}\python";     Flags: recursesubdirs; Components: core
Source: "payload\llama\*";  DestDir: "{app}\engine";     Flags: recursesubdirs; Components: engine
Source: "payload\models\*"; DestDir: "{app}\engine\models"; Flags: recursesubdirs; Components: models
Source: "payload\kicad\*";  DestDir: "{app}\tools\kicad"; Flags: recursesubdirs; Components: eda

[Icons]
Name: "{group}\Nemo (talk mode)"; Filename: "{app}\nemo.cmd"; Parameters: "mode talk"
Name: "{group}\Nemo doctor";      Filename: "{app}\nemo.cmd"; Parameters: "doctor"
Name: "{group}\Projects";         Filename: "{app}\projects"

[Run]
; Always run the doctor. On this hardware the install is not the hard part;
; the configuration is.
Filename: "{app}\nemo.cmd"; Parameters: "doctor"; \
  Description: "Check this machine"; Flags: postinstall runascurrentuser

[Code]
// Two checks, both of which decide whether this install will actually work.

function HasBasicDisplayAdapter(): Boolean;
var
  ResultCode: Integer;
  Output: AnsiString;
begin
  Result := False;
  if LoadStringFromFile(ExpandConstant('{tmp}\gpu.txt'), Output) then
    Result := Pos('Basic Display', Output) > 0;
end;

function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  Result := True;
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox('Nemo needs Windows 10 or later.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  MsgBox('Two things about this machine before you continue.' + #13#10#13#10 +
         '1. This CPU has no AVX2. Nemo ships and expects the AVX-only ' +
         'llama.cpp build. A stock release binary will fault or run at a ' +
         'fraction of its speed, and it will look like the hardware being ' +
         'too slow.' + #13#10#13#10 +
         '2. There is no Windows 11 graphics driver for HD Graphics 3000 ' +
         'and there never will be. KiCad''s canvas and FreeCAD''s 3D view ' +
         'need OpenGL that Windows cannot provide here. After install, run ' +
         'setup-mesa.ps1 to add a software renderer.' + #13#10#13#10 +
         'Run "nemo doctor" when setup finishes. It checks both.',
         mbInformation, MB_OK);
end;
