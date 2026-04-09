"""Transcribe page for the Vocotype Web UI -- main landing page."""

import time

from nicegui import ui

from app.web.state import app_state
from app.web.components.audio_controls import audio_controls, _cleanup_worker
from app.web.components.transcript import transcript

ACCENT = '#646cff'
CARD_BG = '#1a1a2e'
INACTIVE_TEXT = '#b0b0c0'

AUDIO_SOURCES = [
    ('microphone', 'mic', '电脑麦克风'),
    ('esp32', 'wifi', 'ESP32 UDP'),
    ('device', 'speaker', '其他设备'),
]


def _select_source(source_type: str):
    """Switch audio source, tearing down the current worker if needed."""
    if source_type == app_state.audio_source_type:
        return
    # Stop and destroy existing worker so a new one is created with the
    # right audio source on next start.
    if app_state.is_recording:
        app_state.is_recording = False
        app_state.recording_start_time = None
    _cleanup_worker()
    app_state.audio_source_type = source_type
    # Re-render the page
    ui.navigate.to('/')


def transcribe_page():
    """Main transcription page -- default landing page."""

    # ---- 1. Audio source selector ----
    with ui.row().classes('items-center gap-2').style('padding-bottom: 8px;'):
        ui.label('音频源').style(f'color: {INACTIVE_TEXT}; font-size: 13px; margin-right: 4px;')
        for src_type, icon, label in AUDIO_SOURCES:
            is_active = app_state.audio_source_type == src_type
            bg = ACCENT if is_active else 'transparent'
            text = 'white' if is_active else INACTIVE_TEXT
            border = f'1px solid {ACCENT}' if is_active else '1px solid #444'
            ui.button(label, icon=icon, on_click=lambda st=src_type: _select_source(st)).props(
                'flat dense no-caps'
            ).style(
                f'background: {bg}; color: {text}; border: {border}; '
                f'border-radius: 16px; padding: 4px 14px; font-size: 12px;'
            )

    # Device picker (only visible when "其他设备" is selected)
    if app_state.audio_source_type == 'device':
        with ui.row().classes('items-center gap-2').style('padding-bottom: 4px;'):
            ui.label('设备:').style(f'color: {INACTIVE_TEXT}; font-size: 12px;')
            ui.input(
                placeholder='设备名称或索引',
                value=app_state.selected_device or '',
                on_change=lambda e: setattr(app_state, 'selected_device', e.value or None),
            ).props('dense outlined dark').style(
                'width: 240px; font-size: 12px;'
            )

    # ---- 2. Audio controls ----
    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 12px 0; '
        f'margin-bottom: 8px;'
    ):
        audio_controls()

    # ---- 3. Transcript area (takes most vertical space) ----
    transcript()

    # ---- 4. Bottom status bar ----
    _status_bar()


# ------------------------------------------------------------------
# Status bar
# ------------------------------------------------------------------

def _status_bar():
    """Bottom status bar showing recording duration, stats, and mode."""

    with ui.row().classes('items-center justify-between w-full no-wrap').style(
        f'padding: 8px 12px; background: {CARD_BG}; border-radius: 8px; '
        f'margin-top: 8px;'
    ):
        # Left: recording duration
        duration_label = ui.label('').style(
            f'color: {INACTIVE_TEXT}; font-size: 12px; min-width: 100px;')

        # Centre: transcription stats
        stats_label = ui.label('').style(
            f'color: {INACTIVE_TEXT}; font-size: 12px;')

        # Right: current mode label
        mode_text = 'VAD 模式' if app_state.recording_mode == 'vad' else '按钮模式'
        ui.label(mode_text).style(
            f'color: {INACTIVE_TEXT}; font-size: 12px; text-align: right; min-width: 80px;')

    def _refresh_status():
        """Update the status bar labels."""
        # Duration
        if app_state.is_recording and app_state.recording_start_time is not None:
            elapsed = time.time() - app_state.recording_start_time
            mins, secs = divmod(int(elapsed), 60)
            duration_label.text = f'录音时长: {mins:02d}:{secs:02d}'
        else:
            duration_label.text = ''

        # Stats from worker
        if app_state.worker is not None:
            try:
                s = app_state.worker.transcription_stats
            except Exception:
                s = app_state.transcription_stats
        else:
            s = app_state.transcription_stats
        stats_label.text = (
            f'已完成 {s.get("completed", 0)} / '
            f'已提交 {s.get("submitted", 0)} / '
            f'队列 {s.get("pending", 0)}'
        )

    # Refresh every second
    ui.timer(1.0, _refresh_status)
