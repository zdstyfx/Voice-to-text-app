"""Launch the Vocotype Web UI without loading ML/ASR models."""
from app.config import DEFAULT_CONFIG
from app.web import start_web_ui

if __name__ == "__main__":
    start_web_ui(DEFAULT_CONFIG)
