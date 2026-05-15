#!/usr/bin/env bash
# Shokz Type macOS 打包脚本（轻量化版本，不含本地 ASR 模型）

set -e
cd "$(dirname "$0")"

echo "=== Shokz Type macOS 打包 ==="
echo

PYTHON_BIN="${PYTHON_BIN:-python3}"

# 0a. 构建前端
echo "[0/6] 构建前端..."
cd ../frontend
npm install
npm run build
cd ../packaging
echo "  前端 OK"
echo

# 0b. 生成 .icns 图标（如果不存在）
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

# 1. PyInstaller（macOS 不需要 splash，跳过生成步骤）
echo
echo "[1/6] 正在打包..."
pyinstaller --clean --noconfirm shokztype.spec

DIST=dist/ShokzType
APP=dist/ShokzType.app
INTERNAL="$DIST/_internal"

# 2. 修复 librosa stub
echo
echo "[2/6] 修复 librosa stub..."
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

# 3. 本地 ASR 模型（轻量化：跳过，用户可在应用内按需下载）
echo
echo "[3/6] 跳过本地 ASR 模型（轻量化打包）"
echo "  默认使用云端 ASR，如需本地模型请在应用内下载"

# 4. 复制外部文件
echo
echo "[4/6] 复制配置和 KWS 模型..."

KWS_DIR="../sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
if [ -d "$KWS_DIR" ]; then
    cp -R "$KWS_DIR" "$DIST/"
    echo "  KWS 模型 OK"
fi

cp ../keywords.txt "$DIST/" 2>/dev/null && echo "  keywords.txt OK" || true

cp "../config.json.example" "$DIST/config.json"
echo "  config.json (from template) OK"

# 如果有 .app bundle，也复制配置到 .app 内
if [ -d "$APP" ]; then
    APP_DIR="$APP/Contents/MacOS"
    [ -d "$KWS_DIR" ] && cp -R "$KWS_DIR" "$APP_DIR/" && echo "  .app: KWS OK"
    cp ../keywords.txt "$APP_DIR/" 2>/dev/null && echo "  .app: keywords.txt OK" || true
    cp "$DIST/config.json" "$APP_DIR/" && echo "  .app: config.json OK"
fi

# 5. 编译并复制 macOS 热键 helper
if [ -d "$APP" ] && [ -f "hotkey_helper.swift" ]; then
    echo
    echo "[5/6] 编译 hotkey helper..."
    swiftc hotkey_helper.swift -o hotkey_helper
    cp hotkey_helper "$DIST/hotkey_helper"
    cp hotkey_helper "$APP/Contents/MacOS/hotkey_helper"
    echo "  hotkey_helper OK"
fi

# 6. 重新签名（加入麦克风等 entitlements）
if [ -d "$APP" ] && [ -f "entitlements.plist" ]; then
    echo
    echo "[6/6] 签名 .app (entitlements)..."
    rm -f "$APP/Contents/MacOS/shokztype.log" "$APP/Contents/MacOS/hotkey_helper.log"
    if [ -f "$APP/Contents/MacOS/hotkey_helper" ]; then
        codesign --force --sign - --entitlements entitlements.plist "$APP/Contents/MacOS/hotkey_helper"
    fi
    codesign --force --deep --sign - --entitlements entitlements.plist "$APP" && echo "  OK" || echo "  签名失败"
fi

# 健康检查
echo
echo "[验证] 运行打包产物健康检查..."
"$PYTHON_BIN" verify_build.py --mac || true   # 检查失败不阻断 DMG 制作

# 7. 制作 DMG 分发包
APP_VERSION="0.1.0"
DMG_NAME="ShokzType_v${APP_VERSION}.dmg"
DMG_OUT="dist/${DMG_NAME}"
DMG_VOLNAME="Shokz Type"
DMG_STAGING="dist/.dmg_staging"
DMG_TMP="dist/.tmp_shokztype.dmg"

if [ ! -d "$APP" ]; then
    echo
    echo "  跳过 DMG（未找到 .app bundle）"
else
    echo
    echo "[DMG] 制作 macOS 分发包..."
    rm -rf "$DMG_STAGING" "$DMG_TMP" "$DMG_OUT"
    mkdir -p "$DMG_STAGING"

    # 复制 .app 和 Applications 快捷方式到暂存目录
    cp -R "$APP" "$DMG_STAGING/Shokz Type.app"
    ln -s /Applications "$DMG_STAGING/Applications"

    # 计算所需空间（动态，加 10% 缓冲）
    APP_KB=$(du -sk "$DMG_STAGING" | cut -f1)
    DMG_MB=$(( (APP_KB * 11 / 10) / 1024 + 5 ))

    # 创建可读写临时 DMG
    hdiutil create \
        -size "${DMG_MB}m" \
        -volname "$DMG_VOLNAME" \
        -fs HFS+ \
        -format UDRW \
        -srcfolder "$DMG_STAGING" \
        "$DMG_TMP" \
        -quiet
    echo "  临时 DMG 已创建 (${DMG_MB}MB)"

    # 挂载临时 DMG
    MOUNT_POINT="/Volumes/${DMG_VOLNAME}"
    hdiutil attach "$DMG_TMP" -mountpoint "$MOUNT_POINT" -quiet -noautoopen

    # 通过 AppleScript 设置 Finder 窗口外观：图标位置、窗口大小
    # 左：ShokzType.app (130, 170)   右：Applications (370, 170)
    osascript << APPLESCRIPT
tell application "Finder"
    tell disk "${DMG_VOLNAME}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 700, 420}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 96
        set position of item "Shokz Type.app" of container window to {130, 165}
        set position of item "Applications" of container window to {375, 165}
        close
        open
        update without registering applications
        delay 1
    end tell
end tell
APPLESCRIPT

    # 等待 Finder 写完 .DS_Store
    sync
    sleep 2

    # 卸载
    hdiutil detach "$MOUNT_POINT" -quiet

    # 转换为只读压缩 DMG
    hdiutil convert "$DMG_TMP" \
        -format UDZO \
        -imagekey zlib-level=9 \
        -o "$DMG_OUT" \
        -quiet

    # 清理
    rm -f "$DMG_TMP"
    rm -rf "$DMG_STAGING"

    DMG_SIZE_MB=$(du -sm "$DMG_OUT" | cut -f1)
    echo
    echo "┌──────────────────────────────────────────────────────┐"
    echo "│  DMG 已生成:  dist/${DMG_NAME}  (${DMG_SIZE_MB}MB)         │"
    echo "│                                                      │"
    echo "│  用户体验: 双击挂载 → 拖 app 到 Applications → 完成  │"
    echo "└──────────────────────────────────────────────────────┘"
fi

echo
echo "=== 全部完成 ==="
echo "文件夹: $(pwd)/$DIST"
[ -d "$APP" ]     && echo ".app:   $(pwd)/$APP"
[ -f "$DMG_OUT" ] && echo "DMG:    $(pwd)/$DMG_OUT"
