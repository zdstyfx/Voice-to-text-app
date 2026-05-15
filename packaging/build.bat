@echo off
REM Shokz Type 打包脚本（轻量化版本，不含本地 ASR 模型）
REM 依赖：Python, Node.js, PyInstaller, Inno Setup 6.x (可选，用于生成安装包)
REM       Inno Setup 下载: https://jrsoftware.org/isdl.php

cd /d "%~dp0"

echo === Shokz Type 打包 ===
echo.

REM 0. 构建前端
echo [0/5] 构建前端...
cd ..\frontend
call npm install
if errorlevel 1 (
    echo 前端依赖安装失败！
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo 前端构建失败！
    pause
    exit /b 1
)
cd ..\packaging

REM 1a. 生成 splash screen 图片
echo.
echo [1a/5] 生成 splash screen...
python create_splash.py
if errorlevel 1 (
    echo   splash.png 生成失败，将跳过 splash screen（不影响打包）
)

REM 1b. PyInstaller
echo.
echo [1b/5] 正在打包...
pyinstaller --clean --noconfirm shokztype.spec
if errorlevel 1 (
    echo 打包失败！
    pause
    exit /b 1
)

set DIST=dist\ShokzType
set INTERNAL=%DIST%\_internal

REM 2. 修复 librosa stub
echo.
echo [2/5] 修复 librosa stub...
for /f "delims=" %%i in ('python -c "import librosa,os;print(os.path.dirname(librosa.__file__))"') do set LIBROSA_DIR=%%i
if exist "%LIBROSA_DIR%\__init__.pyi" (
    copy /Y "%LIBROSA_DIR%\__init__.pyi" "%INTERNAL%\librosa\" >nul
    for %%d in (core feature util) do (
        if exist "%LIBROSA_DIR%\%%d\__init__.pyi" (
            if not exist "%INTERNAL%\librosa\%%d" mkdir "%INTERNAL%\librosa\%%d"
            copy /Y "%LIBROSA_DIR%\%%d\__init__.pyi" "%INTERNAL%\librosa\%%d\" >nul
        )
    )
    echo   OK
)

REM 3. 本地 ASR 模型（轻量化：跳过，用户可在应用内按需下载）
echo.
echo [3/5] 跳过本地 ASR 模型（轻量化打包）
echo   默认使用云端 ASR，如需本地模型请在应用内下载

REM 4. 复制外部文件
echo.
echo [4/5] 复制配置和 KWS 模型...

if exist "..\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" (
    xcopy /E /I /Y "..\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" "%DIST%\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" >nul
    echo   KWS 模型 OK
)

copy /Y "..\keywords.txt" "%DIST%\" >nul 2>nul && echo   keywords.txt OK

copy /Y "..\config.json.example" "%DIST%\config.json" >nul
echo   config.json (from template) OK

REM 5. 复制快捷方式脚本（保留作备用）
echo.
echo [5/5] 复制附加文件...
copy /Y "create_shortcut.bat" "%DIST%\" >nul && echo   create_shortcut.bat OK
echo 输出: %CD%\%DIST%

REM 6. 健康检查
echo.
echo [验证] 运行打包产物健康检查...
python verify_build.py
if errorlevel 1 (
    echo.
    echo   警告：健康检查发现问题，建议修复后再制作安装包
    echo   是否仍然继续制作安装包？(按 Ctrl+C 取消，Enter 继续)
    pause >nul
)

REM 7. 制作 Inno Setup 安装包
echo.
echo [安装包] 检查 Inno Setup...
where iscc >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo   找到 iscc，正在编译安装包...
    iscc shokztype.iss
    if errorlevel 1 (
        echo   安装包编译失败！请检查 shokztype.iss 配置
    ) else (
        echo.
        echo ┌─────────────────────────────────────────────────────┐
        echo │  安装包已生成:                                      │
        echo │  dist\ShokzType_Setup_v0.1.0.exe                   │
        echo │                                                     │
        echo │  用户体验: 双击 .exe → 向导 → 桌面快捷方式自动创建  │
        echo └─────────────────────────────────────────────────────┘
    )
) else (
    echo.
    echo   未找到 iscc（Inno Setup 编译器）
    echo   如需生成 .exe 安装包，请先安装 Inno Setup 6.x:
    echo     https://jrsoftware.org/isdl.php
    echo.
    echo   当前只生成了文件夹: %DIST%\
    echo   分发方法（备用）：将文件夹打包发给用户，用户运行 create_shortcut.bat
)
echo.
pause
