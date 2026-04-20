import asyncio
import os
import re

import keyboard
from fastapi import APIRouter, Request

from web.web_config import get_config, update_config

router = APIRouter()

# keywords.txt 路径
_KEYWORDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "keywords.txt")


# ---------------------------------------------------------------------------
# 基本配置
# ---------------------------------------------------------------------------

@router.get("/api/wakeup")
async def read_wakeup() -> dict:
    config = get_config()
    w = config.get("wakeup", {})
    return {
        "method": w.get("method", "hotkey"),
        "hotkey_combo": w.get("hotkey", {}).get("combo", "f2"),
        "start_keywords": _read_start_keywords(),
        "end_keywords": w.get("end_keywords", ["退出", "取消", "再见"]),
    }


@router.post("/api/wakeup")
async def save_wakeup(request: Request) -> dict:
    body = await request.json()
    update_data = {
        "wakeup": {
            "method": body.get("method", "hotkey"),
            "hotkey": {"combo": body.get("hotkey_combo", "f2")},
        }
    }
    if "end_keywords" in body:
        update_data["wakeup"]["end_keywords"] = body["end_keywords"]
    update_config(update_data)
    return {"success": True}


# ---------------------------------------------------------------------------
# 开始关键词（keywords.txt）
# ---------------------------------------------------------------------------

def _read_start_keywords() -> list[str]:
    """从 keywords.txt 读取唤醒词列表（只返回显示名）。"""
    if not os.path.exists(_KEYWORDS_PATH):
        return []
    keywords = []
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 格式: pinyin_tokens @显示名
            m = re.search(r"@(.+)$", line)
            if m:
                keywords.append(m.group(1))
    return keywords


def _write_start_keywords(keywords: list[dict]) -> None:
    """写入 keywords.txt。每个 keyword 是 {"name": "你好小韶", "pinyin": "n ǐ h ǎo ..."}。"""
    with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        for kw in keywords:
            f.write(f"{kw['pinyin']} @{kw['name']}\n")


@router.get("/api/wakeup/start-keywords")
async def get_start_keywords() -> dict:
    """读取开始关键词（含拼音）。"""
    if not os.path.exists(_KEYWORDS_PATH):
        return {"keywords": []}
    keywords = []
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.search(r"@(.+)$", line)
            if m:
                name = m.group(1)
                pinyin = line[:m.start()].strip()
                keywords.append({"name": name, "pinyin": pinyin})
    return {"keywords": keywords}


@router.post("/api/wakeup/start-keywords")
async def save_start_keywords(request: Request) -> dict:
    """保存开始关键词。body: {"keywords": [{"name": "你好小韶", "pinyin": "n ǐ h ǎo x iǎo sh áo"}]}"""
    body = await request.json()
    _write_start_keywords(body.get("keywords", []))
    return {"success": True}


@router.delete("/api/wakeup/start-keywords/{name}")
async def delete_start_keyword(name: str) -> dict:
    """删除一个开始关键词。"""
    if not os.path.exists(_KEYWORDS_PATH):
        return {"success": False, "error": "keywords.txt 不存在"}
    keywords = []
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if f"@{name}" not in line:
                keywords.append(line)
    with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        for line in keywords:
            f.write(line + "\n")
    return {"success": True}


# ---------------------------------------------------------------------------
# 热键录制
# ---------------------------------------------------------------------------

@router.post("/api/wakeup/record-hotkey")
async def record_hotkey() -> dict:
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    def on_key(event: keyboard.KeyboardEvent):
        if event.event_type != keyboard.KEY_DOWN:
            return
        if event.name in ("ctrl", "alt", "shift", "left ctrl", "right ctrl",
                          "left alt", "right alt", "left shift", "right shift",
                          "left windows", "right windows"):
            return
        parts = []
        if keyboard.is_pressed("ctrl"):
            parts.append("Ctrl")
        if keyboard.is_pressed("alt"):
            parts.append("Alt")
        if keyboard.is_pressed("shift"):
            parts.append("Shift")
        key_name = event.name
        if len(key_name) == 1:
            key_name = key_name.upper()
        parts.append(key_name)
        combo = "+".join(parts)
        keyboard.unhook(hook)
        if not future.done():
            loop.call_soon_threadsafe(future.set_result, combo)

    hook = keyboard.hook(on_key)

    try:
        combo = await asyncio.wait_for(future, timeout=10)
        return {"success": True, "combo": combo}
    except asyncio.TimeoutError:
        keyboard.unhook(hook)
        return {"success": False, "error": "超时：10秒内未检测到按键"}
