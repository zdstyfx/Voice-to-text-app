"""Windows COM-based audio device monitoring (IMMNotificationClient)."""

import asyncio
import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Optional

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


def com_enumerate_endpoints() -> dict[str, str]:
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


# ---------------------------------------------------------------------------
# COM 事件监听（后台线程）
# ---------------------------------------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_enumerator = None
_notification_client = None
_listener_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


class _NotificationClient(COMObject):
    _com_interfaces_ = [IMMNotificationClient]

    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change

    def _schedule(self) -> None:
        if _loop is not None:
            _loop.call_soon_threadsafe(asyncio.ensure_future, self._on_change())

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
        return 0


def start_listening(loop: asyncio.AbstractEventLoop, on_change) -> None:
    global _loop, _listener_thread, _stop_event

    _loop = loop
    _stop_event.clear()

    def _listener_main():
        global _enumerator, _notification_client
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            _enumerator = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                interface=IMMDeviceEnumerator,
                clsctx=comtypes.CLSCTX_INPROC_SERVER,
            )
            _notification_client = _NotificationClient(on_change)
            _enumerator.RegisterEndpointNotificationCallback(_notification_client)
            logger.info("Windows 音频设备监听已启动 (IMMNotificationClient)")
            _stop_event.wait()
            _enumerator.UnregisterEndpointNotificationCallback(_notification_client)
            logger.info("Windows 音频设备监听已停止")
        except Exception:
            logger.exception("COM 设备监听线程异常")
        finally:
            comtypes.CoUninitialize()

    _listener_thread = threading.Thread(
        target=_listener_main, daemon=True, name="DeviceMonitorCOM",
    )
    _listener_thread.start()


def stop_listening() -> None:
    _stop_event.set()
    if _listener_thread is not None:
        _listener_thread.join(timeout=3)
