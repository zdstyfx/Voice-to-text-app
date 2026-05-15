# ShokzType — Voice to Text Desktop App

> Chinese voice recognition app that listens, transcribes, and types directly into any window.  
> 中文语音识别桌面应用，实时转写并自动输入到任意窗口。

---

## Features / 功能特性

| | English | 中文 |
|---|---|---|
| 🎙️ | Local ASR (offline, no data sent) | 本地离线识别，数据不出本机 |
| ☁️ | Cloud ASR (DashScope / VolcEngine) | 支持阿里云、火山云端识别 |
| ⌨️ | Auto-type result into active window | 自动将结果输入到当前窗口 |
| 🔑 | Hotkey or VAD+Keyword wakeup | 快捷键 / 声纹+关键词唤醒 |
| 👤 | Speaker voiceprint filtering | 声纹识别，只响应指定说话人 |
| 🤖 | Optional LLM post-processing | 可接大模型对识别结果润色 |
| 🖥️ | Windows & macOS desktop app | 支持 Windows / macOS |

---

## Quick Start / 快速开始

### Prerequisites / 环境要求

- Python 3.10+
- Windows 10/11 or macOS 12+

### Install / 安装

```bash
git clone https://github.com/zdstyfx/Voice-to-text-app.git
cd Voice-to-text-app

pip install -r requirements.txt

cp config.json.example config.json
```

### Run / 运行

```bash
# Desktop window mode (default) / 桌面窗口模式（默认）
python -m shokztype

# HTTP server only, no window / 仅启动服务，不弹窗口
python -m shokztype --no-window

# Custom port / 自定义端口
python -m shokztype --port 9000
```

Open `http://localhost:8000` in your browser if running without a window.  
无窗口模式下，在浏览器打开 `http://localhost:8000`。

---

## Configuration / 配置

Edit `config.json` after copying from the example:  
从示例复制后编辑 `config.json`：

```json
{
  "asr": {
    "backend": "local"
  },
  "cloud_asr": {
    "provider": "dashscope",
    "api_key": "your-api-key-here"
  }
}
```

| Field / 字段 | Values / 可选值 | Description / 说明 |
|---|---|---|
| `asr.backend` | `local` / `cloud` | Local FunASR or cloud / 本地或云端 |
| `cloud_asr.provider` | `dashscope` / `volcengine` | Cloud provider / 云端服务商 |
| `cloud_asr.api_key` | string | Your API key / 你的 API Key |

---

## Architecture / 架构

```
shokztype/
├── core/          # Audio pipeline: VAD, ASR, speaker, KWS, output
│                  # 音频管线：VAD、识别、声纹、关键词、输出
├── web/           # FastAPI backend + React frontend
│                  # FastAPI 后端 + React 前端
│   ├── routers/   # REST / SSE API endpoints
│   ├── services/  # Pipeline orchestration
│   └── static/    # Built frontend (served directly)
├── desktop/       # NiceGUI alternative UI
└── __main__.py    # Entry point / 入口
```

**Pipeline flow / 管线流程:**

```
Wakeup (hotkey / VAD+KWS)
    → Transcriber (local FunASR / cloud ASR)
        → [optional] SpeakerGate (voiceprint filter)
            → [optional] LLM post-process
                → type_text() → active window
```

---

## Local ASR Models / 本地模型

On first run, models are downloaded automatically (~500MB total):  
首次运行会自动下载模型（共约 500MB）：

| Model | Size | Purpose |
|---|---|---|
| FunASR Paraformer | ~400MB | Speech recognition / 语音识别 |
| CAM++ | ~27MB | Speaker verification / 声纹验证 |
| FireRedVAD | ~10MB | Voice activity detection / 语音检测 |

You can also trigger download from the Settings page in the UI.  
也可以在 UI 设置页面手动触发下载。

---

## Packaging / 打包

Build a standalone executable with PyInstaller:  
使用 PyInstaller 打包为独立可执行文件：

```bash
# Windows
packaging/build.bat

# macOS
bash packaging/build.sh
```

Output: `packaging/dist/ShokzType/`  
Windows installer (Inno Setup): `packaging/dist/ShokzType_Setup_v0.1.0.exe`

---

## License / 许可

[MIT](LICENSE)
