# VoiceInterface

语音交互接口，集成关键词唤醒(KWS)、语音活动检测(VAD)、云端语音识别(ASR)和声纹识别功能。

## 快速开始

```bash
git clone https://github.com/manceLMS/VoiceInterface.git
cd VoiceInterface
pip install -r requirements.txt
cp config.json.example config.json  # 填入自己的 API key
python main.py
```

## 配置

编辑 `config.json`，填入你的 DashScope API Key：

```json
{
  "cloud_asr": {
    "api_key": "your-dashscope-api-key-here"
  }
}
```
