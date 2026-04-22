"""Transcript display component for the Vocotype Web UI."""

from nicegui import ui

from shokztype.desktop.state import app_state

SPEAKER_COLORS = ['#4ade80', '#60a5fa', '#f97316', '#a78bfa', '#fb7185', '#fbbf24']

# Map speaker names to colors by order of first appearance
_speaker_color_map: dict[str, str] = {}


def _color_for_speaker(name: str) -> str:
    """Return a stable colour for a speaker name."""
    if name not in _speaker_color_map:
        idx = len(_speaker_color_map) % len(SPEAKER_COLORS)
        _speaker_color_map[name] = SPEAKER_COLORS[idx]
    return _speaker_color_map[name]


def _confidence_style(confidence: float) -> tuple[str, str]:
    """Return (background, text) colour for a confidence value."""
    if confidence >= 0.8:
        return ('rgba(74, 222, 128, 0.18)', '#4ade80')
    if confidence >= 0.5:
        return ('rgba(251, 191, 36, 0.18)', '#fbbf24')
    return ('rgba(239, 68, 68, 0.18)', '#ef4444')


def transcript():
    """Transcript result display -- document-flow style with auto-scroll."""

    # Scrollable container
    scroll_container = ui.column().classes('w-full gap-2').style(
        'flex: 1 1 0; min-height: 200px; overflow-y: auto; '
        'padding: 12px; background: #1a1a2e; border-radius: 10px;'
    )

    # We keep track of how many results we have already rendered so the
    # timer only adds the new ones.
    rendered_count = {'n': 0}

    def _render_result(r: dict):
        """Add one transcript result row to the scroll container."""
        with scroll_container:
            with ui.row().classes('items-start gap-2 w-full no-wrap').style(
                'padding: 6px 4px; border-bottom: 1px solid rgba(255,255,255,0.04);'
            ):
                # Speaker badge
                if r.get('speaker'):
                    color = _color_for_speaker(r['speaker'])
                    label = r['speaker']
                    if r.get('speaker_confidence') is not None:
                        label += f' {r["speaker_confidence"]:.0%}'
                    ui.label(label).style(
                        f'background: {color}22; color: {color}; '
                        f'font-size: 11px; padding: 1px 8px; border-radius: 10px; '
                        f'white-space: nowrap;'
                    )

                # Timestamp
                ui.label(r.get('timestamp', '')).style(
                    'color: #666; font-size: 11px; white-space: nowrap; min-width: 55px;'
                )

                # Confidence badge
                conf = r.get('confidence', 0)
                bg, fg = _confidence_style(conf)
                ui.label(f'{conf:.0%}').style(
                    f'background: {bg}; color: {fg}; font-size: 10px; '
                    f'padding: 1px 6px; border-radius: 8px; white-space: nowrap;'
                )

                # Transcription text
                ui.label(r.get('text', '')).style(
                    'color: #e0e0e0; font-size: 14px; line-height: 1.5; '
                    'word-break: break-word; flex: 1;'
                )

    def _check_new_results():
        """Periodically called by a timer to render newly arrived results."""
        total = len(app_state.transcription_results)
        if total <= rendered_count['n']:
            return
        # Render any results added since last check
        for r in app_state.transcription_results[rendered_count['n']:]:
            _render_result(r)
        rendered_count['n'] = total
        # Auto-scroll the container to the bottom
        ui.run_javascript(
            '''
            const el = document.querySelector('[style*="min-height: 200px"]');
            if (el) el.scrollTop = el.scrollHeight;
            '''
        )

    # Timer -- poll for new transcription results every 0.5s
    ui.timer(0.5, _check_new_results)

    # Empty-state placeholder (will be covered once results arrive)
    if not app_state.transcription_results:
        with scroll_container:
            with ui.column().classes('items-center justify-center w-full').style(
                'padding: 48px 0;'
            ):
                ui.icon('subtitles').style('font-size: 48px; color: #333;')
                ui.label('等待转写结果...').style(
                    'color: #555; font-size: 14px; margin-top: 8px;'
                )
    else:
        # Render existing results
        for r in app_state.transcription_results:
            _render_result(r)
        rendered_count['n'] = len(app_state.transcription_results)
