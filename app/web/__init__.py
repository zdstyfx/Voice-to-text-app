"""Vocotype NiceGUI Web UI entry point."""
from nicegui import ui, app
from app.web.components.sidebar import sidebar
from app.web.pages.transcribe import transcribe_page
from app.web.pages.esp32 import esp32_page
from app.web.pages.speakers import speakers_page
from app.web.pages.settings import settings_page
from app.web.state import app_state

GLOBAL_CSS = """
body {
    background: #16161e !important;
    font-family: 'Microsoft YaHei UI', system-ui, -apple-system, sans-serif !important;
    color: #e0e0e0 !important;
    margin: 0;
    padding: 0;
}
/* Remove default NiceGUI page padding */
.nicegui-content {
    padding: 0 !important;
}
/* Quasar dark overrides */
.q-page, .q-layout, .q-page-container {
    background: #16161e !important;
}
/* Scrollbar styling */
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: #16161e;
}
::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #555;
}
"""


def create_page_layout(content_fn):
    """Wrap a page content function with sidebar + main content layout."""
    # Enable dark mode
    ui.dark_mode(True)

    # Inject global styles
    ui.add_css(GLOBAL_CSS)

    # Set primary color
    ui.colors(primary='#646cff')

    # Main layout: sidebar on left, content area fills remaining space
    with ui.row().classes('w-full h-screen no-wrap').style(
        'margin: 0; padding: 0; gap: 0;'
    ):
        # Sidebar (fixed 200px)
        sidebar()

        # Main content area (fills remaining width)
        with ui.column().classes('flex-grow h-screen').style(
            'background: #16161e; padding: 24px 32px; overflow-y: auto; '
            'min-width: 0;'
        ):
            content_fn()


def start_web_ui(config: dict):
    """Start the NiceGUI web server.

    Args:
        config: Application configuration dictionary.
    """
    # Store config in shared state for pages to access
    app_state.config = config

    # -- Register page routes --

    @ui.page('/')
    def index():
        create_page_layout(transcribe_page)

    @ui.page('/esp32')
    def esp32():
        create_page_layout(esp32_page)

    @ui.page('/speakers')
    def speakers():
        create_page_layout(speakers_page)

    @ui.page('/settings')
    def settings_pg():
        create_page_layout(settings_page)

    ui.run(title='Vocotype', port=8080, reload=False)
