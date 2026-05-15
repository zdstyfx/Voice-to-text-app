# ShokzType macOS 打包指南

> 适用人员：没有任何预置环境，只有 Claude Code 的同事。  
> 目标：在 macOS 上打出 `ShokzType.app`，可直接双击运行。

---

## 前置要求

- macOS 12 (Monterey) 或更新版本
- 已联网（需要下载工具和依赖）
- 已有项目代码（zip 压缩包或 git 仓库）

---

## 第一步：安装 Homebrew（包管理器）

打开终端，粘贴以下命令并回车：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

安装完成后，**按照终端提示**把 brew 加入 PATH（Apple Silicon Mac 需要额外执行一条 `eval` 命令，终端会给出具体命令，复制粘贴执行即可）。

验证：
```bash
brew --version
```

---

## 第二步：安装 Python 3.11 和 Node.js

```bash
brew install python@3.11 node
```

验证：
```bash
python3.11 --version   # 应输出 Python 3.11.x
node --version         # 应输出 v18.x 或更新
npm --version
```

---

## 第三步：解压 / 进入项目目录

将项目 zip 解压，或者 git clone，然后：

```bash
cd /path/to/VoiceInterfaceV2   # 替换为实际路径
```

---

## 第四步：创建 Python 虚拟环境并安装依赖

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

安装项目依赖：
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

安装 macOS 额外依赖（PyObjC 全套 + PyInstaller）：
```bash
pip install pyobjc pyinstaller
```

> `pyobjc` 包含 AppKit、Foundation、Quartz 等所有 macOS 框架绑定，体积较大（约 200MB），耐心等待。

---

## 第五步：运行打包脚本

```bash
cd packaging
bash build.sh
```

脚本会依次执行：
1. 构建前端（npm install + npm run build）
2. PyInstaller 打包 Python 代码
3. 修复 librosa stub 文件
4. 跳过本地 ASR 模型（轻量化，用户可在应用内下载）
5. 复制 KWS 模型和配置文件
6. 编译 hotkey_helper.swift（Swift 热键辅助程序）
7. 代码签名（ad-hoc，无开发者证书时使用 `-` 自签名）

完成后输出路径：
```
packaging/dist/ShokzType/        # 文件夹版（可直接运行）
packaging/dist/ShokzType.app/    # .app bundle（推荐分发）
```

---

## 第六步：首次运行授权

双击 `ShokzType.app` 后，macOS 会弹出以下权限请求，全部允许：

- **麦克风**：语音识别必需
- **辅助功能**（系统设置 → 隐私与安全 → 辅助功能）：文字注入必需

如果 macOS 提示"无法打开，因为无法验证开发者"，右键点击 app → 打开 → 打开，即可绕过 Gatekeeper。

---

## 常见问题

### `swiftc: command not found`
需要安装 Xcode Command Line Tools：
```bash
xcode-select --install
```

### `pip install` 安装某个包报错
部分包编译时需要 Xcode CLT，执行 `xcode-select --install` 后重试。

### PyInstaller 报 `ModuleNotFoundError`
确保在 `.venv` 激活状态下运行 `bash build.sh`（提示符前面有 `(.venv)` 字样）。

### 打包成功但 app 打开后无内容 / 报错
打开终端，手动运行可执行文件查看错误日志：
```bash
./packaging/dist/ShokzType.app/Contents/MacOS/ShokzType
```

---

## 注意事项

- **config.json**：打包脚本使用 `config.json.example` 作为默认配置（不含 API Key）。用户首次运行后需在应用设置页填写云端 ASR 的 API Key（火山引擎 / 阿里云）。
- **本地模型**：默认不打包 FunASR 模型（约 500MB）。如需本地识别，在应用设置页点击"下载本地模型"即可。
- **分发**：`.app` bundle 可以直接压缩成 zip 发给用户，解压双击即用。无需 App Store 或开发者证书。
