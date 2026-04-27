import asyncio
import logging
import os
import re

import keyboard
from fastapi import APIRouter, Request

from shokztype.web.web_config import get_config, update_config
from shokztype import PROJECT_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()

from shokztype import APP_DIR
_PROJECT_ROOT = PROJECT_ROOT
_KEYWORDS_PATH = os.path.join(APP_DIR, "keywords.txt")


def _get_tokens_path() -> str:
    config = get_config()
    model_dir = config.get("kws", {}).get("model_dir", "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20")
    if not os.path.isabs(model_dir):
        model_dir = os.path.join(APP_DIR, model_dir)
    return os.path.join(model_dir, "tokens.txt")


# ---------------------------------------------------------------------------
# keywords.txt 读写（开始词 + 结束词统一管理）
# ---------------------------------------------------------------------------

def _read_all_keywords() -> list[dict]:
    """读取 keywords.txt 全部行，返回 [{"name": ..., "pinyin": ...}]。"""
    if not os.path.exists(_KEYWORDS_PATH):
        return []
    result = []
    with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.search(r"@(.+)$", line)
            if m:
                result.append({"name": m.group(1), "pinyin": line[:m.start()].strip()})
    return result


def _write_all_keywords(keywords: list[dict]) -> None:
    """写入 keywords.txt（开始词 + 结束词）。"""
    with open(_KEYWORDS_PATH, "w", encoding="utf-8") as f:
        for kw in keywords:
            f.write(f"{kw['pinyin']} @{kw['name']}\n")


def _rebuild_keywords_file(start_keywords: list[dict], end_keyword_names: list[str]) -> None:
    """用开始词列表 + 结束词名称列表重建 keywords.txt。

    start_keywords: [{"name": ..., "pinyin": ...}] — 已编码
    end_keyword_names: ["退出", "取消", ...] — 纯文本，需要编码
    """
    from shokztype.core.kws_add_keyword import text_to_kws_line

    all_kws = list(start_keywords)
    existing_names = {kw["name"] for kw in all_kws}
    tokens_path = _get_tokens_path()

    for name in end_keyword_names:
        if name in existing_names:
            continue
        try:
            line = text_to_kws_line(name, tokens_path)
            m = re.search(r"@(.+)$", line)
            pinyin = line[:m.start()].strip() if m else line
            all_kws.append({"name": name, "pinyin": pinyin})
        except Exception as e:
            logger.warning("结束词 '%s' token 编码失败: %s", name, e)

    _write_all_keywords(all_kws)


def _read_start_keywords_with_pinyin() -> list[dict]:
    """读取开始词（排除结束词），含拼音。"""
    config = get_config()
    end_names = set(config.get("wakeup", {}).get("end_keywords", []))
    return [kw for kw in _read_all_keywords() if kw["name"] not in end_names]


def _read_start_keyword_names() -> list[str]:
    """读取开始词名称列表（排除结束词）。"""
    return [kw["name"] for kw in _read_start_keywords_with_pinyin()]


def _notify_pipeline():
    from shokztype.web.services.event_bus import bus
    bus.emit("config_changed", {"wakeup": {"keywords_file": True}})


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
        "start_keywords": _read_start_keyword_names(),
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
    end_keywords_changed = False
    if "end_keywords" in body:
        update_data["wakeup"]["end_keywords"] = body["end_keywords"]
        end_keywords_changed = True

    update_config(update_data)

    # 结束词变了 → 重建 keywords.txt
    if end_keywords_changed:
        start_kws = _read_start_keywords_with_pinyin()
        _rebuild_keywords_file(start_kws, body["end_keywords"])

    from shokztype.web.services.event_bus import bus
    bus.emit("config_changed", update_data)
    return {"success": True}


# ---------------------------------------------------------------------------
# 开始关键词
# ---------------------------------------------------------------------------

@router.get("/api/wakeup/start-keywords")
async def get_start_keywords() -> dict:
    return {"keywords": _read_start_keywords_with_pinyin()}


@router.post("/api/wakeup/start-keywords")
async def save_start_keywords(request: Request) -> dict:
    """保存开始关键词。body: {"keywords": [{"name": ..., "pinyin": ...}]}"""
    body = await request.json()
    start_kws = body.get("keywords", [])
    config = get_config()
    end_names = config.get("wakeup", {}).get("end_keywords", [])
    _rebuild_keywords_file(start_kws, end_names)
    _notify_pipeline()
    return {"success": True}


@router.delete("/api/wakeup/start-keywords/{name}")
async def delete_start_keyword(name: str) -> dict:
    start_kws = [kw for kw in _read_start_keywords_with_pinyin() if kw["name"] != name]
    config = get_config()
    end_names = config.get("wakeup", {}).get("end_keywords", [])
    _rebuild_keywords_file(start_kws, end_names)
    _notify_pipeline()
    return {"success": True}


@router.post("/api/wakeup/add-start-keyword")
async def add_start_keyword(request: Request) -> dict:
    from shokztype.core.kws_add_keyword import text_to_kws_line

    body = await request.json()
    keyword = body.get("keyword", "").strip()
    if not keyword:
        return {"success": False, "error": "唤醒词不能为空"}

    existing = _read_start_keyword_names()
    if keyword in existing:
        return {"success": False, "error": "该唤醒词已存在"}

    try:
        line = text_to_kws_line(keyword, _get_tokens_path())
    except (ValueError, FileNotFoundError) as e:
        return {"success": False, "error": str(e)}

    m = re.search(r"@(.+)$", line)
    pinyin = line[:m.start()].strip() if m else line

    start_kws = _read_start_keywords_with_pinyin()
    start_kws.append({"name": keyword, "pinyin": pinyin})
    config = get_config()
    end_names = config.get("wakeup", {}).get("end_keywords", [])
    _rebuild_keywords_file(start_kws, end_names)
    _notify_pipeline()
    return {"success": True, "keyword": keyword}


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
