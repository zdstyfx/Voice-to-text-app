"""设备变化监听 + SSE 广播。使用 sounddevice 真实枚举。"""

import asyncio
import json
from typing import Any

import sounddevice as sd

_clients: list[asyncio.Queue] = []


def list_devices() -> list[dict[str, Any]]:
    """列出所有可用的音频输入设备。"""
    devices = sd.query_devices()
    default_input = sd.default.device[0]
    result = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            result.append({
                "id": str(i),
                "name": dev["name"],
                "is_default": i == default_input,
            })
    return result


async def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _clients.append(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    if queue in _clients:
        _clients.remove(queue)


async def broadcast(data: dict[str, Any]) -> None:
    message = json.dumps(data, ensure_ascii=False)
    for queue in list(_clients):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            pass


async def poll_device_changes(interval: float = 2.0) -> None:
    prev = None
    while True:
        try:
            current = list_devices()
            current_ids = {d["id"] for d in current}
            if prev is not None and current_ids != prev:
                await broadcast({"event": "devices_changed", "devices": current})
            prev = current_ids
        except Exception:
            pass
        await asyncio.sleep(interval)
