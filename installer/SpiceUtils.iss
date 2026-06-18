; ============================================================================
;  SpiceUtils - script Inno Setup -> produit "SpiceUtils-Setup.exe"
;
;  Installe l'application SpiceUtils (WebView) + son serveur + ses extensions
;  embarquees (Stem Extractor) + toutes les dependances Python.
;
;  - detecte une installation existante -> affiche "Mise a jour" ;
;  - arrete SpiceUtils AVANT de copier les fichiers ;
;  - cree des raccourcis (menu Demarrer + bureau optionnel) ;
;  - propose de lancer SpiceUtils a la fin.
;  PAS de tache planifiee : le demarrage auto est un reglage DANS l'app.
;
;  Compiler : "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" SpiceUtils.iss
; ============================================================================

#define MyAppName    "SpiceUtils"
#define MyAppVersion "1.1.5"
#define MyAppPublisher "SpiceUtils"
#define MyAppId "{A7C4E91F-2D6B-4A83-9F1C-SPICEUTILS001}"
#define PyW "{app}\app\.venv\Scripts\pythonw.exe"
#define MainPy "{app}\app\main.py"

[Setup]
AppId={{A7C4E91F-2D6B-4A83-9F1C-SPICEUTILS001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SpiceUtils
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputBaseFilename=SpiceUtils-Setup
OutputDir=Output
SetupIconFile=..\app\icon.ico
UninstallDisplayIcon={app}\app\icon.ico
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Windows 10 (1809) ou plus recent.
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; Application (UI + serveur + extensions). Le venv est cree a l'install.
Source: "..\app\*";          DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion; Excludes: ".venv\*,__pycache__\*,*.pyc"
Source: "postinstall.ps1";   DestDir: "{app}\installer"; Flags: ignoreversion
Source: "preuninstall.ps1";  DestDir: "{app}\installer"; Flags: ignoreversion
Source: "..\README.md";      DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\SpiceUtils";        Filename: "{#PyW}"; Parameters: """{#MainPy}"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\icon.ico"
Name: "{group}\Uninstall SpiceUtils"; Filename: "{uninstallexe}"
Name: "{userdesktop}\SpiceUtils";  Filename: "{#PyW}"; Parameters: """{#MainPy}"""; WorkingDir: "{app}\app"; IconFilename: "{app}\app\icon.ico"; Tasks: desktopicon

[Run]
; 1) Post-install (admin): standalone Python + FFmpeg + WebView2 + venv + deps.
;    Hidden window (runhidden); progress is shown in the wizard.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\installer\postinstall.ps1"" -AppDir ""{app}"""; \
  StatusMsg: "Installing components and dependencies (several minutes, please wait)..."; \
  Flags: runhidden waituntilterminated

; 2) Launch SpiceUtils (also after a silent update).
Filename: "{#PyW}"; Parameters: """{#MainPy}"""; WorkingDir: "{app}\app"; \
  Description: "Launch SpiceUtils now"; \
  Flags: runasoriginaluser nowait postinstall; \
  Check: ServerReady

[UninstallRun]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\preuninstall.ps1"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "StopSpiceUtils"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app\.venv"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\ffmpeg"

[Code]
var
  IsUpgrade: Boolean;

function DetectUpgrade(): Boolean;
var
  v: String;
  key: String;
begin
  key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  Result := RegQueryStringValue(HKLM64, key, 'DisplayVersion', v)
         or RegQueryStringValue(HKLM32, key, 'DisplayVersion', v);
end;

function InitializeSetup(): Boolean;
begin
  IsUpgrade := DetectUpgrade();
  Result := True;
end;

procedure InitializeWizard();
begin
  if IsUpgrade then
  begin
    WizardForm.WelcomeLabel1.Caption := 'Update {#MyAppName}';
    WizardForm.WelcomeLabel2.Caption :=
      'A version is already installed. This wizard will update it.' + #13#10 + #13#10 +
      'SpiceUtils will be stopped and can be relaunched at the end.';
  end;
end;

function ServerReady(): Boolean;
begin
  Result := FileExists(ExpandConstant('{#PyW}'));
end;

// Before copying: stop SpiceUtils (and its server) to free the files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like ''*SpiceUtils*main.py*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

[Messages]
WelcomeLabel2=This wizard will install SpiceUtils: the application, its stem-separation server, and the Stem Extractor extension (installable from the app).
