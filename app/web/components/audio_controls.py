"""Audio controls component for the Vocotype Web UI."""

import logging
import time

from nicegui import ui

from app.web.state import app_state

logger = logging.getLogger(__name__)

ACCENT = '#646cff'
RECORD_RED = '#ef4444'

PULSE_CSS = """
@keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
    70%  { box-shadow: 0 0 0 16px rgba(239, 68, 68, 0); }
    100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}
.pulse-recording {
    animation: pulse-ring 1.4s ease-out infinite;
}
"""


def _on_transcription_result(result):
    """Callback from worker thread -- append to shared state list.

    Runs in a background thread, so we only touch the plain Python list
    (no NiceGUI calls).  A ui.timer in the transcript component picks up
    changes on the next tick.
    """
    app_state.transcription_results.append({
        'text': result.text,
        'speaker': result.speaker,
        'speaker_confidence': result.speaker_confidence,
        'confidence': result.confidence,
        'duration': result.duration,
        'timestamp': time.strftime('%H:%M:%S'),
    })


def _ensure_audio_source():
    """Create the audio source object if it doesn't exist yet."""
    if app_state.audio is not None:
        return
    if app_state.audio_source_type == 'esp32':
        from app.udp_audio_source import UDPAudioSource
        app_state.audio = UDPAudioSource(
            esp32_host=app_state.esp32_host,
            esp32_port=app_state.esp32_port,
        )
    else:
        from app.audio_capture import AudioCapture
        device = app_state.selected_device if app_state.audio_source_type == 'device' else None
        app_state.audio = AudioCapture(
            sample_rate=16000, block_ms=20, device=device,
        )


def _ensure_worker():
    """Create the transcription worker if it doesn't exist yet."""
    if app_state.worker is not None:
        return
    _ensure_audio_source()
    if app_state.recording_mode == 'vad':
        from app.vad_worker import VadTranscriptionWorker
        app_state.worker = VadTranscriptionWorker(
            on_result=_on_transcription_result,
            audio_source=app_state.audio,
            speaker_processor=app_state.speaker_processor,
            speaker_mode=app_state.speaker_mode,
        )
    else:
        from app.transcribe import TranscriptionWorker
        app_state.worker = TranscriptionWorker(
            on_result=_on_transcription_result,
            audio_source=app_state.audio,
        )


def _start_recording():
    """Start recording / VAD listening."""
    try:
        _ensure_worker()
        app_state.worker.start()
        app_state.is_recording = True
        app_state.recording_start_time = time.time()
    except Exception as exc:
        logger.error("Failed to start recording: %s", exc, exc_info=True)
        ui.notify(f'启动录音失败: {exc}', type='negative')


def _stop_recording():
    """Stop recording / VAD listening."""
    try:
        if app_state.worker is not None:
            app_state.worker.stop()
        app_state.is_recording = False
        app_state.recording_start_time = None
    except Exception as exc:
        logger.error("Failed to stop recording: %s", exc, exc_info=True)
        ui.notify(f'停止录音失败: {exc}', type='negative')


def _cleanup_worker():
    """Destroy the current worker and audio source so a fresh one is
    created next time (e.g. when the user changes mode or source)."""
    if app_state.worker is not None:
        try:
            app_state.worker.cleanup()
        except Exception:
            pass
        app_state.worker = None
    if app_state.audio is not None:
        try:
            app_state.audio.stop()
        except Exception:
            pass
        app_state.audio = None


# ------------------------------------------------------------------
# Public component
# ------------------------------------------------------------------

def audio_controls():
    """Recording control component. Shows button mode or VAD mode controls."""

    # Inject pulse animation CSS once
    ui.add_css(PULSE_CSS)

    if app_state.recording_mode == 'vad':
        _vad_controls()
    else:
        _button_controls()


# ------------------------------------------------------------------
# Button mode
# ------------------------------------------------------------------

def _button_controls():
    """Large circular record/stop button."""

    with ui.column().classes('items-center w-full gap-3').style('padding: 16px 0;'):
        # The record button
        btn_color = RECORD_RED if app_state.is_recording else ACCENT
        btn_icon = 'stop' if app_state.is_recording else 'mic'
        pulse_cls = 'pulse-recording' if app_state.is_recording else ''

        btn = ui.button(
            icon=btn_icon,
            on_click=lambda: _toggle_recording(),
        ).props('round flat').style(
            f'width: 80px; height: 80px; background: {btn_color}; '
            f'color: white; font-size: 32px;'
        )
        if pulse_cls:
            btn.classes(pulse_cls)

        # Label below
        if app_state.is_recording:
            ui.label('录音中… 点击停止').style(
                'color: #ef4444; font-size: 13px;')
        else:
            ui.label('点击开始录音').style(
                'color: #b0b0c0; font-size: 13px;')


def _toggle_recording():
    """Toggle between recording and not-recording."""
    if app_state.is_recording:
        _stop_recording()
    else:
        _start_recording()
    # Force page refresh to update UI state
    ui.navigate.to('/')


# ------------------------------------------------------------------
# VAD mode
# ------------------------------------------------------------------

def _vad_controls():
    """VAD auto-detection controls."""

    with ui.column().classes('items-center w-full gap-3').style('padding: 16px 0;'):
        # Status indicator row
        with ui.row().classes('items-center gap-2'):
            if app_state.is_recording:
                # Green pulsing dot
                ui.element('div').style(
                    'width: 10px; height: 10px; border-radius: 50%; '
                    'background: #4ade80; box-shadow: 0 0 6px #4ade80;'
                )
                ui.label('VAD 自动检测中...').style(
                    'color: #4ade80; font-size: 14px; font-weight: 500;')
            else:
                ui.element('div').style(
                    'width: 10px; height: 10px; border-radius: 50%; '
                    'background: #666;'
                )
                ui.label('VAD 已停止').style(
                    'color: #b0b0c0; font-size: 14px;')

        # Simple audio level placeholder bar
        if app_state.is_recording:
            with ui.element('div').style(
                'width: 200px; height: 6px; background: #2a2a3e; '
                'border-radius: 3px; overflow: hidden;'
            ):
                ui.element('div').style(
                    'width: 30%; height: 100%; background: #4ade80; '
                    'border-radius: 3px; transition: width 0.3s;'
                )

        # Start / Stop button
        if app_state.is_recording:
            ui.button('停止监听', icon='stop', on_click=lambda: _toggle_recording()).props(
                'flat'
            ).style(
                f'background: {RECORD_RED}; color: white; border-radius: 8px; '
                f'padding: 8px 24px;'
            )
        else:
            ui.button('开始监听', icon='hearing', on_click=lambda: _toggle_recording()).props(
                'flat'
            ).style(
                f'background: {ACCENT}; color: white; border-radius: 8px; '
                f'padding: 8px 24px;'
            )
