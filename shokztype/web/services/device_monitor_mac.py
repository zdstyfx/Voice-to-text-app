"""macOS audio device monitoring via Core Audio property listener (event-driven)."""

import asyncio
import ctypes
import ctypes.util
import logging
import struct
from typing import Optional

logger = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None
_on_change = None
_listener_installed = False

# Core Audio constants
kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = int.from_bytes(b'dev#', 'big')
kAudioObjectPropertyScopeGlobal = int.from_bytes(b'glob', 'big')
kAudioObjectPropertyElementMain = 0

# Load CoreAudio framework
_ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreAudio'))


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ('mSelector', ctypes.c_uint32),
        ('mScope', ctypes.c_uint32),
        ('mElement', ctypes.c_uint32),
    ]


# typedef OSStatus (*AudioObjectPropertyListenerProc)(
#     AudioObjectID, UInt32, const AudioObjectPropertyAddress*, void*)
_ListenerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32,      # OSStatus return
    ctypes.c_uint32,     # AudioObjectID
    ctypes.c_uint32,     # numberAddresses
    ctypes.POINTER(AudioObjectPropertyAddress),
    ctypes.c_void_p,     # clientData
)

_ca.AudioObjectAddPropertyListener.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(AudioObjectPropertyAddress),
    _ListenerProc,
    ctypes.c_void_p,
]
_ca.AudioObjectAddPropertyListener.restype = ctypes.c_int32

_ca.AudioObjectRemovePropertyListener.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(AudioObjectPropertyAddress),
    _ListenerProc,
    ctypes.c_void_p,
]
_ca.AudioObjectRemovePropertyListener.restype = ctypes.c_int32

# prevent GC of the callback
_callback_ref = None


def _on_devices_changed(obj_id, num_addr, addresses, client_data):
    if _loop is not None and _on_change is not None:
        _loop.call_soon_threadsafe(asyncio.ensure_future, _on_change())
    return 0


def start_listening(loop: asyncio.AbstractEventLoop, on_change) -> None:
    global _loop, _on_change, _listener_installed, _callback_ref

    _loop = loop
    _on_change = on_change

    prop = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDevices,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )

    _callback_ref = _ListenerProc(_on_devices_changed)

    status = _ca.AudioObjectAddPropertyListener(
        kAudioObjectSystemObject,
        ctypes.byref(prop),
        _callback_ref,
        None,
    )

    if status == 0:
        _listener_installed = True
        logger.info("macOS Core Audio 设备监听已启动 (事件驱动)")
    else:
        logger.error("AudioObjectAddPropertyListener 失败: %d", status)


def stop_listening() -> None:
    global _listener_installed

    if not _listener_installed:
        return

    prop = AudioObjectPropertyAddress(
        kAudioHardwarePropertyDevices,
        kAudioObjectPropertyScopeGlobal,
        kAudioObjectPropertyElementMain,
    )

    _ca.AudioObjectRemovePropertyListener(
        kAudioObjectSystemObject,
        ctypes.byref(prop),
        _callback_ref,
        None,
    )
    _listener_installed = False
    logger.info("macOS Core Audio 设备监听已停止")
