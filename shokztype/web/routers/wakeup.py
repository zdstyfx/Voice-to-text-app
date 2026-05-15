import asyncio
import logging
import os
import re

from fastapi import APIRouter, Request

from shokztype.web.web_config import get_config, update_config
from shokztype.core.hotkeys import PersistentKeyListener, MODIFIER_KEYS
from shokztype import PROJECT_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()

from shokztype import APP_DIR, DATA_DIR
_PROJECT_ROOT = PROJECT_ROOT
_KEYWORDS_PATH = os.path.join(DATA_DIR, "keywords.txt")

# 首次运行：从 APP_DIR 复制 keywords.txt 到可写目录
if DATA_DIR != APP_DIR and not os.path.exists(_KEYWORDS_PATH):
    _src = os.path.join(APP_DIR, "keywords.txt")
    if os.path.exists(_src):
        import shutil
        shutil.copy2(_src, _KEYWORDS_PATH)


def _get_tokens_path() -> str:
    from shokztype.core.kws import _safe_ascii_path
    config = get_config()
    model_dir = config.get("kws", {}).get("model_dir", "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20")
    if not os.path.isabs(model_dir):
        model_dir = os.path.join(APP_DIR, model_dir)
    model_dir = _safe_ascii_path(model_dir, "kws-model")
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
    # 同步到 kws.keywords_file（sherpa-onnx 需要 ASCII 路径时使用）
    kws_path = get_config().get("kws", {}).get("keywords_file", "")
    if kws_path and os.path.abspath(kws_path) != os.path.abspath(_KEYWORDS_PATH):
        import shutil
        os.makedirs(os.path.dirname(kws_path), exist_ok=True)
        shutil.copy2(_KEYWORDS_PATH, kws_path)


def _rebuild_keywords_file(start_keywords: list[dict], end_keyword_names: list[str]) -> None:
    """用开始词列表 + 结束词 + 命令词重建 keywords.txt。

    start_keywords: [{"name": ..., "pinyin": ...}] — 已编码
    end_keyword_names: ["退出", "取消", ...] — 纯文本，需要编码
    命令词从 config 自动读取。
    """
    from shokztype.core.kws_add_keyword import text_to_kws_line

    config = get_config()
    cmd_keyword_names = list(config.get("wakeup", {}).get("command_keywords", {}).keys())

    all_kws = list(start_keywords)
    existing_names = {kw["name"] for kw in all_kws}
    tokens_path = _get_tokens_path()

    for name in end_keyword_names + cmd_keyword_names:
        if name in existing_names:
            continue
        try:
            line = text_to_kws_line(name, tokens_path)
            m = re.search(r"@(.+)$", line)
            pinyin = line[:m.start()].strip() if m else line
            all_kws.append({"name": name, "pinyin": pinyin})
            existing_names.add(name)
        except Exception as e:
            logger.warning("关键词 '%s' token 编码失败: %s", name, e)

    _write_all_keywords(all_kws)


def _read_start_keywords_with_pinyin() -> list[dict]:
    """读取开始词（排除结束词和命令词），含拼音。"""
    config = get_config()
    end_names = set(config.get("wakeup", {}).get("end_keywords", []))
    cmd_names = set(config.get("wakeup", {}).get("command_keywords", {}).keys())
    exclude = end_names | cmd_names
    return [kw for kw in _read_all_keywords() if kw["name"] not in exclude]


def _read_start_keyword_names() -> list[str]:
    """读取开始词名称列表（排除结束词）。"""
    return [kw["name"] for kw in _read_start_keywords_with_pinyin()]


def _notify_pipeline():
    from shokztype.web.services.event_bus import bus
    bus.emit("config_changed", {"wakeup": {"keywords_file": True}})


def sync_keywords_on_startup() -> None:
    """启动时校验 keywords.txt 与 config 是否一致，不一致则重建。"""
    config = get_config()
    wakeup_cfg = config.get("wakeup", {})
    end_names_cfg = set(wakeup_cfg.get("end_keywords", _DEFAULT_END_KEYWORDS))
    cmd_names_cfg = set(wakeup_cfg.get("command_keywords", {}).keys())
    all_names_file = {kw["name"] for kw in _read_all_keywords()}
    start_names_file = {kw["name"] for kw in _read_start_keywords_with_pinyin()}
    non_start_names_file = all_names_file - start_names_file
    expected_non_start = end_names_cfg | cmd_names_cfg
    if expected_non_start != non_start_names_file:
        logger.info("keywords.txt 与 config 不一致，重建: cfg=%s file=%s", expected_non_start, non_start_names_file)
        try:
            start_kws = _read_start_keywords_with_pinyin()
            _rebuild_keywords_file(start_kws, list(end_names_cfg))
        except Exception as e:
            logger.warning("启动时重建 keywords.txt 失败: %s", e)


# ---------------------------------------------------------------------------
# 基本配置
# ---------------------------------------------------------------------------

_DEFAULT_END_KEYWORDS = ["退出", "结束"]


@router.get("/api/wakeup")
async def read_wakeup() -> dict:
    config = get_config()
    w = config.get("wakeup", {})
    # 兼容旧格式 {"method": "hotkey"} → 新格式 {"methods": [...]}
    methods = w.get("methods") or [w.get("method", "hotkey")]

    end_keywords = w.get("end_keywords")
    if end_keywords is None:
        # 首次：写入默认结束词到 config 和 keywords.txt，并触发 pipeline 重载
        end_keywords = _DEFAULT_END_KEYWORDS
        update_config({"wakeup": {"end_keywords": end_keywords}})
        start_kws = _read_start_keywords_with_pinyin()
        try:
            _rebuild_keywords_file(start_kws, end_keywords)
            logger.info("默认结束词已初始化: %s", end_keywords)
            _notify_pipeline()
        except Exception as e:
            logger.warning("初始化默认结束词失败: %s", e)

    return {
        "methods": methods,
        "hotkey_combo": w.get("hotkey", {}).get("combo", "f9"),
        "start_keywords": _read_start_keyword_names(),
        "end_keywords": end_keywords,
        "undo_hotkey": w.get("undo_hotkey", "ctrl+shift+z"),
        "command_keywords": w.get("command_keywords", {"帮我撤销": "undo"}),
    }


@router.post("/api/wakeup")
async def save_wakeup(request: Request) -> dict:
    body = await request.json()
    methods = body.get("methods") or [body.get("method", "hotkey")]

    if "vad" in methods:
        import importlib.util
        if importlib.util.find_spec("sherpa_onnx") is None:
            return {"success": False, "error": "语音唤醒需要安装 sherpa-onnx 组件，当前环境未安装。可在设置中仅使用热键唤醒。"}

    update_data = {
        "wakeup": {
            "methods": methods,
            "hotkey": {"combo": body.get("hotkey_combo", "f9")},
        }
    }
    end_keywords_changed = False
    if "end_keywords" in body:
        update_data["wakeup"]["end_keywords"] = body["end_keywords"]
        end_keywords_changed = True
    if "undo_hotkey" in body:
        update_data["wakeup"]["undo_hotkey"] = body["undo_hotkey"]

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
    except Exception as e:
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
# 结束关键词
# ---------------------------------------------------------------------------

@router.post("/api/wakeup/add-end-keyword")
async def add_end_keyword(request: Request) -> dict:
    body = await request.json()
    keyword = body.get("keyword", "").strip()
    if not keyword:
        return {"success": False, "error": "结束词不能为空"}

    config = get_config()
    end_keywords = list(config.get("wakeup", {}).get("end_keywords", []))
    if keyword in end_keywords:
        return {"success": False, "error": "该结束词已存在"}

    end_keywords.append(keyword)
    update_config({"wakeup": {"end_keywords": end_keywords}})
    start_kws = _read_start_keywords_with_pinyin()
    _rebuild_keywords_file(start_kws, end_keywords)
    _notify_pipeline()
    return {"success": True, "keyword": keyword}


@router.delete("/api/wakeup/end-keywords/{name}")
async def delete_end_keyword(name: str) -> dict:
    config = get_config()
    end_keywords = [k for k in config.get("wakeup", {}).get("end_keywords", []) if k != name]
    update_config({"wakeup": {"end_keywords": end_keywords}})
    start_kws = _read_start_keywords_with_pinyin()
    _rebuild_keywords_file(start_kws, end_keywords)
    _notify_pipeline()
    return {"success": True}


# ---------------------------------------------------------------------------
# 命令关键词（语音触发撤销等操作）
# ---------------------------------------------------------------------------

@router.post("/api/wakeup/add-command-keyword")
async def add_command_keyword(request: Request) -> dict:
    body = await request.json()
    keyword = body.get("keyword", "").strip()
    action = body.get("action", "undo")
    if not keyword:
        return {"success": False, "error": "命令词不能为空"}

    config = get_config()
    cmd_kws = dict(config.get("wakeup", {}).get("command_keywords", {}))
    if keyword in cmd_kws and cmd_kws[keyword] == action:
        return {"success": False, "error": "该命令词已存在"}

    cmd_kws[keyword] = action
    update_config({"wakeup": {"command_keywords": cmd_kws}})
    start_kws = _read_start_keywords_with_pinyin()
    end_names = config.get("wakeup", {}).get("end_keywords", [])
    _rebuild_keywords_file(start_kws, end_names)
    _notify_pipeline()
    return {"success": True, "keyword": keyword, "action": action}


@router.delete("/api/wakeup/command-keywords/{name}")
async def delete_command_keyword(name: str) -> dict:
    config = get_config()
    cmd_kws = {k: v for k, v in config.get("wakeup", {}).get("command_keywords", {}).items() if k != name}
    update_config({"wakeup": {"command_keywords": cmd_kws}})
    start_kws = _read_start_keywords_with_pinyin()
    end_names = config.get("wakeup", {}).get("end_keywords", [])
    _rebuild_keywords_file(start_kws, end_names)
    _notify_pipeline()
    return {"success": True}


# ---------------------------------------------------------------------------
# 撤销快捷键
# ---------------------------------------------------------------------------

@router.post("/api/wakeup/undo-hotkey")
async def save_undo_hotkey(request: Request) -> dict:
    body = await request.json()
    combo = body.get("combo", "").strip()
    if not combo:
        return {"success": False, "error": "快捷键不能为空"}

    update_config({"wakeup": {"undo_hotkey": combo}})

    from shokztype.web.services import recording_pipeline
    recording_pipeline.restart_undo_hotkey(combo)
    return {"success": True, "combo": combo}


# ---------------------------------------------------------------------------
# 热键录制（通过 PersistentKeyListener 的 hooks 机制）
# ---------------------------------------------------------------------------

from pynput.keyboard import Key as _Key

_CTRL_KEYS = frozenset({_Key.ctrl, _Key.ctrl_l, _Key.ctrl_r})
_ALT_KEYS = frozenset({_Key.alt, _Key.alt_l, _Key.alt_r})
_SHIFT_KEYS = frozenset({_Key.shift, _Key.shift_l, _Key.shift_r})


@router.post("/api/wakeup/record-hotkey")
async def record_hotkey() -> dict:
    pkl = PersistentKeyListener.get()
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    active_modifiers: set = set()

    def on_press(key):
        if key in MODIFIER_KEYS:
            active_modifiers.add(key)
            return

        parts = []
        if active_modifiers & _CTRL_KEYS:
            parts.append("Ctrl")
        if active_modifiers & _ALT_KEYS:
            parts.append("Alt")
        if active_modifiers & _SHIFT_KEYS:
            parts.append("Shift")

        if hasattr(key, 'char') and key.char:
            key_name = key.char.upper()
        elif hasattr(key, 'name'):
            key_name = key.name
        else:
            key_name = str(key)
        parts.append(key_name)
        combo = "+".join(parts)

        pkl.clear_hooks()
        if not future.done():
            loop.call_soon_threadsafe(future.set_result, combo)

    def on_release(key):
        active_modifiers.discard(key)

    pkl.set_hooks(on_press, on_release)

    try:
        combo = await asyncio.wait_for(future, timeout=10)
        return {"success": True, "combo": combo}
    except asyncio.TimeoutError:
        pkl.clear_hooks()
        return {"success": False, "error": "超时：10秒内未检测到按键"}
