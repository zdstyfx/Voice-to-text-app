"""Tests for desktop icon path resolution."""

import sys
from pathlib import Path

import shokztype.__main__ as app_main


def test_get_icon_path_uses_source_tree(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    icon = repo / "shokztype" / "assets" / "shokztype.ico"
    icon.parent.mkdir(parents=True)
    icon.touch()

    monkeypatch.setattr(app_main, "__file__", str(repo / "shokztype" / "__main__.py"))
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert Path(app_main._get_icon_path()) == icon


def test_get_icon_path_uses_pyinstaller_internal_dir(monkeypatch, tmp_path):
    exe_dir = tmp_path / "ShokzType"
    icon = exe_dir / "_internal" / "shokztype" / "assets" / "shokztype.ico"
    icon.parent.mkdir(parents=True)
    icon.touch()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "ShokzType.exe"))

    assert Path(app_main._get_icon_path()) == icon
