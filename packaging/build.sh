#!/usr/bin/env bash
# Shokz Type macOS 打包脚本

set -e
cd "$(dirname "$0")"

echo "=== Shokz Type macOS 打包 ==="
echo

PYTHON_BIN="${PYTHON_BIN:-python}"

# 0. 生成 .icns 图标（如果不存在）
ICNS="../shokztype/assets/shokztype.icns"
ICO="../shokztype/assets/shokztype.ico"
if [ ! -f "$ICNS" ] && [ -f "$ICO" ]; then
    echo "[0] 生成 .icns 图标..."
    "$PYTHON_BIN" -c "
from PIL import Image
import os, subprocess, tempfile, shutil
img = Image.open('$ICO')
tmpdir = tempfile.mkdtemp()
iconset = os.path.join(tmpdir, 'shokztype.iconset')
os.makedirs(iconset)
for sz in [16, 32, 64, 128, 256, 512]:
    img.resize((sz, sz), Image.LANCZOS).save(os.path.join(iconset, f'icon_{sz}x{sz}.png'))
for sz in [32, 64, 256, 512]:
    shutil.copy2(os.path.join(iconset, f'icon_{sz}x{sz}.png'), os.path.join(iconset, f'icon_{sz//2}x{sz//2}@2x.png'))
img.resize((1024, 1024), Image.LANCZOS).save(os.path.join(iconset, 'icon_512x512@2x.png'))
subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', '$ICNS'], check=True)
shutil.rmtree(tmpdir)
" && echo "  OK" || echo "  跳过（生成失败）"
fi

# 1. PyInstaller
echo
echo "[1/5] 正在打包..."
pyinstaller --clean --noconfirm shokztype.spec

DIST=dist/ShokzType
APP=dist/ShokzType.app
INTERNAL="$DIST/_internal"

# 2. 修复 librosa stub
echo
echo "[2/5] 修复 librosa stub..."
LIBROSA_DIR=$("$PYTHON_BIN" -c "import librosa,os;print(os.path.dirname(librosa.__file__))")
if [ -f "$LIBROSA_DIR/__init__.pyi" ]; then
    cp "$LIBROSA_DIR/__init__.pyi" "$INTERNAL/librosa/"
    for d in core feature util; do
        if [ -f "$LIBROSA_DIR/$d/__init__.pyi" ]; then
            mkdir -p "$INTERNAL/librosa/$d"
            cp "$LIBROSA_DIR/$d/__init__.pyi" "$INTERNAL/librosa/$d/"
        fi
    done
    echo "  OK"
fi

# 3. 复制 ASR + 声纹模型
echo
echo "[3/5] 复制模型文件..."
MODEL_CACHE="$HOME/.cache/modelscope/hub/models/iic"
MODEL_DIST="$DIST/models"
mkdir -p "$MODEL_DIST"

for m in \
    speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx \
    punc_ct-transformer_zh-cn-common-vocab272727-onnx \
    speech_campplus_sv_zh-cn_16k-common \
    speech_fsmn_vad_zh-cn-16k-common-onnx; do
    if [ -d "$MODEL_CACHE/$m" ]; then
        cp -R "$MODEL_CACHE/$m" "$MODEL_DIST/"
        echo "  $m OK"
    else
        echo "  $m 未找到，跳过"
    fi
done

# 4. 复制外部文件
echo
echo "[4/5] 复制配置和 KWS 模型..."

KWS_DIR="../sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
if [ -d "$KWS_DIR" ]; then
    cp -R "$KWS_DIR" "$DIST/"
    echo "  KWS 模型 OK"
fi

cp ../keywords.txt "$DIST/" 2>/dev/null && echo "  keywords.txt OK" || true

if [ -f "../config.json" ]; then
    cp "../config.json" "$DIST/config.json"
    echo "  config.json OK"
else
    cp "../config.json.example" "$DIST/config.json"
    echo "  config.json (template) OK"
fi

# 如果有 .app bundle，也复制模型/配置到 .app 内
if [ -d "$APP" ]; then
    APP_DIR="$APP/Contents/MacOS"
    [ -d "$MODEL_DIST" ] && cp -R "$MODEL_DIST" "$APP_DIR/models" && echo "  .app: models OK"
    [ -d "$KWS_DIR" ] && cp -R "$KWS_DIR" "$APP_DIR/" && echo "  .app: KWS OK"
    cp ../keywords.txt "$APP_DIR/" 2>/dev/null && echo "  .app: keywords.txt OK" || true
    [ -f "$DIST/config.json" ] && cp "$DIST/config.json" "$APP_DIR/" && echo "  .app: config.json OK" || true
fi

# 5. 编译并复制 macOS 热键 helper
if [ -d "$APP" ] && [ -f "hotkey_helper.swift" ]; then
    echo
    echo "[5/7] 编译 hotkey helper..."
    swiftc hotkey_helper.swift -o hotkey_helper
    cp hotkey_helper "$DIST/hotkey_helper"
    cp hotkey_helper "$APP/Contents/MacOS/hotkey_helper"
    echo "  hotkey_helper OK"
fi

# 6. 重新签名（加入麦克风等 entitlements）
if [ -d "$APP" ] && [ -f "entitlements.plist" ]; then
    echo
    echo "[6/7] 签名 .app (entitlements)..."
    rm -f "$APP/Contents/MacOS/shokztype.log" "$APP/Contents/MacOS/hotkey_helper.log"
    if [ -f "$APP/Contents/MacOS/hotkey_helper" ]; then
        codesign --force --sign - --entitlements entitlements.plist "$APP/Contents/MacOS/hotkey_helper"
    fi
    codesign --force --deep --sign - --entitlements entitlements.plist "$APP" && echo "  OK" || echo "  签名失败"
fi

# 7. 完成
echo
echo "[7/7] 打包完成！"
echo "文件夹: $(pwd)/$DIST"
[ -d "$APP" ] && echo ".app:   $(pwd)/$APP"
