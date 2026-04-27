"""OpenAI 兼容 LLM 客户端。"""

import httpx
from typing import Any


async def call_llm(config: dict[str, Any], prompt: str) -> dict[str, Any]:
    """调用 OpenAI 兼容 API。

    Args:
        config: llm 配置块 {"apiBaseUrl", "apiKey", "model", "timeoutSeconds", "temperature"}
        prompt: 渲染后的完整 prompt

    Returns:
        {"success": bool, "text": str, "error": str | None}
    """
    base_url = config.get("apiBaseUrl", "").rstrip("/")
    api_key = config.get("apiKey", "")
    model = config.get("model", "")
    timeout = config.get("timeoutSeconds", 90)
    temperature = config.get("temperature", 0.2)

    if not base_url or not api_key or not model:
        return {"success": False, "text": "", "error": "LLM 配置不完整（缺少 apiBaseUrl/apiKey/model）"}

    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "enable_thinking": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            return {"success": True, "text": text, "error": None}
    except httpx.TimeoutException:
        return {"success": False, "text": "", "error": f"LLM 请求超时（{timeout}s）"}
    except httpx.HTTPStatusError as e:
        return {"success": False, "text": "", "error": f"LLM HTTP 错误: {e.response.status_code}"}
    except Exception as e:
        return {"success": False, "text": "", "error": f"LLM 调用失败: {e}"}
