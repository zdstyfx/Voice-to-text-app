"""文本处理管线：模式路由 + Prompt 渲染 + LLM 调用。"""

import time
from typing import Any

from shokztype.web.services.llm_client import call_llm


async def process_text(text: str, config: dict[str, Any], mode: str | None = None) -> dict[str, Any]:
    """根据当前模式处理文本。"""
    mode = mode or config.get("currentMode", "transcribe")
    start = time.monotonic()

    if mode == "transcribe":
        elapsed = int((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "processed_text": text,
            "mode": mode,
            "used_llm": False,
            "duration_ms": elapsed,
            "fell_back_to_transcribe": False,
        }

    prompts = config.get("prompts", {})
    template = prompts.get(mode, "{text}")
    target_language = config.get("translateTargetLanguage", "英语")
    rendered = template.replace("{text}", text).replace("{targetLanguage}", target_language)

    llm_config = config.get("llm", {})
    result = await call_llm(llm_config, rendered)
    elapsed = int((time.monotonic() - start) * 1000)

    if result["success"]:
        return {
            "success": True,
            "processed_text": result["text"],
            "mode": mode,
            "used_llm": True,
            "duration_ms": elapsed,
            "fell_back_to_transcribe": False,
        }

    return {
        "success": True,
        "processed_text": text,
        "mode": mode,
        "used_llm": False,
        "duration_ms": elapsed,
        "fell_back_to_transcribe": True,
        "error": result["error"],
    }
