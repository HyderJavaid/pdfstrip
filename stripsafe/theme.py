"""Dark and light palettes and the Qt style sheet built from them."""

from dataclasses import dataclass


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


def blend(c1: str, c2: str, t: float) -> str:
    """Mix two #RRGGBB colours; t=0 gives c1, t=1 gives c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def qss(p: Palette) -> str:
    return f"""
* {{ outline: 0; }}
QMainWindow, QWidget#root, QWidget#page, QStackedWidget {{ background: {p.bg}; }}
QWidget {{ color: {p.text}; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
QLabel#logo {{ font-size: 15pt; font-weight: 700; }}
QLabel#bold {{ font-weight: 600; }}
QLabel#muted {{ color: {p.muted}; }}
QLabel#small {{ color: {p.muted}; font-size: 9pt; }}
QLabel#success {{ color: {p.success}; }}
QLabel#danger {{ color: {p.danger}; }}
QLabel#value {{ font-size: 12pt; font-weight: 600; }}

QFrame#sidebar {{ background: {p.surface}; border: none; border-right: 1px solid {p.border}; }}
QFrame#sidebar QLabel {{ background: transparent; }}
QFrame#localNote {{ background: {p.bg}; border: 1px solid {p.border}; border-radius: 0px; }}
QFrame#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#inset {{ background: {p.surface2}; border: none; border-radius: 8px; }}
QFrame#divider {{ background: {p.border}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#dropzone {{ background: {p.surface}; border: 1.5px dashed {p.border}; border-radius: 14px; }}
QFrame#dropzone[active="true"] {{ border-color: {p.accent}; }}

QPushButton {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 8px 18px; }}
QPushButton:hover {{ background: {p.surface2}; }}
QPushButton:disabled {{ color: {p.muted}; }}
QPushButton[variant="primary"] {{ background: {p.accent}; border-color: {p.accent}; color: {p.on_accent};
    font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {blend(p.surface, p.accent, .35)};
    border-color: {blend(p.surface, p.accent, .35)}; color: {blend(p.surface, p.on_accent, .75)}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {p.muted};
    padding: 5px 10px; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface2}; color: {p.text}; }}
QPushButton[variant="seg"]:checked {{ background: {p.accent}; border-color: {p.accent}; color: {p.on_accent}; }}

QPushButton#nav {{ background: transparent; border: none; border-left: 3px solid transparent; border-radius: 0px;
    text-align: left; padding: 11px 16px; color: {p.muted}; margin: 0px 0px; }}
QPushButton#nav:hover {{ background: {p.surface2}; }}
QPushButton#nav:checked {{ background: {p.surface2}; border-left: 3px solid {p.accent}; color: {p.text};
    font-weight: 600; }}
QPushButton#tab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
    border-radius: 0px; padding: 6px 2px; color: {p.muted}; }}
QPushButton#tab:checked {{ border-bottom: 2px solid {p.accent}; color: {p.text}; font-weight: 600; }}

QLabel#path {{ background: {p.surface2}; border-radius: 8px; padding: 8px 12px; }}

QTableView {{ background: {p.surface}; border: none; gridline-color: transparent; selection-background-color: transparent;
    outline: 0; }}
QHeaderView {{ background: {p.surface2}; border: none; }}
QHeaderView::section {{ background: {p.surface2}; color: {p.muted}; border: none; padding: 7px 4px; font-size: 9pt; }}
QHeaderView::section:first {{ padding-left: 44px; }}

QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.accent}; border: 2px solid {p.bg}; width: 12px; height: 12px;
    margin: -8px 0; border-radius: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0; }}
QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border}; padding: 4px; }}
"""
