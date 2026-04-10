"""Speaker voice print management page for the Vocotype Web UI."""

import logging
from datetime import datetime

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

SPEAKER_COLORS = ['#4ade80', '#60a5fa', '#f97316', '#a78bfa', '#fb7185', '#fbbf24']


# ------------------------------------------------------------------
# Backend helpers
# ------------------------------------------------------------------

def _get_speaker_db():
    """Get or create SpeakerDB instance."""
    from app.speaker_db import SpeakerDB
    db_path = app_state.config.get('speaker', {}).get('db_path', 'speaker_db.json')
    return SpeakerDB(db_path)


def _get_speaker_info(db):
    """Get list of speaker info dicts from the database."""
    speakers = []
    for name in db.list_speakers():
        entry = db._speakers.get(name) or db._auto_speakers.get(name, {})
        speakers.append({
            'name': name,
            'registered_at': entry.get('registered_at', 'N/A'),
            'sample_count': entry.get('sample_count', len(entry.get('embeddings', []))),
            'is_manual': name in db._speakers,
        })
    return speakers


def _format_time(iso_str):
    """Format ISO8601 timestamp to readable string."""
    if not iso_str or iso_str == 'N/A':
        return 'N/A'
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return iso_str


def _delete_speaker(name):
    """Delete a speaker and refresh the page."""
    db = _get_speaker_db()
    if db.remove(name):
        ui.notify(f'已删除说话人: {name}', type='warning')
    else:
        ui.notify(f'未找到说话人: {name}', type='negative')
    ui.navigate.to('/speakers')


def _start_enrollment(name, num_samples):
    """Start voice enrollment by configuring speaker processor and worker."""
    if not name or not name.strip():
        ui.notify('请输入说话人名称', type='negative')
        return
    name = name.strip()
    num_samples = int(num_samples)

    # Check for duplicate names
    db = _get_speaker_db()
    if name in db.list_speakers():
        ui.notify(f'说话人 "{name}" 已存在，请使用其他名称', type='negative')
        return

    # Set up speaker processor if needed
    if app_state.speaker_processor is None:
        try:
            from app.speaker import SpeakerProcessor
            app_state.speaker_processor = SpeakerProcessor(app_state.config)
        except Exception as exc:
            logger.error("Failed to initialize SpeakerProcessor: %s", exc)
            ui.notify(f'声纹模型加载失败: {exc}', type='negative')
            return

    # Configure enrollment target in config
    app_state.config.setdefault('speaker', {})['enroll_target'] = name
    app_state.config['speaker']['enroll_samples'] = num_samples

    # Create audio source if needed
    if app_state.audio is None:
        try:
            from app.audio_capture import AudioCapture
            audio_cfg = app_state.config.get('audio', {})
            app_state.audio = AudioCapture(
                sample_rate=audio_cfg.get('sample_rate', 16000),
                block_ms=audio_cfg.get('block_ms', 20),
                device=audio_cfg.get('device'),
            )
        except Exception as exc:
            logger.error("Failed to create AudioCapture: %s", exc)
            ui.notify(f'音频设备初始化失败: {exc}', type='negative')
            return

    # Create VadTranscriptionWorker in enroll mode
    try:
        from app.vad_worker import VadTranscriptionWorker
        worker = VadTranscriptionWorker(
            on_result=None,
            audio_source=app_state.audio,
            speaker_processor=app_state.speaker_processor,
            speaker_mode='enroll',
        )
        worker.start()
        logger.info("Enrollment started for '%s' (%d samples)", name, num_samples)
        ui.notify(f'开始采集 {name} 的声纹 ({num_samples} 样本)', type='info')
    except Exception as exc:
        logger.error("Failed to start enrollment worker: %s", exc)
        ui.notify(f'采集启动失败: {exc}', type='negative')


# ------------------------------------------------------------------
# Page
# ------------------------------------------------------------------

def speakers_page():
    """Speaker voice print management page."""

    # Page title
    ui.label('声纹管理').style(
        f'color: {TEXT_MAIN}; font-size: 20px; font-weight: 600; '
        f'margin-bottom: 4px;'
    )
    ui.label('管理已注册的说话人声纹，或注册新的说话人。').style(
        f'color: {TEXT_SEC}; font-size: 13px; margin-bottom: 16px;'
    )

    # Load speaker data
    db = _get_speaker_db()
    speaker_list = _get_speaker_info(db)

    # ---- 1. Registered Speakers Card ----
    _speaker_list_card(speaker_list)

    # ---- 2. Diarize session speakers (if active) ----
    if app_state.speaker_mode == 'diarize' and app_state.speaker_cluster is not None:
        _diarize_card()

    # ---- 3. New registration card ----
    _new_registration_card()


# ------------------------------------------------------------------
# Card 1: Registered Speakers List
# ------------------------------------------------------------------

def _speaker_list_card(speaker_list):
    """Card showing all registered speakers with delete actions."""

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px;'
    ):
        ui.label('已注册说话人').style(
            f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 12px;'
        )

        if not speaker_list:
            # Empty state
            with ui.element('div').style(
                'text-align: center; padding: 32px 0;'
            ):
                ui.icon('person_off').style(
                    f'font-size: 48px; color: #555; margin-bottom: 8px;'
                )
                ui.label('暂无注册说话人').style(
                    f'color: {TEXT_SEC}; font-size: 14px;'
                )
                ui.label('使用下方表单注册新的说话人声纹。').style(
                    f'color: #777; font-size: 12px; margin-top: 4px;'
                )
        else:
            # Speaker table
            for idx, spk in enumerate(speaker_list):
                _speaker_row(idx, spk)


def _speaker_row(idx, spk):
    """Single speaker row with avatar, info, and delete button."""
    color = SPEAKER_COLORS[idx % len(SPEAKER_COLORS)]
    name = spk['name']

    with ui.row().classes('items-center w-full no-wrap').style(
        f'padding: 10px 0; '
        f'border-bottom: 1px solid #2a2a3e;'
    ):
        # Color avatar block
        ui.element('div').style(
            f'width: 36px; height: 36px; border-radius: 8px; '
            f'background: {color}; flex-shrink: 0; '
            f'display: flex; align-items: center; justify-content: center; '
            f'color: white; font-weight: 600; font-size: 14px;'
        ).props(f'innerHTML="{name[0].upper() if name else "?"}"')

        # Speaker info column
        with ui.column().style('flex: 1; gap: 2px; min-width: 0; margin-left: 12px;'):
            # Name row
            with ui.row().classes('items-center gap-2'):
                ui.label(name).style(
                    f'color: {TEXT_MAIN}; font-size: 14px; font-weight: 500;'
                )
                if not spk.get('is_manual', True):
                    ui.label('自动').style(
                        f'color: {WARNING}; font-size: 10px; '
                        f'background: rgba(250,204,21,0.15); '
                        f'padding: 1px 6px; border-radius: 4px;'
                    )
            # Details row
            with ui.row().classes('items-center gap-4'):
                ui.label(f'注册: {_format_time(spk["registered_at"])}').style(
                    f'color: {TEXT_SEC}; font-size: 11px;'
                )
                ui.label(f'样本: {spk["sample_count"]}').style(
                    f'color: {TEXT_SEC}; font-size: 11px;'
                )

        # Delete button with confirmation
        with ui.element('div').style('flex-shrink: 0;'):
            ui.button(
                icon='delete',
                on_click=lambda n=name: _confirm_delete(n),
            ).props('flat dense round').style(
                f'color: {ERROR}; opacity: 0.6;'
            ).tooltip(f'删除 {name}')


def _confirm_delete(name):
    """Show a confirmation dialog before deleting a speaker."""
    with ui.dialog() as dialog, ui.card().style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px;'
    ):
        ui.label(f'确认删除说话人 "{name}"？').style(
            f'color: {TEXT_MAIN}; font-size: 14px; margin-bottom: 16px;'
        )
        ui.label('此操作不可撤销，将删除该说话人的所有声纹数据。').style(
            f'color: {TEXT_SEC}; font-size: 12px; margin-bottom: 16px;'
        )
        with ui.row().classes('justify-end gap-2'):
            ui.button('取消', on_click=dialog.close).props('flat').style(
                f'color: {TEXT_SEC};'
            )
            ui.button('删除', on_click=lambda: (dialog.close(), _delete_speaker(name))).props(
                'flat'
            ).style(
                f'background: {ERROR}; color: white; border-radius: 8px; '
                f'padding: 6px 16px;'
            )
    dialog.open()


# ------------------------------------------------------------------
# Card 2: New Registration
# ------------------------------------------------------------------

def _new_registration_card():
    """Card for starting a new speaker enrollment."""

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px;'
    ):
        ui.label('新建注册').style(
            f'color: {TEXT_MAIN}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 12px;'
        )

        # Name input
        name_input = ui.input(
            label='说话人名称',
            placeholder='例如: 张三',
        ).props('dense outlined dark').style(
            f'width: 250px; font-size: 13px; margin-bottom: 8px;'
        )

        # Sample count input
        with ui.row().classes('items-end gap-4'):
            sample_input = ui.number(
                label='采集样本数',
                value=5,
                min=3,
                max=20,
            ).props('dense outlined dark').style(
                f'width: 140px; font-size: 13px;'
            ).tooltip('建议采集 5 个以上样本以获得较好的识别效果')

            # Start button
            ui.button(
                '开始采集',
                icon='mic',
                on_click=lambda: _start_enrollment(name_input.value, sample_input.value),
            ).props('flat').style(
                f'background: {ACCENT}; color: white; border-radius: 8px; '
                f'padding: 8px 20px;'
            )

        ui.label(
            '注册时请在安静环境中，对着麦克风清晰说话。每个样本需说 2-5 秒。'
        ).style(
            f'color: {TEXT_SEC}; font-size: 11px; margin-top: 12px; '
            f'font-style: italic;'
        )


# ------------------------------------------------------------------
# Card 3: Diarize Session Speakers
# ------------------------------------------------------------------

def _diarize_card():
    """Card showing current session's diarized speakers with rename support."""

    cluster = app_state.speaker_cluster
    speakers = cluster.get_speakers()

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px; border: 1px solid {ACCENT};'
    ):
        ui.label('当前会话说话人').style(
            f'color: {ACCENT}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 4px;'
        )
        ui.label('说话人分离模式 — 自动检测到的说话人').style(
            f'color: {TEXT_SEC}; font-size: 12px; margin-bottom: 12px;'
        )

        if not speakers:
            ui.label('尚未检测到说话人，开始录音后将自动识别。').style(
                f'color: {TEXT_SEC}; font-size: 13px; font-style: italic; '
                f'padding: 16px 0;'
            )
        else:
            for idx, spk in enumerate(speakers):
                _diarize_speaker_row(idx, spk)

        # Reset button
        if speakers:
            ui.separator().style('margin: 12px 0; opacity: 0.2;')

            def _reset_cluster():
                cluster.reset()
                ui.notify('已重置说话人聚类', type='info')
                ui.navigate.to('/speakers')

            ui.button('重置聚类', icon='refresh', on_click=_reset_cluster).props(
                'flat dense'
            ).style(f'color: {WARNING}; font-size: 12px;')

    # Auto-refresh timer to pick up new speakers
    initial_count = len(speakers)

    def _poll_diarize():
        if app_state.speaker_cluster is None:
            return
        current = len(app_state.speaker_cluster.get_speakers())
        if current != initial_count:
            ui.navigate.to('/speakers')

    ui.timer(2.0, _poll_diarize)


def _diarize_speaker_row(idx, spk):
    """Single diarized speaker row with rename support."""
    color = SPEAKER_COLORS[idx % len(SPEAKER_COLORS)]
    name = spk['name']
    count = spk['count']

    with ui.row().classes('items-center w-full no-wrap').style(
        f'padding: 8px 0; border-bottom: 1px solid #2a2a3e;'
    ):
        # Color avatar
        ui.element('div').style(
            f'width: 32px; height: 32px; border-radius: 8px; '
            f'background: {color}; flex-shrink: 0; '
            f'display: flex; align-items: center; justify-content: center; '
            f'color: white; font-weight: 600; font-size: 13px;'
        ).props(f'innerHTML="{name[0] if name else "?"}"')

        # Name and count
        with ui.column().style('flex: 1; gap: 2px; margin-left: 12px;'):
            ui.label(name).style(
                f'color: {TEXT_MAIN}; font-size: 14px; font-weight: 500;'
            )
            ui.label(f'{count} 段语音').style(
                f'color: {TEXT_SEC}; font-size: 11px;'
            )

        # Rename button
        def _rename_dialog(old_name=name):
            with ui.dialog() as dialog, ui.card().style(
                f'background: {CARD_BG}; border-radius: 12px; padding: 20px;'
            ):
                ui.label(f'重命名 "{old_name}"').style(
                    f'color: {TEXT_MAIN}; font-size: 14px; margin-bottom: 12px;'
                )
                name_input = ui.input(
                    label='新名称', placeholder='例如: 张三',
                ).props('dense outlined dark autofocus').style('width: 220px;')

                def _do_rename():
                    new_name = name_input.value.strip()
                    if not new_name:
                        ui.notify('请输入名称', type='warning')
                        return
                    if app_state.speaker_cluster and app_state.speaker_cluster.rename(old_name, new_name):
                        # Update existing transcription results
                        for r in app_state.transcription_results:
                            if r.get('speaker') == old_name:
                                r['speaker'] = new_name
                        ui.notify(f'已重命名: {old_name} → {new_name}', type='positive')
                        dialog.close()
                        ui.navigate.to('/speakers')
                    else:
                        ui.notify('重命名失败（名称冲突或不存在）', type='negative')

                with ui.row().classes('justify-end gap-2').style('margin-top: 12px;'):
                    ui.button('取消', on_click=dialog.close).props('flat').style(
                        f'color: {TEXT_SEC};'
                    )
                    ui.button('确认', on_click=_do_rename).props('flat').style(
                        f'background: {ACCENT}; color: white; border-radius: 8px; '
                        f'padding: 6px 16px;'
                    )
            dialog.open()

        ui.button(icon='edit', on_click=_rename_dialog).props(
            'flat dense round'
        ).style(f'color: {ACCENT}; opacity: 0.7;').tooltip('重命名')
