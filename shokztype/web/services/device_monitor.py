"""设备变化监听 + SSE 广播。

使用 Windows Core Audio COM 接口 (IMMNotificationClient) 实现事件驱动的
设备变化检测，取代轮询。设备增删、状态变化、默认设备切换均会触发回调。
"""

import asyncio
import ctypes
import json
import logging
import threading
from ctypes import wintypes
from typing import Any, Callable, Optional

import comtypes
from comtypes import GUID, HRESULT, COMMETHOD, COMObject, IUnknown
import sounddevice as sd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows Core Audio COM 接口定义
# ---------------------------------------------------------------------------

class IMMNotificationClient(IUnknown):
    _iid_ = GUID('{7991EEC9-7E89-4D85-8390-6C703CEC60C0}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'OnDeviceStateChanged',
                  (['in'], wintypes.LPCWSTR, 'pwstrDeviceId'),
                  (['in'], wintypes.DWORD, 'dwNewState')),
        COMMETHOD([], HRESULT, 'OnDeviceAdded',
                  (['in'], wintypes.LPCWSTR, 'pwstrDeviceId')),
        COMMETHOD([], HRESULT, 'OnDeviceRemoved',
                  (['in'], wintypes.LPCWSTR, 'pwstrDeviceId')),
        COMMETHOD([], HRESULT, 'OnDefaultDeviceChanged',
                  (['in'], wintypes.DWORD, 'flow'),
                  (['in'], wintypes.DWORD, 'role'),
                  (['in'], wintypes.LPCWSTR, 'pwstrDefaultDeviceId')),
        COMMETHOD([], HRESULT, 'OnPropertyValueChanged',
                  (['in'], wintypes.LPCWSTR, 'pwstrDeviceId'),
                  (['in'], ctypes.c_byte * 20, 'key')),
    ]


class IPropertyStore(IUnknown):
    _iid_ = GUID('{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}')


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ('vt', wintypes.USHORT),
        ('reserved1', wintypes.USHORT),
        ('reserved2', wintypes.USHORT),
        ('reserved3', wintypes.USHORT),
        ('pwszVal', wintypes.LPWSTR),
        ('padding', ctypes.c_byte * 8),
    ]


IPropertyStore._methods_ = [
    COMMETHOD([], HRESULT, 'GetCount', (['out'], ctypes.POINTER(wintypes.DWORD), 'cProps')),
    COMMETHOD([], HRESULT, 'GetAt', (['in'], wintypes.DWORD, 'iProp'), (['out'], ctypes.POINTER(PROPERTYKEY), 'pkey')),
    COMMETHOD([], HRESULT, 'GetValue', (['in'], ctypes.POINTER(PROPERTYKEY), 'key'), (['out'], ctypes.POINTER(PROPVARIANT), 'pv')),
]

PKEY_Device_FriendlyName = PROPERTYKEY(GUID('{a45c254e-df1c-4efd-8020-67d146a850e0}'), 14)


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID('{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'GetCount', (['out'], ctypes.POINTER(wintypes.UINT), 'pcDevices')),
        COMMETHOD([], HRESULT, 'Item', (['in'], wintypes.UINT, 'nDevice'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IUnknown)), 'ppDevice')),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'Activate',
                  (['in'], ctypes.POINTER(GUID), 'iid'),
                  (['in'], wintypes.DWORD, 'dwClsCtx'),
                  (['in'], ctypes.c_void_p, 'pActivationParams'),
                  (['out'], ctypes.POINTER(ctypes.c_void_p), 'ppInterface')),
        COMMETHOD([], HRESULT, 'OpenPropertyStore',
                  (['in'], wintypes.DWORD, 'stgmAccess'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IPropertyStore)), 'ppProperties')),
        COMMETHOD([], HRESULT, 'GetId',
                  (['out'], ctypes.POINTER(wintypes.LPWSTR), 'ppstrId')),
        COMMETHOD([], HRESULT, 'GetState',
                  (['out'], ctypes.POINTER(wintypes.DWORD), 'pdwState')),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'EnumAudioEndpoints',
                  (['in'], wintypes.DWORD, 'dataFlow'),
                  (['in'], wintypes.DWORD, 'dwStateMask'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)), 'ppDevices')),
        COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint',
                  (['in'], wintypes.DWORD, 'dataFlow'),
                  (['in'], wintypes.DWORD, 'role'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDevice)), 'ppEndpoint')),
        COMMETHOD([], HRESULT, 'GetDevice',
                  (['in'], wintypes.LPCWSTR, 'pwstrId'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDevice)), 'ppDevice')),
        COMMETHOD([], HRESULT, 'RegisterEndpointNotificationCallback',
                  (['in'], ctypes.POINTER(IMMNotificationClient), 'pClient')),
        COMMETHOD([], HRESULT, 'UnregisterEndpointNotificationCallback',
                  (['in'], ctypes.POINTER(IMMNotificationClient), 'pClient')),
    ]


CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
_ECAPTURE = 1
_DEVICE_STATE_ACTIVE = 0x00000001
_STGM_READ = 0

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
    """重新初始化 PortAudio 以刷新设备列表。

    注意：Pa_Terminate 会销毁所有活跃的 PortAudio 流。
    仅在设备变化事件时调用，调用后需要重建 AudioCapture 流。
    """
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def _com_enumerate_endpoints() -> dict[str, str]:
    """通过 COM 枚举活跃的输入端点，返回 {name: endpoint_id}。"""
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        collection = enum.EnumAudioEndpoints(_ECAPTURE, _DEVICE_STATE_ACTIVE)
        count = collection.GetCount()
        result = {}
        for i in range(count):
            device = collection.Item(i).QueryInterface(IMMDevice)
            eid = device.GetId()
            props = device.OpenPropertyStore(_STGM_READ)
            pv = props.GetValue(ctypes.byref(PKEY_Device_FriendlyName))
            name = pv.pwszVal if pv.vt == 31 else ""
            if name and eid:
                result[name] = eid
        return result
    except Exception as e:
        logger.debug("COM 枚举端点失败: %s", e)
        return {}


def list_devices() -> list[dict[str, Any]]:
    """列出所有可用的音频输入设备，包含 endpoint_id。"""
    devices = sd.query_devices()
    default_input = sd.default.device[0]

    # COM 枚举拿 endpoint_id + 完整名称，按名称前缀匹配 sounddevice 的设备
    ep_map = _com_enumerate_endpoints()  # {com_name: endpoint_id}
    # 反向映射：endpoint_id → com_name（完整名称）
    eid_to_name = {eid: name for name, eid in ep_map.items()}

    result = []
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            name = dev["name"]
            # sounddevice 名称可能被截断，用前缀匹配
            endpoint_id = ep_map.get(name, "")
            if not endpoint_id:
                for ep_name, eid in ep_map.items():
                    if ep_name.startswith(name) or name.startswith(ep_name):
                        endpoint_id = eid
                        break
            if endpoint_id:
                # 用 COM 的完整名称替换 sounddevice 可能截断的名称
                full_name = eid_to_name.get(endpoint_id, name)
                result.append({
                    "id": str(i),
                    "name": full_name,
                    "endpoint_id": endpoint_id,
                    "is_default": i == default_input,
                })

    # 按 endpoint_id 去重，同一物理设备只保留一个（优先保留 is_default 的）
    seen: dict[str, dict] = {}
    for d in result:
        eid = d["endpoint_id"]
        if eid not in seen or d["is_default"]:
            seen[eid] = d
    return list(seen.values())

# ---------------------------------------------------------------------------
# 设备变化处理（在事件循环线程执行）
# ---------------------------------------------------------------------------

_prev_device_ids: set[str] | None = None


async def _handle_device_change() -> None:
    """COM 回调触发后，在事件循环中执行设备变化处理。"""
    global _prev_device_ids

    try:
        # COM 事件触发 → 刷新 PortAudio 设备列表
        _refresh_portaudio()
        if _on_portaudio_refresh:
            _on_portaudio_refresh()
        current = list_devices()
        current_ids = {d["id"] for d in current}

        # 首次初始化，仅记录
        if _prev_device_ids is None:
            _prev_device_ids = current_ids
            return

        # 设备列表无实际变化（属性变更等噪声事件）
        if current_ids == _prev_device_ids:
            return

        _prev_device_ids = current_ids

        if not current:
            await broadcast({"event": "devices_changed", "devices": current})
            return

        active_id = _get_active_device() if _get_active_device else None
        # preferred 返回的是 endpoint_id（稳定标识）
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
# COM 事件监听（后台线程）
# ---------------------------------------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_enumerator = None
_notification_client = None
_listener_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


class _NotificationClient(COMObject):
    """IMMNotificationClient 实现，将 COM 回调桥接到 asyncio 事件循环。"""
    _com_interfaces_ = [IMMNotificationClient]

    def _schedule(self) -> None:
        if _loop is not None:
            _loop.call_soon_threadsafe(asyncio.ensure_future, _handle_device_change())

    def OnDeviceStateChanged(self, pwstrDeviceId, dwNewState):
        logger.debug("COM: DeviceStateChanged %s state=%s", pwstrDeviceId, dwNewState)
        self._schedule()
        return 0

    def OnDeviceAdded(self, pwstrDeviceId):
        logger.debug("COM: DeviceAdded %s", pwstrDeviceId)
        self._schedule()
        return 0

    def OnDeviceRemoved(self, pwstrDeviceId):
        logger.debug("COM: DeviceRemoved %s", pwstrDeviceId)
        self._schedule()
        return 0

    def OnDefaultDeviceChanged(self, flow, role, pwstrDefaultDeviceId):
        logger.debug("COM: DefaultDeviceChanged flow=%s role=%s id=%s", flow, role, pwstrDefaultDeviceId)
        self._schedule()
        return 0

    def OnPropertyValueChanged(self, pwstrDeviceId, key):
        # 属性变化频繁且通常无关，忽略
        return 0


def _listener_main() -> None:
    """COM 监听线程入口。"""
    global _enumerator, _notification_client

    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    try:
        _enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator,
            interface=IMMDeviceEnumerator,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        _notification_client = _NotificationClient()
        _enumerator.RegisterEndpointNotificationCallback(_notification_client)
        logger.info("Windows 音频设备监听已启动 (IMMNotificationClient)")

        # 初始化设备列表快照
        global _prev_device_ids
        try:
            devices = list_devices()
            _prev_device_ids = {d["id"] for d in devices}
        except Exception:
            pass

        # 保持线程存活，等待停止信号
        _stop_event.wait()

        _enumerator.UnregisterEndpointNotificationCallback(_notification_client)
        logger.info("Windows 音频设备监听已停止")
    except Exception:
        logger.exception("COM 设备监听线程异常")
    finally:
        comtypes.CoUninitialize()


def start_listening(loop: asyncio.AbstractEventLoop) -> None:
    """启动设备变化监听（后台线程）。"""
    global _loop, _listener_thread, _stop_event

    _loop = loop
    _stop_event.clear()
    _listener_thread = threading.Thread(
        target=_listener_main, daemon=True, name="DeviceMonitorCOM",
    )
    _listener_thread.start()


def stop_listening() -> None:
    """停止设备变化监听。"""
    _stop_event.set()
    if _listener_thread is not None:
        _listener_thread.join(timeout=3)
