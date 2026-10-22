"""Tiny JSON settings file stored in the user's config folder (never leaves the machine)."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

THEMES = ("dark", "light")


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "StripSafe" / "settings.json"


@dataclass
class Settings:
    theme: str = "dark"
    quality: int = 2                  # index into the quality slider steps
    output_dir: Optional[str] = None  # None means next to the originals

    def normalized(self) -> "Settings":
        if self.theme not in THEMES:
            self.theme = "dark"
        self.quality = min(3, max(0, int(self.quality)))
        if self.output_dir is not None and not isinstance(self.output_dir, str):
            self.output_dir = None
        return self


def load(path: Optional[Path] = None) -> Settings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in Settings.__dataclass_fields__}
        return Settings(**known).normalized()
    except Exception:
        return Settings()


def save(settings: Settings, path: Optional[Path] = None) -> None:
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    except OSError:
        pass  # settings are a convenience; never fail the app over them
