; Shokz Type Windows 安装脚本
; 构建工具: Inno Setup 6.x  https://jrsoftware.org/isdl.php
;
; 用法（需先完成 PyInstaller 打包）:
;   cd packaging
;   iscc shokztype.iss
;
; 输出: packaging\dist\ShokzType_Setup_v0.1.0.exe

; ─────────────────────────────────────────────────────────────────
; 版本号等常量（更新版本时只改这里）
; ─────────────────────────────────────────────────────────────────
#define AppName        "Shokz Type"
#define AppVersion     "0.1.0"
#define AppPublisher   "Shokz"
#define AppExeName     "ShokzType.exe"
#define AppIcon        "..\shokztype\assets\shokztype.ico"

; ─────────────────────────────────────────────────────────────────
[Setup]
; AppId 唯一标识此应用，Windows 用它识别"同一软件的不同版本"
; 重要：同一应用的所有版本必须保持 AppId 不变；
;       可用 Inno Setup 菜单 Tools → Generate GUID 重新生成一个新 GUID
AppId={{A7C3F2E0-8B1D-4F6A-92CE-5D4E3B1A7F08}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} 安装程序

; 安装目录：有管理员权限 → Program Files\Shokz Type
;           无管理员权限 → %LOCALAPPDATA%\Programs\Shokz Type
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}

; 不强制要求管理员权限，方便普通员工直接安装
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog

; 最低 Windows 版本：Windows 10 1809（Edge WebView2 最低要求）
MinVersion=10.0.17763

AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=ShokzType_Setup_v{#AppVersion}
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\{#AppExeName}

; LZMA 压缩，包体最小
Compression=lzma2/max
SolidCompression=yes

; 现代向导样式
WizardStyle=modern
WizardSizePercent=100

; ─────────────────────────────────────────────────────────────────
[Languages]
; Inno Setup 6.x 内置中文简体语言包
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

; ─────────────────────────────────────────────────────────────────
[Tasks]
; 安装向导里的可选任务（默认勾选桌面图标）
Name: "desktopicon"; \
  Description: "在桌面创建快捷方式"; \
  GroupDescription: "附加快捷方式:"; \
  Flags: checkedonce

; ─────────────────────────────────────────────────────────────────
[Files]
; ── 主程序文件（PyInstaller 产物）──────────────────────────────
; config.json 单独处理：只在首次安装时复制，更新时保留用户配置
Source: "dist\ShokzType\config.json"; \
  DestDir: "{app}"; \
  Flags: onlyifdoesntexist uninsneveruninstall

; 其余所有文件（递归，排除 config.json 和开发工具脚本）
Source: "dist\ShokzType\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "config.json,create_shortcut.bat"

; ─────────────────────────────────────────────────────────────────
[Icons]
; 开始菜单
Name: "{group}\{#AppName}"; \
  Filename: "{app}\{#AppExeName}"

Name: "{group}\卸载 {#AppName}"; \
  Filename: "{uninstallexe}"

; 桌面快捷方式（仅当用户勾选了 desktopicon 任务时创建）
Name: "{autodesktop}\{#AppName}"; \
  Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon

; ─────────────────────────────────────────────────────────────────
[Run]
; 安装完成页面的"立即启动"选项
Filename: "{app}\{#AppExeName}"; \
  Description: "立即启动 {#AppName}"; \
  Flags: nowait postinstall skipifsilent

; ─────────────────────────────────────────────────────────────────
[UninstallDelete]
; 卸载时删除运行产生的日志目录（不删 config.json，保留用户设置）
Type: filesandordirs; Name: "{app}\logs"
