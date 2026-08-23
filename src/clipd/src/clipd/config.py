"""Flat INI config at ~/.config/clipd/config.ini, written back on change.

Fields on the dataclass are the single source of truth: load() coerces by
field type, save() writes every field, and the settings UI edits attributes
directly. Unknown keys in the file are ignored, missing ones default.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, fields
from pathlib import Path

_SECTION = "clipd"


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "clipd" / "config.ini"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "clipd"


def db_path() -> Path:
    return data_dir() / "history.sqlite3"


@dataclass
class Config:
    history_cap: int = 500
    capture_images: bool = True
    max_text_bytes: int = 1_000_000
    max_image_bytes: int = 16_000_000
    auto_paste: bool = True
    terminal_shift_paste: bool = True  # Ctrl+Shift+V when a terminal is focused
    hide_on_focus_loss: bool = True
    window_width: int = 640
    window_height: int = 480

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        parser = configparser.ConfigParser()
        parser.read(path)
        cfg = cls()
        if not parser.has_section(_SECTION):
            return cfg
        section = parser[_SECTION]
        for field in fields(cls):
            if field.name not in section:
                continue
            try:
                if field.type == "bool":
                    setattr(cfg, field.name, section.getboolean(field.name))
                elif field.type == "int":
                    setattr(cfg, field.name, section.getint(field.name))
            except ValueError:
                pass  # malformed value: keep the default
        return cfg

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        parser = configparser.ConfigParser()
        parser[_SECTION] = {f.name: str(getattr(self, f.name)) for f in fields(self)}
        tmp = path.with_suffix(".ini.tmp")
        with open(tmp, "w") as fh:
            parser.write(fh)
        tmp.replace(path)
