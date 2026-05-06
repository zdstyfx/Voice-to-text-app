"""Web 层配置扩展。

在 shokztype.core.config 基础上，增加 LLM、Prompt、处理模式等 Web 专用字段。
"""

import json
import os
import threading
from typing import Any

from shokztype.core.config import DEFAULT_CONFIG as APP_DEFAULT_CONFIG, _merge_dict

WEB_EXTRA_DEFAULTS: dict[str, Any] = {
    "currentMode": "translate",
    "llm": {
        "apiBaseUrl": "",
        "apiKey": "",
        "model": "",
        "timeoutSeconds": 90,
        "temperature": 0.2,
    },
    "translateTargetLanguage": "\u82f1\u8bed",
    "prompts": {
        "translate": (
            "你是一个语音转写文本的翻译工具。\n"
            "将下面的语音转写文本翻译为{targetLanguage}，直接给出译文，不要添加任何解释或标记。\n"
            "绝对不要输出空行。\n"
            "{text}"
        ),
        "polish": (
            "你是一个语音转写文本的润色工具。\n"
            "将下面的口语转写文本整理为通顺的书面表达，修正语音识别可能产生的错别字，去除口语中的语气词和重复，保留原意，不要添加任何解释或标记，直接给出润色后的纯文本。\n"
            "绝对不要输出空行。\n"
            "{text}"
        ),
    },
    "voiceprint": {
        "enabled": False,
        "activeProfiles": [],
    },
    "wakeup": {
        "method": "hotkey",
        "hotkey": {"combo": "f2"},
        "vad": {"keyword": ""},
    },
}

DEFAULT_CONFIG = _merge_dict(APP_DEFAULT_CONFIG, WEB_EXTRA_DEFAULTS)

_lock = threading.RLock()
_config: dict[str, Any] | None = None
_config_path: str | None = None


def _resolve_config_path(path: str | None = None) -> str:
    if path:
        return os.path.abspath(path)
    from shokztype import DATA_DIR, APP_DIR
    data_cfg = os.path.join(DATA_DIR, "config.json")
    app_cfg = os.path.join(APP_DIR, "config.json")
    # 优先用可写目录的配置；首次运行从 APP_DIR 复制到 DATA_DIR
    if not os.path.exists(data_cfg) and os.path.exists(app_cfg) and DATA_DIR != APP_DIR:
        import shutil
        shutil.copy2(app_cfg, data_cfg)
    return data_cfg if DATA_DIR != APP_DIR else app_cfg


def load_config(path: str | None = None) -> dict[str, Any]:
    global _config, _config_path
    with _lock:
        _config_path = _resolve_config_path(path)
        if os.path.exists(_config_path):
            with open(_config_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            _config = _merge_dict(DEFAULT_CONFIG, overrides)
        else:
            _config = dict(DEFAULT_CONFIG)
            _save_to_disk(_config, _config_path)
        return dict(_config)


def get_config() -> dict[str, Any]:
    with _lock:
        if _config is None:
            return load_config()
        return dict(_config)


def update_config(overrides: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if _config is None:
            load_config()
        merged = _merge_dict(_config, overrides)
        _config.clear()
        _config.update(merged)
        _save_to_disk(_config, _config_path)
        return dict(_config)


def _save_to_disk(config: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
