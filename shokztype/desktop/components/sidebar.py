"""Sidebar navigation component for the Vocotype Web UI."""
from nicegui import ui

SPEAKER_COLORS = ['#4ade80', '#60a5fa', '#f97316', '#a78bfa', '#fb7185', '#fbbf24']

NAV_ITEMS = [
    {'label': '语音转写', 'icon': 'mic', 'path': '/'},
    {'label': 'ESP32 麦克风', 'icon': 'wifi', 'path': '/esp32'},
    {'label': '声纹管理', 'icon': 'person', 'path': '/speakers'},
]

ACCENT = '#646cff'
SIDEBAR_BG = '#1a1a2e'
HOVER_BG = 'rgba(100, 108, 255, 0.1)'
ACTIVE_BG = 'rgba(100, 108, 255, 0.18)'


def _nav_button(label: str, icon: str, path: str, current_path: str):
    """Render a single navigation item."""
    is_active = current_path == path
    bg = ACTIVE_BG if is_active else 'transparent'
    left_border = f'3px solid {ACCENT}' if is_active else '3px solid transparent'
    text_color = ACCENT if is_active else '#b0b0c0'

    with ui.element('div').classes('w-full cursor-pointer').style(
        f'background: {bg}; border-left: {left_border}; '
        f'padding: 10px 16px; transition: background 0.15s;'
    ).on('click', lambda p=path: ui.navigate.to(p)) as row:
        # Add hover effect
        row.on('mouseenter', lambda e, r=row: r.style(f'background: {HOVER_BG if not is_active else ACTIVE_BG}'))
        row.on('mouseleave', lambda e, r=row, bg=bg: r.style(f'background: {bg}'))
        with ui.row().classes('items-center gap-3 no-wrap'):
            ui.icon(icon).style(f'color: {text_color}; font-size: 20px;')
            ui.label(label).style(f'color: {text_color}; font-size: 14px; font-weight: 500;')


def sidebar():
    """Left sidebar navigation component (~200px wide)."""
    # Detect current page path from client connection
    try:
        current_path = ui.context.client.page.path
    except Exception:
        current_path = '/'

    with ui.column().classes('h-screen justify-between').style(
        f'width: 200px; min-width: 200px; max-width: 200px; '
        f'background: {SIDEBAR_BG}; padding: 0; margin: 0; '
        f'border-right: 1px solid rgba(255,255,255,0.06);'
    ):
        # -- Top section: brand + nav items --
        with ui.column().classes('w-full gap-0'):
            # Brand area
            with ui.element('div').classes('w-full').style(
                'padding: 24px 20px 20px 20px; margin-bottom: 8px;'
            ):
                ui.label('Vocotype').style(
                    f'color: {ACCENT}; font-size: 22px; font-weight: 700; '
                    f'letter-spacing: 0.5px;'
                )

            # Navigation items
            for item in NAV_ITEMS:
                _nav_button(item['label'], item['icon'], item['path'], current_path)

        # -- Bottom section: Settings --
        with ui.column().classes('w-full gap-0').style('padding-bottom: 12px;'):
            ui.separator().style('background: rgba(255,255,255,0.06); margin: 0 12px 4px 12px;')
            _nav_button('设置', 'settings', '/settings', current_path)
