"""Vocotype NiceGUI Web UI entry point."""
from nicegui import ui


def start_web_ui(config: dict):
    """Start the NiceGUI web server."""
    # Will be fully implemented in Task 2
    ui.run(title='Vocotype', port=8080)
