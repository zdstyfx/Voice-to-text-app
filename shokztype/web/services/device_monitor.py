"""设备变化监听 + SSE 广播 — 跨平台调度。

Windows: COM IMMNotificationClient 事件驱动
macOS: sounddevice 轮询
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

import sounddevice as sd

from shokztype.core.platform import IS_WINDOWS, IS_MACOS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE 订阅
# ---------------------------------------------------------------------------

_clients: list[asyncio.Queue] = []


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

# ---------------------------------------------------------------------------
# 回调：由 recording_pipeline 注册
# ---------------------------------------------------------------------------

_get_active_device: Optional[Callable[[], Optional[str]]] = None
_get_preferred_device: Optional[Callable[[], Optional[str]]] = None
_on_device_switch: Optional[Callable[[str, list[dict[str, Any]]], None]] = None
_on_portaudio_refresh: Optional[Callable[[], None]] = None


def register_get_active_device(cb: Callable[[], Optional[str]]) -> None:
    global _get_active_device
    _get_active_device = cb


def register_get_preferred_device(cb: Callable[[], Optional[str]]) -> None:
    global _get_preferred_device
    _get_preferred_device = cb


def register_on_portaudio_refresh(cb: Callable[[], None]) -> None:
    global _on_portaudio_refresh
    _on_portaudio_refresh = cb


def register_on_device_switch(cb: Callable[[str, list[dict[str, Any]]], None]) -> None:
    global _on_device_switch
    _on_device_switch = cb

# ---------------------------------------------------------------------------
# 设备枚举
# ---------------------------------------------------------------------------

def _refresh_portaudio() -> None:
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def _get_ep_map() -> dict[str, str]:
    """获取 endpoint_id 映射（仅 Windows 有 COM 枚举，macOS 返回空）。"""
    if IS_WINDOWS:
        from shokztype.web.services.device_monitor_win import com_enumerate_endpoints
        return com_enumerate_endpoints()
    return {}


def list_devices() -> list[dict[str, Any]]:
    """列出所有可用的音频输入设备。"""
    devices = sd.query_devices()
    default_input = sd.default.device[0]

    ep_map = _get_ep_map()
    eid_to_name = {eid: name for name, eid in ep_map.items()}

    result = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            name = dev["name"]

            if ep_map:
                endpoint_id = ep_map.get(name, "")
                if not endpoint_id:
                    for ep_name, eid in ep_map.items():
                        if ep_name.startswith(name) or name.startswith(ep_name):
                            endpoint_id = eid
                            break
                if endpoint_id:
                    full_name = eid_to_name.get(endpoint_id, name)
                    result.append({
                        "id": str(i),
                        "name": full_name,
                        "endpoint_id": endpoint_id,
                        "is_default": i == default_input,
                    })
            else:
                result.append({
                    "id": str(i),
                    "name": name,
                    "endpoint_id": str(i),
                    "is_default": i == default_input,
                })

    if ep_map:
        seen: dict[str, dict] = {}
        for d in result:
            eid = d["endpoint_id"]
            if eid not in seen or d["is_default"]:
                seen[eid] = d
        return list(seen.values())

    return result

# ---------------------------------------------------------------------------
# 设备变化处理（在事件循环线程执行）
# ---------------------------------------------------------------------------

_prev_device_ids: set[str] | None = None


async def _handle_device_change() -> None:
    global _prev_device_ids

    try:
        _refresh_portaudio()
        if _on_portaudio_refresh:
            _on_portaudio_refresh()
        current = list_devices()
        current_ids = {d["id"] for d in current}

        if _prev_device_ids is None:
            _prev_device_ids = current_ids
            return

        if current_ids == _prev_device_ids:
            return

        _prev_device_ids = current_ids

        if not current:
            await broadcast({"event": "devices_changed", "devices": current})
            return

        active_id = _get_active_device() if _get_active_device else None
        preferred_eid = _get_preferred_device() if _get_preferred_device else None
        active_lost = active_id is not None and active_id not in current_ids
        preferred_match = next(
            (d for d in current if d.get("endpoint_id") == preferred_eid), None,
        ) if preferred_eid else None
        preferred_available = (
            preferred_match is not None
            and preferred_match["id"] != active_id
        )

        if active_lost and _on_device_switch:
            if preferred_match:
                target = preferred_match
                reason = "preferred_fallback"
            else:
                target = next(
                    (d for d in current if d["is_default"]),
                    current[0],
                )
                reason = "device_lost"
            logger.warning(
                "活跃设备 #%s 已断开，切换到 #%s (%s) [%s]",
                active_id, target["id"], target["name"], reason,
            )
            _on_device_switch(target["id"], current)
            await broadcast({
                "event": "device_switched",
                "new_device": target,
                "devices": current,
                "reason": reason,
            })
        elif preferred_available and _on_device_switch:
            target = preferred_match
            logger.info(
                "偏好设备 #%s (%s) 已重新连接，自动切回",
                target["id"], target["name"],
            )
            _on_device_switch(target["id"], current)
            await broadcast({
                "event": "device_switched",
                "new_device": target,
                "devices": current,
                "reason": "preferred_reconnected",
            })
        else:
            await broadcast({"event": "devices_changed", "devices": current})
    except Exception:
        logger.exception("处理设备变化事件失败")

# ---------------------------------------------------------------------------
# 平台调度：启动/停止监听
# ---------------------------------------------------------------------------


def start_listening(loop: asyncio.AbstractEventLoop) -> None:
    global _prev_device_ids
    try:
        devices = list_devices()
        _prev_device_ids = {d["id"] for d in devices}
    except Exception:
        pass

    if IS_WINDOWS:
        from shokztype.web.services.device_monitor_win import start_listening as _start
        _start(loop, _handle_device_change)
    elif IS_MACOS:
        from shokztype.web.services.device_monitor_mac import start_listening as _start
        _start(loop, _handle_device_change)
    else:
        logger.warning("不支持的平台，设备监控已禁用")


def stop_listening() -> None:
    if IS_WINDOWS:
        from shokztype.web.services.device_monitor_win import stop_listening as _stop
        _stop()
    elif IS_MACOS:
        from shokztype.web.services.device_monitor_mac import stop_listening as _stop
        _stop()
