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

# Module-level enrollment state (transient, not persisted)
_enrollment_active = False
_enrollment_name = ''
_enrollment_target_samples = 5
_enrollment_collected = 0
_enrollment_worker = None


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


def _stop_enrollment():
    """Stop any active enrollment and clean up."""
    global _enrollment_active, _enrollment_worker, _enrollment_collected
    if _enrollment_worker is not None:
        try:
            _enrollment_worker.stop()
            _enrollment_worker.cleanup()
        except Exception as exc:
            logger.error("Enrollment worker cleanup error: %s", exc)
        _enrollment_worker = None
    _enrollment_active = False
    _enrollment_collected = 0


def _start_enrollment(name, num_samples):
    """Start voice enrollment process using VadTranscriptionWorker in enroll mode."""
    global _enrollment_active, _enrollment_name, _enrollment_target_samples
    global _enrollment_collected, _enrollment_worker

    if not name or not name.strip():
        ui.notify('请输入说话人名称', type='negative')
        return
    name = name.strip()

    # Check for duplicate names
    db = _get_speaker_db()
    if name in db.list_speakers():
        ui.notify(f'说话人 "{name}" 已存在，请使用其他名称', type='negative')
        return

    _enrollment_name = name
    _enrollment_target_samples = int(num_samples)
    _enrollment_collected = 0
    _enrollment_active = True

    # Set up speaker processor if needed
    if app_state.speaker_processor is None:
        try:
            from app.speaker import SpeakerProcessor
            app_state.speaker_processor = SpeakerProcessor(app_state.config)
        except Exception as exc:
            logger.error("Failed to initialize SpeakerProcessor: %s", exc)
            ui.notify(f'声纹模型加载失败: {exc}', type='negative')
            _enrollment_active = False
            return

    # Configure enrollment target in config
    app_state.config.setdefault('speaker', {})['enroll_target'] = name
    app_state.config['speaker']['enroll_samples'] = _enrollment_target_samples

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
            _enrollment_active = False
            return

    # Create VadTranscriptionWorker in enroll mode
    try:
        from app.vad_worker import VadTranscriptionWorker
        _enrollment_worker = VadTranscriptionWorker(
            on_result=None,  # Enrollment doesn't produce transcription results
            audio_source=app_state.audio,
            speaker_processor=app_state.speaker_processor,
            speaker_mode='enroll',
        )
        _enrollment_worker.start()
        logger.info("Enrollment started for '%s' (%d samples)", name, _enrollment_target_samples)
    except Exception as exc:
        logger.error("Failed to start enrollment worker: %s", exc)
        ui.notify(f'采集启动失败: {exc}', type='negative')
        _enrollment_active = False
        _enrollment_worker = None
        return

    # Refresh page to show enrollment UI
    ui.navigate.to('/speakers')


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

    # ---- 2. Enrollment flow or new registration card ----
    if _enrollment_active:
        _enrollment_card()
    else:
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
# Card 3: Enrollment Flow (shown when enrolling)
# ------------------------------------------------------------------

def _enrollment_card():
    """Card showing enrollment progress with live sample collection."""
    global _enrollment_collected

    with ui.element('div').style(
        f'background: {CARD_BG}; border-radius: 12px; padding: 20px 24px; '
        f'margin-bottom: 16px; border: 1px solid {ACCENT};'
    ):
        ui.label('声纹采集中').style(
            f'color: {ACCENT}; font-size: 16px; font-weight: 600; '
            f'margin-bottom: 8px;'
        )

        ui.label(
            f'正在采集 {_enrollment_name} 的声纹样本...'
        ).style(
            f'color: {TEXT_MAIN}; font-size: 14px; margin-bottom: 16px;'
        )

        # Progress bar
        progress_label = ui.label(
            f'{_enrollment_collected} / {_enrollment_target_samples} 样本'
        ).style(
            f'color: {TEXT_SEC}; font-size: 13px; margin-bottom: 6px;'
        )

        progress_bar = ui.linear_progress(
            value=_enrollment_collected / max(_enrollment_target_samples, 1),
            show_value=False,
        ).props('rounded').style(
            f'height: 8px; margin-bottom: 16px;'
        )

        # Instructions
        ui.label('请对着麦克风说话，系统会自动检测并采集声纹样本。').style(
            f'color: {TEXT_SEC}; font-size: 12px; margin-bottom: 12px;'
        )

        # Status indicator (animated)
        status_label = ui.label('等待语音输入...').style(
            f'color: {WARNING}; font-size: 13px; margin-bottom: 16px;'
        )

        # Cancel button
        ui.button(
            '取消采集',
            icon='stop',
            on_click=lambda: (_stop_enrollment(), ui.navigate.to('/speakers')),
        ).props('flat').style(
            f'background: {ERROR}; color: white; border-radius: 8px; '
            f'padding: 8px 20px;'
        )

        # Timer to poll enrollment progress from the worker
        def _poll_enrollment():
            global _enrollment_collected, _enrollment_active, _enrollment_worker

            if not _enrollment_active or _enrollment_worker is None:
                return

            # Poll the worker's enroll count
            try:
                current_count = _enrollment_worker._enroll_count
            except Exception:
                current_count = _enrollment_collected

            if current_count != _enrollment_collected:
                _enrollment_collected = current_count
                ratio = _enrollment_collected / max(_enrollment_target_samples, 1)
                progress_bar.value = ratio
                progress_label.text = f'{_enrollment_collected} / {_enrollment_target_samples} 样本'
                status_label.text = f'已采集第 {_enrollment_collected} 个样本'
                status_label.style(f'color: {SUCCESS}; font-size: 13px; margin-bottom: 16px;')

            # Check if enrollment is complete
            # The worker switches to "filter" mode when done
            try:
                worker_mode = _enrollment_worker._speaker_mode
            except Exception:
                worker_mode = 'enroll'

            if worker_mode != 'enroll' or _enrollment_collected >= _enrollment_target_samples:
                # Enrollment complete
                _stop_enrollment()
                ui.notify(
                    f'声纹注册完成: {_enrollment_name} ({_enrollment_collected} 样本)',
                    type='positive',
                )
                ui.navigate.to('/speakers')

        ui.timer(0.5, _poll_enrollment)
