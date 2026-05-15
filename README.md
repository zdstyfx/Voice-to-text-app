# ShokzType 🎙️

**说话，它来打字。**  
**Speak. It types for you.**

对着麦克风说话，文字自动出现在你正在使用的任何窗口里——聊天框、文档、搜索栏，都行。  
Speak into your mic, and the text appears in whatever window you're using — chat, docs, search bars, anything.

---

## 它能做什么 / What it does

- **一键开录** — 按下快捷键开始说话，松开自动识别并输入  
  **One-key recording** — press a hotkey to start, release to transcribe and type

- **离线可用** — 本地模型，说的话不会上传到任何服务器  
  **Works offline** — local model, your voice never leaves your machine

- **也支持云端** — 想要更高精度，可以接阿里云 / 火山引擎  
  **Cloud option too** — connect DashScope or VolcEngine for higher accuracy

- **认识你的声音** — 声纹功能，只响应你的声音，别人说话不触发  
  **Knows your voice** — voiceprint filter so only your voice triggers it

- **自动唤醒** — 不想按键？说关键词自动开始录音  
  **Auto wakeup** — say a keyword to start recording, no hands needed

- **AI 润色** — 可选接入大模型，自动整理口语表达  
  **AI polish** — optionally connect an LLM to clean up spoken language

---

## 快速上手 / Getting Started

### 第一步：安装 / Step 1 — Install

```bash
git clone https://github.com/zdstyfx/Voice-to-text-app.git
cd Voice-to-text-app
pip install -r requirements.txt
```

### 第二步：配置 / Step 2 — Configure

```bash
cp config.json.example config.json
```

用记事本打开 `config.json`，填入你的 API Key（如果使用云端识别的话）。  
Open `config.json` and fill in your API key if you want cloud recognition.

### 第三步：启动 / Step 3 — Run

```bash
python -m shokztype
```

程序启动后会弹出一个窗口，直接在界面里操作就行。  
A window will pop up — everything can be controlled from there.

---

## 第一次运行说明 / First Run Note

首次启动会自动下载本地识别模型，共约 **500MB**，需要等几分钟，下载完成后后续启动秒开。  
On first launch, local models (~500MB total) will download automatically. This takes a few minutes once, then it's instant every time after.

也可以在设置页面手动触发下载。  
You can also trigger the download manually from the Settings page.

---

## 系统要求 / Requirements

| | |
|---|---|
| 系统 / OS | Windows 10/11 or macOS 12+ |
| Python | 3.10 或以上 / 3.10 or above |
| 麦克风 / Mic | 任意输入设备 / Any input device |

---

## 常见问题 / FAQ

**Q: 识别很慢怎么办？**  
A: 默认用本地模型跑在 CPU 上，速度一般。可以在设置里切换到云端识别，速度快很多。

**Q: Why is recognition slow?**  
A: The default local model runs on CPU. Switch to cloud recognition in Settings for much faster results.

---

**Q: macOS 提示没有辅助功能权限？**  
A: 前往「系统设置 → 隐私与安全性 → 辅助功能」，把终端或应用加进去。

**Q: macOS says it needs accessibility permission?**  
A: Go to System Settings → Privacy & Security → Accessibility, and add the terminal or app.

---

**Q: 我不想联网，可以纯离线用吗？**  
A: 可以。`config.json` 里把 `asr.backend` 设为 `local`，模型下载完之后完全离线运行。

**Q: Can I use it fully offline?**  
A: Yes. Set `asr.backend` to `local` in `config.json`. Once models are downloaded, no internet needed.

---

## License

[MIT](LICENSE)
