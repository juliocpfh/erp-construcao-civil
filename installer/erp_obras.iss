; Instalador do ERP Obras (Inno Setup 6). Compilado pelo GitHub Actions após installer\build_windows.ps1.
#define AppName "ERP Obras"
#define AppVersion GetEnv("ERP_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F2C9A41-7D3B-4E8A-9B1C-2E5D8F0A7C31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ERP Obras
DefaultDirName={localappdata}\Programs\ERP Obras
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ERP-Obras-Setup
SetupIconFile=erp_obras.ico
UninstallDisplayIcon={app}\erp_obras.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
ptbr.WelcomeLabel2=Este assistente vai instalar o [name/ver] neste computador, com o leitor de notas fiscais (OCR) incluso.%n%nNo primeiro acesso como administrador você escolhe onde guardar o banco de dados:%n%n• Neste computador (disco): acessível só neste computador, não pelo celular nem remotamente.%n• No seu FTP: acessível pelo link do sistema, de qualquer lugar, conforme o nível de acesso de cada usuário.

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
; atualização: remove o código antigo (os dados ficam em %LOCALAPPDATA%\ERP Obras\data e são preservados)
Type: filesandordirs; Name: "{app}\erp"

[Files]
Source: "..\build\ERP-Obras\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ERP Obras"; Filename: "{app}\python\python.exe"; Parameters: """{app}\erp_launcher.py"""; WorkingDir: "{app}"; IconFilename: "{app}\erp_obras.ico"
Name: "{group}\Pasta de dados do ERP"; Filename: "{localappdata}\ERP Obras\data"
Name: "{group}\Desinstalar ERP Obras"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ERP Obras"; Filename: "{app}\python\python.exe"; Parameters: """{app}\erp_launcher.py"""; WorkingDir: "{app}"; IconFilename: "{app}\erp_obras.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: """{app}\erp_launcher.py"""; WorkingDir: "{app}"; Description: "Abrir o ERP Obras agora"; Flags: postinstall nowait skipifsilent
