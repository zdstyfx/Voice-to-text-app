"""Settings page for the Vocotype Web UI."""

from nicegui import ui

from app.web.state import app_state

ACCENT = '#646cff'
CARD_BG = '#1a1a2e'
TEXT_MAIN = '#e0e0e0'
TEXT_SEC = '#b0b0c0'

CARD_STYLE = (
    f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
    f'margin-bottom: 16px;'
)


def _pill_button(label: str, value: str, current: str, on_click):
    """Render a pill/chip toggle button, highlighted when selected."""
    is_active = current == value
    bg = ACCENT if is_active else 'transparent'
    text = 'white' if is_active else TEXT_SEC
    border = f'1px solid {ACCENT}' if is_active else '1px solid #444'
    ui.button(label, on_click=lambda: on_click(value)).props(
        'flat dense no-caps'
    ).style(
        f'background: {bg}; color: {text}; border: {border}; '
        f'border-radius: 16px; padding: 4px 16px; font-size: 13px;'
    )


def _section_title(text: str):
    """Render a card section title."""
    ui.label(text).style(
        f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
        f'margin-bottom: 12px;'
    )


def settings_page():
    """Settings page for configuring Vocotype."""

    ui.label('Settings').style(
        f'color: {TEXT_MAIN}; font-size: 22px; font-weight: 700; '
        f'margin-bottom: 16px;'
    )

    # ----------------------------------------------------------------
    # Section 1: Recording mode
    # ----------------------------------------------------------------
    with ui.element('div').style(CARD_STYLE):
        _section_title('录音模式')

        mode_container = ui.row().classes('items-center gap-3')

        def _set_recording_mode(mode: str):
            app_state.recording_mode = mode
            ui.navigate.to('/settings')

        with mode_container:
            _pill_button('按钮模式', 'button', app_state.recording_mode,
                         _set_recording_mode)
            _pill_button('VAD 自动模式', 'vad', app_state.recording_mode,
                         _set_recording_mode)

        # Brief explanations
        with ui.row().classes('gap-6').style('margin-top: 8px;'):
            if app_state.recording_mode == 'button':
                ui.label('手动按下按钮开始/停止录音').style(
                    f'color: {TEXT_SEC}; font-size: 12px;')
            else:
                ui.label('自动检测语音活动，无需手动操作').style(
                    f'color: {TEXT_SEC}; font-size: 12px;')

    # ----------------------------------------------------------------
    # Section 2: Speaker recognition
    # ----------------------------------------------------------------
    with ui.element('div').style(CARD_STYLE):
        _section_title('声纹识别')

        speaker_modes = [
            ('关闭', 'off'),
            ('识别', 'identify'),
            ('过滤', 'filter'),
            ('实时注册', 'enroll'),
        ]

        def _set_speaker_mode(mode: str):
            app_state.speaker_mode = mode
            ui.navigate.to('/settings')

        with ui.row().classes('items-center gap-2'):
            for label, value in speaker_modes:
                _pill_button(label, value, app_state.speaker_mode,
                             _set_speaker_mode)

        # Whitelist section when filter mode is selected
        if app_state.speaker_mode == 'filter':
            ui.separator().style('margin: 12px 0; opacity: 0.2;')
            ui.label('白名单').style(
                f'color: {TEXT_MAIN}; font-size: 14px; font-weight: 500; '
                f'margin-bottom: 8px;'
            )

            speakers = _load_speaker_list()
            if speakers:
                for name in speakers:
                    is_checked = name in app_state.speaker_whitelist

                    def _toggle_whitelist(e, speaker_name=name):
                        if e.value:
                            if speaker_name not in app_state.speaker_whitelist:
                                app_state.speaker_whitelist.append(speaker_name)
                        else:
                            if speaker_name in app_state.speaker_whitelist:
                                app_state.speaker_whitelist.remove(speaker_name)

                    ui.checkbox(name, value=is_checked,
                                on_change=_toggle_whitelist).style(
                        f'color: {TEXT_MAIN};'
                    )
            else:
                ui.label('无已注册说话人').style(
                    f'color: {TEXT_SEC}; font-size: 13px; font-style: italic;')

    # ----------------------------------------------------------------
    # Section 3: VAD parameters
    # ----------------------------------------------------------------
    with ui.element('div').style(CARD_STYLE):
        _section_title('VAD 参数')

        with ui.row().classes('items-center gap-4 w-full'):
            ui.label('语音检测阈值').style(
                f'color: {TEXT_SEC}; font-size: 13px; min-width: 100px;')
            threshold_label = ui.label(f'{app_state.vad_threshold:.2f}').style(
                f'color: {ACCENT}; font-size: 14px; font-weight: 600; '
                f'min-width: 40px; text-align: right;'
            )

        def _on_threshold_change(e):
            app_state.vad_threshold = round(e.value, 2)
            threshold_label.text = f'{app_state.vad_threshold:.2f}'

        ui.slider(
            min=0.1, max=0.9, step=0.05,
            value=app_state.vad_threshold,
            on_change=_on_threshold_change,
        ).props('color=indigo label-always').style(
            'width: 100%; margin-top: 4px;'
        )

        ui.label('较低值更灵敏，较高值需要更清晰的语音').style(
            f'color: {TEXT_SEC}; font-size: 11px; margin-top: 4px;')

    # ----------------------------------------------------------------
    # Section 4: Output configuration
    # ----------------------------------------------------------------
    with ui.element('div').style(CARD_STYLE):
        _section_title('输出配置')

        with ui.column().classes('gap-2'):
            ui.switch(
                '追加换行',
                value=app_state.append_newline,
                on_change=lambda e: setattr(app_state, 'append_newline', e.value),
            ).style(f'color: {TEXT_MAIN};')
            ui.label('每段转录文本后自动添加换行符').style(
                f'color: {TEXT_SEC}; font-size: 11px; margin-left: 48px; '
                f'margin-top: -8px;'
            )

            ui.switch(
                '去重',
                value=app_state.dedupe,
                on_change=lambda e: setattr(app_state, 'dedupe', e.value),
            ).style(f'color: {TEXT_MAIN};')
            ui.label('过滤重复的转录结果').style(
                f'color: {TEXT_SEC}; font-size: 11px; margin-left: 48px; '
                f'margin-top: -8px;'
            )


def _load_speaker_list() -> list:
    """Load registered speaker names from SpeakerDB (lazy import)."""
    try:
        from app.speaker_db import SpeakerDB

        db_path = app_state.config.get('speaker', {}).get(
            'db_path', 'speaker_db.json'
        )
        db = SpeakerDB(db_path)
        return db.list_manual_speakers()
    except Exception:
        return []
