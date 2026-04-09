"""ESP32 wireless microphone management page for the Vocotype Web UI."""

import logging

from nicegui import ui

from app.web.state import app_state

logger = logging.getLogger(__name__)

# -- Visual constants (match project dark theme) --
ACCENT = '#646cff'
CARD_BG = '#1a1a2e'
SUCCESS = '#4ade80'
ERROR = '#ef4444'
WARNING = '#facc15'
TEXT_MAIN = '#e0e0e0'
TEXT_SEC = '#b0b0c0'

PULSE_CSS = """
@keyframes esp32-pulse {
    0%   { opacity: 1; }
    50%  { opacity: 0.4; }
    100% { opacity: 1; }
}
.esp32-connecting {
    animation: esp32-pulse 1.2s ease-in-out infinite;
}
"""

# Module-level flag for "connecting in progress" (not persisted in app_state
# because it is transient UI state within a single page render cycle).
_connecting = False


# ------------------------------------------------------------------
# Backend helpers
# ------------------------------------------------------------------

def _connect_esp32():
    """Create UDPAudioSource and start connection."""
    global _connecting
    _connecting = True
    # Force UI refresh to show "connecting" state
    ui.navigate.to('/esp32')

    try:
        from app.udp_audio_source import UDPAudioSource

        # Tear down any existing source first
        if app_state.audio is not None:
            try:
                app_state.audio.stop()
            except Exception:
                pass
            app_state.audio = None

        app_state.audio = UDPAudioSource(
            esp32_host=app_state.esp32_host,
            esp32_port=app_state.esp32_port,
        )
        app_state.audio.start()
        app_state.esp32_connected = True
        logger.info("ESP32 已连接: %s:%d", app_state.esp32_host, app_state.esp32_port)
    except Exception as exc:
        logger.error("ESP32 连接失败: %s", exc, exc_info=True)
        app_state.esp32_connected = False
        ui.notify(f'ESP32 连接失败: {exc}', type='negative')
    finally:
        _connecting = False
        ui.navigate.to('/esp32')


def _disconnect_esp32():
    """Stop and cleanup UDPAudioSource."""
    if app_state.audio is not None:
        try:
            app_state.audio.stop()
        except Exception as exc:
            logger.error("ESP32 断开异常: %s", exc, exc_info=True)
        app_state.audio = None
    app_state.esp32_connected = False
    logger.info("ESP32 已断开")
    ui.navigate.to('/esp32')


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

def esp32_page():
    """ESP32 wireless microphone management page."""

    ui.add_css(PULSE_CSS)

    # Page title
    ui.label('ESP32 无线麦克风').style(
        f'color: {TEXT_MAIN}; font-size: 20px; font-weight: 600; '
        f'margin-bottom: 16px;'
    )

    # ---- 1. Connection Config Card ----
    _connection_config_card()

    # ---- 2. Status Panel Card ----
    _status_panel_card()

    # ---- 3. Recording Save Card ----
    _recording_save_card()


# ------------------------------------------------------------------
# Card 1: Connection Config
# ------------------------------------------------------------------

def _connection_config_card():
    """Connection configuration card with IP, port, and connect/disconnect."""

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px;'
    ):
        ui.label('连接配置').style(
            f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 12px;'
        )

        # Input row
        with ui.row().classes('items-end gap-4 w-full no-wrap').style(
            'flex-wrap: wrap;'
        ):
            # IP address
            ui.input(
                label='ESP32 IP 地址',
                value=app_state.esp32_host,
                on_change=lambda e: setattr(app_state, 'esp32_host', e.value),
            ).props('dense outlined dark').style(
                f'width: 200px; font-size: 13px;'
            ).tooltip('ESP32 设备的 IP 地址')

            # Port
            ui.number(
                label='UDP 端口',
                value=app_state.esp32_port,
                min=1,
                max=65535,
                on_change=lambda e: setattr(app_state, 'esp32_port', int(e.value)) if e.value else None,
            ).props('dense outlined dark').style(
                f'width: 120px; font-size: 13px;'
            ).tooltip('UDP 监听端口')

            # Connect / Disconnect button
            if _connecting:
                ui.button('连接中...', icon='sync').props('flat disable').style(
                    f'background: #555; color: {TEXT_SEC}; border-radius: 8px; '
                    f'padding: 8px 20px; cursor: not-allowed;'
                )
            elif app_state.esp32_connected:
                ui.button('断开', icon='link_off', on_click=_disconnect_esp32).props(
                    'flat'
                ).style(
                    f'background: {ERROR}; color: white; border-radius: 8px; '
                    f'padding: 8px 20px;'
                )
            else:
                ui.button('连接', icon='link', on_click=_connect_esp32).props(
                    'flat'
                ).style(
                    f'background: {ACCENT}; color: white; border-radius: 8px; '
                    f'padding: 8px 20px;'
                )


# ------------------------------------------------------------------
# Card 2: Status Panel
# ------------------------------------------------------------------

def _status_panel_card():
    """Connection status display with indicator dot and audio level bar."""

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px;'
    ):
        ui.label('连接状态').style(
            f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 12px;'
        )

        # Status indicator row
        status_row = ui.row().classes('items-center gap-3')
        with status_row:
            if _connecting:
                # Yellow pulsing dot
                ui.element('div').classes('esp32-connecting').style(
                    f'width: 12px; height: 12px; border-radius: 50%; '
                    f'background: {WARNING}; box-shadow: 0 0 8px {WARNING};'
                )
                ui.label('连接中...').style(
                    f'color: {WARNING}; font-size: 14px; font-weight: 500;'
                )
            elif app_state.esp32_connected:
                # Green dot
                ui.element('div').style(
                    f'width: 12px; height: 12px; border-radius: 50%; '
                    f'background: {SUCCESS}; box-shadow: 0 0 8px {SUCCESS};'
                )
                ui.label('已连接').style(
                    f'color: {SUCCESS}; font-size: 14px; font-weight: 500;'
                )
            else:
                # Gray dot
                ui.element('div').style(
                    'width: 12px; height: 12px; border-radius: 50%; '
                    'background: #666;'
                )
                ui.label('未连接').style(
                    f'color: {TEXT_SEC}; font-size: 14px;'
                )

        # Connection details when connected
        if app_state.esp32_connected:
            with ui.row().classes('items-center gap-4').style('margin-top: 12px;'):
                ui.label(f'目标: {app_state.esp32_host}:{app_state.esp32_port}').style(
                    f'color: {TEXT_SEC}; font-size: 12px;'
                )

        # Audio level bar (placeholder, animated when connected)
        ui.element('div').style('margin-top: 16px;')
        ui.label('音频电平').style(
            f'color: {TEXT_SEC}; font-size: 12px; margin-bottom: 4px;'
        )

        level_container = ui.element('div').style(
            'width: 100%; height: 8px; background: #2a2a3e; '
            'border-radius: 4px; overflow: hidden;'
        )
        with level_container:
            level_bar = ui.element('div').style(
                'width: 0%; height: 100%; border-radius: 4px; '
                'transition: width 0.3s ease;'
            )

        # Packet stats row
        stats_label = ui.label('').style(
            f'color: {TEXT_SEC}; font-size: 11px; margin-top: 8px;'
        )

        def _refresh_status():
            """Update audio level bar and packet stats via timer."""
            if app_state.esp32_connected and app_state.audio is not None:
                audio = app_state.audio
                # Compute a rough audio level from the queue size ratio
                try:
                    qsize = audio.queue.qsize()
                    max_size = audio.queue.maxsize or 200
                    # Use queue fill percentage as a proxy for activity
                    pct = min(100, int((qsize / max_size) * 100)) if max_size > 0 else 0
                    # Ensure at least a small bar when connected and receiving
                    received = getattr(audio, '_packets_received', 0)
                    lost = getattr(audio, '_packets_lost', 0)
                    if received > 0 and pct < 5:
                        pct = 5  # show minimal activity
                    color = SUCCESS if pct < 70 else (WARNING if pct < 90 else ERROR)
                    level_bar.style(
                        f'width: {pct}%; height: 100%; background: {color}; '
                        f'border-radius: 4px; transition: width 0.3s ease;'
                    )
                    stats_label.text = f'收到 {received} 包  |  丢失 {lost} 包  |  队列 {qsize}/{max_size}'
                except Exception:
                    level_bar.style(
                        'width: 0%; height: 100%; background: #666; '
                        'border-radius: 4px; transition: width 0.3s ease;'
                    )
                    stats_label.text = ''
            else:
                level_bar.style(
                    'width: 0%; height: 100%; background: #666; '
                    'border-radius: 4px; transition: width 0.3s ease;'
                )
                stats_label.text = ''

        ui.timer(1.0, _refresh_status)


# ------------------------------------------------------------------
# Card 3: Recording Save
# ------------------------------------------------------------------

def _recording_save_card():
    """Toggle for saving received audio to file."""

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px;'
    ):
        ui.label('录音保存').style(
            f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 12px;'
        )

        # Save path display (shown when enabled)
        save_path_label = ui.label('').style(
            f'color: {TEXT_SEC}; font-size: 12px; margin-top: 8px; '
            f'font-family: monospace;'
        )

        def _on_save_toggle(e):
            if e.value:
                import os
                import time as _time
                default_dir = os.path.join(os.getcwd(), 'recordings')
                timestamp = _time.strftime('%Y%m%d_%H%M%S')
                path = os.path.join(default_dir, f'esp32_{timestamp}.wav')
                save_path_label.text = f'保存路径: {path}'
            else:
                save_path_label.text = ''

        # Save toggle row
        with ui.row().classes('items-center gap-3'):
            ui.switch(
                '保存录音到文件',
                value=False,
                on_change=_on_save_toggle,
            ).style(f'color: {TEXT_MAIN};')

        ui.label(
            '提示: 录音文件保存功能将在后续版本中完善。'
        ).style(
            f'color: {TEXT_SEC}; font-size: 11px; margin-top: 12px; '
            f'font-style: italic;'
        )
