"""Dark and light palettes plus font selection."""

from dataclasses import dataclass
from tkinter import font as tkfont


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    on_accent: str
    success: str
    danger: str


DARK = Palette(
    name="dark", bg="#0F1115", surface="#171A21", surface2="#1F232C", border="#2B303B",
    text="#E8EAF0", muted="#8B92A1", accent="#6D7DFF", accent_hover="#8290FF", on_accent="#FFFFFF",
    success="#3DD68C", danger="#FF6B6B",
)
LIGHT = Palette(
    name="light", bg="#F4F5F8", surface="#FFFFFF", surface2="#EEF0F5", border="#DDE0E8",
    text="#14171F", muted="#6A7080", accent="#4F5BD5", accent_hover="#3F4BC2", on_accent="#FFFFFF",
    success="#13905A", danger="#D13F3F",
)
PALETTES = {"dark": DARK, "light": LIGHT}

_PREFERRED = ("Inter", "Segoe UI", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans", "Helvetica", "Arial")


def pick_family(root) -> str:
    available = set(tkfont.families(root))
    return next((f for f in _PREFERRED if f in available), tkfont.nametofont("TkDefaultFont").actual("family"))


def make_fonts(root) -> dict:
    fam = pick_family(root)
    return {
        "base": tkfont.Font(root, family=fam, size=10),
        "small": tkfont.Font(root, family=fam, size=9),
        "bold": tkfont.Font(root, family=fam, size=10, weight="bold"),
        "h1": tkfont.Font(root, family=fam, size=20, weight="bold"),
        "h2": tkfont.Font(root, family=fam, size=12, weight="bold"),
        "logo": tkfont.Font(root, family=fam, size=15, weight="bold"),
    }
