@echo off
REM Shokz Type 打包脚本

cd /d "%~dp0"

echo === Shokz Type 打包 ===
echo.

REM 1. PyInstaller
echo [1/5] 正在打包...
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

REM 3. 复制 ASR + 声纹模型
echo.
echo [3/5] 复制模型文件...
set MODEL_CACHE=%USERPROFILE%\.cache\modelscope\hub\models\iic
set MODEL_DIST=%DIST%\models

if not exist "%MODEL_DIST%" mkdir "%MODEL_DIST%"

for %%m in (
    speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx
    punc_ct-transformer_zh-cn-common-vocab272727-onnx
    speech_campplus_sv_zh-cn_16k-common
    speech_fsmn_vad_zh-cn-16k-common-onnx
) do (
    if exist "%MODEL_CACHE%\%%m" (
        xcopy /E /I /Y "%MODEL_CACHE%\%%m" "%MODEL_DIST%\%%m" >nul
        echo   %%m OK
    ) else (
        echo   %%m 未找到，跳过
    )
)

REM 4. 复制外部文件
echo.
echo [4/5] 复制配置和 KWS 模型...

if exist "..\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" (
    xcopy /E /I /Y "..\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" "%DIST%\sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" >nul
    echo   KWS 模型 OK
)

copy /Y "..\keywords.txt" "%DIST%\" >nul 2>nul && echo   keywords.txt OK

if exist "..\config.json" (
    copy /Y "..\config.json" "%DIST%\config.json" >nul
    echo   config.json OK
) else (
    copy /Y "..\config.json.example" "%DIST%\config.json" >nul
    echo   config.json (template) OK
)

REM 5. 完成
echo.
echo [5/5] 打包完成！
echo 输出: %CD%\%DIST%
echo.
pause
