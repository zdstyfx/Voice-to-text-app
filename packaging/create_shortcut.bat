@echo off
chcp 65001 >nul
setlocal

set "EXE_DIR=%~dp0"
set "EXE_PATH=%EXE_DIR%ShokzType.exe"
set "ICON_PATH=%EXE_DIR%_internal\shokztype\assets\shokztype.ico"
set "SHORTCUT=%USERPROFILE%\Desktop\Shokz Type.lnk"

powershell -NoProfile -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT%');" ^
  "$s.TargetPath = '%EXE_PATH%';" ^
  "$s.WorkingDirectory = '%EXE_DIR%';" ^
  "$s.IconLocation = '%ICON_PATH%';" ^
  "$s.Description = 'Shokz Type 语音输入';" ^
  "$s.Save();"

if %errorlevel% == 0 (
    echo 桌面快捷方式已创建：Shokz Type
) else (
    echo 创建失败，请右键以管理员身份运行此脚本。
)
pause
