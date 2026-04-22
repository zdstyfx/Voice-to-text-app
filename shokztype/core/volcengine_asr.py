"""VolcEngineASR — 火山引擎 Seed ASR 流式语音识别大模型封装。

协议文档: https://www.volcengine.com/docs/6561/1354869
WebSocket 二进制帧协议，双向流式模式。
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import struct
import threading
import time
import uuid
import wave
from queue import Empty, Queue
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 协议常量
# ---------------------------------------------------------------------------

_DEFAULT_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# Header byte 0: version(4bit) | header_size(4bit)
_PROTOCOL_VERSION = 0x1
_HEADER_SIZE_WORDS = 0x1  # 1 word = 4 bytes

# Message types (byte 1 high nibble)
_MSG_FULL_CLIENT_REQUEST = 0x1
_MSG_AUDIO_ONLY = 0x2
_MSG_FULL_SERVER_RESPONSE = 0x9
_MSG_ERROR = 0xF

# Message type flags (byte 1 low nibble)
_FLAG_NONE = 0x0
_FLAG_LAST_PACKET = 0x2  # 负包，标识最后一包

# Serialization (byte 2 high nibble)
_SERIAL_NONE = 0x0
_SERIAL_JSON = 0x1

# Compression (byte 2 low nibble)
_COMPRESS_NONE = 0x0
_COMPRESS_GZIP = 0x1

# 最优音频分包：200ms @ 16kHz 16bit mono = 6400 bytes
_CHUNK_BYTES = 6400
_CHUNK_DURATION_MS = 200

# 队列哨兵
_SENTINEL = None


def _build_header(
    msg_type: int,
    flags: int = _FLAG_NONE,
    serial: int = _SERIAL_JSON,
    compress: int = _COMPRESS_NONE,
) -> bytes:
    """构造 4 字节协议头。"""
    byte0 = (_PROTOCOL_VERSION << 4) | _HEADER_SIZE_WORDS
    byte1 = (msg_type << 4) | flags
    byte2 = (serial << 4) | compress
    byte3 = 0x00
    return bytes([byte0, byte1, byte2, byte3])


def _build_full_client_request(payload_dict: dict, sequence: int = 1) -> bytes:
    """构造 full client request 二进制帧（JSON + Gzip，带 sequence）。"""
    header = _build_header(_MSG_FULL_CLIENT_REQUEST, 0x01, _SERIAL_JSON, _COMPRESS_GZIP)
    payload = gzip.compress(json.dumps(payload_dict, ensure_ascii=False).encode("utf-8"))
    pkt = bytearray(header)
    pkt.extend(struct.pack(">i", sequence))
    pkt.extend(struct.pack(">I", len(payload)))
    pkt.extend(payload)
    return bytes(pkt)


def _build_audio_frame(pcm_bytes: bytes, is_last: bool = False) -> bytes:
    """构造 audio only request 二进制帧（Gzip 压缩）。"""
    flags = _FLAG_LAST_PACKET if is_last else _FLAG_NONE
    header = _build_header(_MSG_AUDIO_ONLY, flags, _SERIAL_JSON, _COMPRESS_GZIP)
    compressed = gzip.compress(pcm_bytes)
    pkt = bytearray(header)
    pkt.extend(struct.pack(">I", len(compressed)))
    pkt.extend(compressed)
    return bytes(pkt)


def _parse_response(data: bytes) -> dict:
    """解析服务端返回的二进制帧。

    使用与 type4me 参考实现相同的通用解析逻辑：
    根据 header flags 判断是否有 sequence number，再读 payload。
    """
    if len(data) < 4:
        raise ValueError(f"响应数据过短: {len(data)} bytes")

    header_size = data[0] & 0x0F
    msg_type = (data[1] >> 4) & 0xF
    flags = data[1] & 0xF
    compression = data[2] & 0xF

    payload = data[header_size * 4:]
    result: dict = {"is_last": bool(flags & 0x02), "msg_type": msg_type}

    # flags bit-0 表示有 sequence number
    if flags & 0x01:
        result["_sequence"] = int.from_bytes(payload[:4], "big", signed=True)
        payload = payload[4:]

    if msg_type == _MSG_FULL_SERVER_RESPONSE:
        size = int.from_bytes(payload[:4], "big")
        payload_bytes = payload[4:4 + size]
        if compression == _COMPRESS_GZIP:
            payload_bytes = gzip.decompress(payload_bytes)
        result.update(json.loads(payload_bytes.decode("utf-8")))

    elif msg_type == _MSG_ERROR:
        code = int.from_bytes(payload[:4], "big")
        size = int.from_bytes(payload[4:8], "big")
        err_bytes = payload[8:8 + size]
        if compression == _COMPRESS_GZIP:
            err_bytes = gzip.decompress(err_bytes)
        result["error"] = True
        result["code"] = code
        result["message"] = err_bytes.decode("utf-8", errors="replace")

    return result


class VolcEngineASR:
    """火山引擎 Seed ASR 流式语音识别大模型。

    提供与 CloudASR (DashScope) 相同的接口：
      - transcribe_file(wav_path) → dict
      - start_streaming(on_partial, on_sentence)
      - send_frame(pcm_bytes)
      - stop_streaming()
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        # 凭证优先从 asr.volcengine 读取，其次 cloud_asr.volcengine
        volc_cfg = config.get("asr", {}).get("volcengine", {})
        cloud_volc_cfg = config.get("cloud_asr", {}).get("volcengine", {})

        self._api_key = str(volc_cfg.get("api_key", "") or cloud_volc_cfg.get("api_key", ""))
        if not self._api_key:
            raise ValueError(
                "火山引擎 API Key 未配置。"
                "请在 config.json 的 asr.volcengine.api_key 中设置。"
            )
        self._model_id = str(
            volc_cfg.get("model_id", "")
            or cloud_volc_cfg.get("model_id", "")
        )
        self._ws_url = (
            volc_cfg.get("ws_url")
            or cloud_volc_cfg.get("ws_url")
            or _DEFAULT_WS_URL
        )
        self._resource_id = str(
            volc_cfg.get("resource_id", "")
            or cloud_volc_cfg.get("resource_id", "")
            or "volc.bigasr.sauc.duration"
        )
        cloud_cfg = config.get("cloud_asr", {})
        self._sample_rate = cloud_cfg.get("sample_rate", 16000)
        self._format = cloud_cfg.get("format", "pcm")

        # 流式状态
        self._audio_queue: Optional[Queue] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_ready = threading.Event()
        self._stream_error: Optional[Exception] = None

        logger.info("VolcEngineASR 初始化完成，endpoint: %s", self._ws_url)

    def _make_request_payload(self) -> dict:
        """构建 full client request 的 JSON payload。"""
        return {
            "user": {
                "uid": str(uuid.uuid4()),
            },
            "audio": {
                "format": self._format,
                "rate": self._sample_rate,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
                "result_type": "full",
            },
        }

    # ------------------------------------------------------------------
    # 文件转写（通过流式 WebSocket 模拟）
    # ------------------------------------------------------------------

    def transcribe_file(self, wav_path: str) -> Dict[str, Any]:
        """同步识别音频文件，返回与 CloudASR.transcribe_file() 相同格式的字典。"""
        start = time.time()
        try:
            result = asyncio.run(self._transcribe_file_async(wav_path))
        except Exception as e:
            logger.error("VolcEngine ASR 调用失败: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            duration = time.time() - start

        if result.get("error"):
            error_msg = result.get("message", str(result))
            logger.error("VolcEngine ASR 返回错误: %s", error_msg)
            return {"success": False, "error": error_msg}

        full_text = self._extract_text(result)
        logger.info("VolcEngine ASR 完成，文本长度: %d, 耗时: %.2fs", len(full_text), duration)
        return {
            "success": True,
            "text": full_text,
            "raw_text": full_text,
            "confidence": 0.95,
            "duration": duration,
        }

    async def _transcribe_file_async(self, wav_path: str) -> dict:
        """异步读取 WAV 文件并通过 WebSocket 流式发送。"""
        import websockets

        pcm_data = self._read_wav_pcm(wav_path)
        full_text = ""

        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        async with websockets.connect(
            self._ws_url, additional_headers=headers,
            open_timeout=15, close_timeout=10,
        ) as ws:
            # 1) 发送 full client request
            await ws.send(_build_full_client_request(self._make_request_payload()))

            # 2) 接收 init 确认
            raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            init_resp = _parse_response(raw)
            if init_resp.get("error"):
                return init_resp

            # 3) 并发发送音频 + 接收结果
            async def _send_audio():
                offset = 0
                total = len(pcm_data)
                while offset < total:
                    chunk_end = min(offset + _CHUNK_BYTES, total)
                    is_last = (chunk_end >= total)
                    await ws.send(_build_audio_frame(pcm_data[offset:chunk_end], is_last=is_last))
                    offset = chunk_end

            send_task = asyncio.create_task(_send_audio())

            try:
                async for msg in ws:
                    resp = _parse_response(msg)
                    if resp.get("error"):
                        await send_task
                        return resp
                    text = resp.get("result", {}).get("text", "")
                    if text:
                        full_text = text
                    if resp.get("is_last"):
                        break
            except Exception:
                pass

            await send_task

        return {"result": {"text": full_text}}

    @staticmethod
    def _read_wav_pcm(wav_path: str) -> bytes:
        """读取 WAV 文件并返回 PCM 数据（跳过 WAV 头）。"""
        with wave.open(wav_path, "rb") as wf:
            return wf.readframes(wf.getnframes())

    @staticmethod
    def _extract_text(result: dict) -> str:
        """从服务端响应中提取识别文本。"""
        res = result.get("result", {})
        if isinstance(res, dict):
            return res.get("text", "")
        if isinstance(res, list) and res:
            return res[0].get("text", "")
        return ""

    # ------------------------------------------------------------------
    # 流式 API
    # ------------------------------------------------------------------

    def start_streaming(
        self,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        """建立 WebSocket 连接，开始流式识别。旧连接若未关完则放任其自行结束。"""
        if self._stream_thread and self._stream_thread.is_alive():
            logger.info("旧流式连接仍在关闭中，不等待，直接建立新连接")
            # 不调用 stop_streaming()，旧线程是 daemon 会自行结束

        self._audio_queue = Queue()
        self._stream_ready.clear()
        self._stream_error = None

        self._stream_thread = threading.Thread(
            target=self._streaming_thread_entry,
            args=(on_partial, on_sentence),
            daemon=True,
            name="VolcEngineASR-Stream",
        )
        self._stream_thread.start()

        # 等待 WebSocket 连接建立
        if not self._stream_ready.wait(timeout=10.0):
            err = self._stream_error or RuntimeError("WebSocket 连接超时")
            self._stream_thread = None
            raise err

        if self._stream_error:
            raise self._stream_error

        logger.info("VolcEngine 流式识别已启动")

    def send_frame(self, pcm_bytes: bytes, is_last: bool = False) -> None:
        """送入一帧 PCM 音频。is_last=True 表示这是最后一包。"""
        if self._audio_queue is None:
            return
        if is_last:
            self._audio_queue.put(("LAST", pcm_bytes))
        else:
            self._audio_queue.put(pcm_bytes)

    def stop_streaming(self) -> None:
        """等待流式识别线程结束（调用前应已通过 send_frame(is_last=True) 发送结束信号）。"""
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=10.0)
            if self._stream_thread.is_alive():
                logger.warning("流式识别线程未能在 10s 内结束")

        self._audio_queue = None
        self._stream_thread = None
        self._stream_loop = None
        logger.info("VolcEngine 流式识别已停止")

    def _streaming_thread_entry(
        self,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        """流式识别后台线程入口。"""
        try:
            asyncio.run(self._streaming_loop(on_partial, on_sentence))
        except Exception as e:
            logger.error("流式识别线程异常: %s", e, exc_info=True)
            if not self._stream_ready.is_set():
                self._stream_error = e
                self._stream_ready.set()

    async def _streaming_loop(
        self,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        """异步流式识别主循环。"""
        import websockets

        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        }

        try:
            async with websockets.connect(self._ws_url, additional_headers=headers) as ws:
                # 发送 full client request
                req_payload = self._make_request_payload()
                await ws.send(_build_full_client_request(req_payload))

                # 等待确认响应
                resp_data = await ws.recv()
                first_resp = _parse_response(resp_data)
                if first_resp.get("error"):
                    raise RuntimeError(
                        f"VolcEngine 连接错误: {first_resp.get('message', first_resp)}"
                    )

                # 连接就绪，通知主线程
                self._stream_ready.set()

                # 并发：发送音频 + 接收结果
                send_task = asyncio.create_task(self._send_audio_loop(ws))
                recv_task = asyncio.create_task(
                    self._recv_result_loop(ws, on_partial, on_sentence)
                )

                # 等待发送完成（收到 sentinel），然后等待接收完成
                await send_task
                await recv_task

        except Exception as e:
            if not self._stream_ready.is_set():
                self._stream_error = e
                self._stream_ready.set()
            else:
                logger.error("VolcEngine 流式识别异常: %s", e)

    async def _send_audio_loop(self, ws) -> None:
        """异步循环：从队列取音频帧并发送。"""
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, self._queue_get_blocking)
            if item is _SENTINEL:
                # 兜底：如果没有通过 send_frame(is_last=True) 结束，发空包
                await ws.send(_build_audio_frame(b"", is_last=True))
                return
            if isinstance(item, tuple) and item[0] == "LAST":
                # 最后一包：带结束标志发送
                await ws.send(_build_audio_frame(item[1], is_last=True))
                return
            await ws.send(_build_audio_frame(item, is_last=False))

    def _queue_get_blocking(self) -> Optional[bytes]:
        """阻塞从音频队列获取数据，支持超时以便检测停止。"""
        while True:
            try:
                return self._audio_queue.get(timeout=1.0)
            except Empty:
                # 队列为空但线程还在运行，继续等待
                if self._audio_queue is None:
                    return _SENTINEL
                continue

    async def _recv_result_loop(
        self,
        ws,
        on_partial: Callable[[str], None],
        on_sentence: Callable[[str], None],
    ) -> None:
        """异步循环：接收识别结果并分发回调。"""
        last_partial_text = ""
        finished_indices: set[int] = set()

        try:
            async for message in ws:
                if isinstance(message, str):
                    continue  # 忽略文本消息

                resp = _parse_response(message)
                if resp.get("error"):
                    msg = resp.get("message", "")
                    if "timeout" in msg.lower() or "session has ended" in msg.lower():
                        logger.debug("VolcEngine 流式会话超时（正常关闭）: %s", msg)
                    else:
                        logger.error("VolcEngine 流式错误: code=%s, %s", resp.get("code"), msg)
                    continue

                res = resp.get("result", {})
                if isinstance(res, list) and res:
                    res = res[0]
                if not isinstance(res, dict):
                    continue

                # 全局文本作为 partial
                full_text = res.get("text", "")

                utterances = res.get("utterances", [])
                if utterances:
                    for utt in utterances:
                        utt_text = utt.get("text", "")
                        if not utt_text:
                            continue
                        is_definite = utt.get("definite", False)
                        utt_idx = utt.get("start_time", 0)

                        if is_definite:
                            if utt_idx not in finished_indices:
                                finished_indices.add(utt_idx)
                                on_sentence(full_text)
                                last_partial_text = full_text
                        else:
                            if full_text != last_partial_text:
                                last_partial_text = full_text
                                on_partial(full_text)
                elif full_text and full_text != last_partial_text:
                    last_partial_text = full_text
                    on_partial(full_text)

        except Exception as e:
            # websockets.ConnectionClosed 等
            logger.debug("流式接收循环结束: %s", e)
