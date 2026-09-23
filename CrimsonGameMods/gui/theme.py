from __future__ import annotations
import base64 as _b64

# Every palette carries the same keys. Besides the base colours there are
# tab colours and button roles: buttons get their colour from what they do
# (primary / success / warn / danger / neutral), not a fixed hex per button,
# so every theme colours them consistently. See button_css().

# GitHub Dark - the default since v2.2.1.
DARK_COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "header": "#21262d",
    "accent": "#2f81f7",
    "accent_hover": "#58a6ff",
    "on_accent": "#ffffff",
    "text": "#e6edf3",
    "text_dim": "#8b949e",
    "selected": "#1f3a5f",
    "border": "#30363d",
    "input_bg": "#0a0d12",
    "success": "#3fb950",
    "warning": "#d29922",
    "error": "#f85149",
    "scope_save": "#58a6ff",
    "scope_game": "#d29922",
    "tab_bg": "#1f2a3a",
    "tab_text": "#ffffff",
    "tab_border": "#2f81f7",
    "btn_primary": ("#1f6feb", "#ffffff", "#388bfd"),
    "btn_success": ("#238636", "#ffffff", "#2ea043"),
    "btn_warn": ("#3b2e0a", "#e3b341", "#9e6a03"),
    "btn_danger": ("#2a1517", "#ff7b72", "#da3633"),
    "btn_neutral": ("#21262d", "#e6edf3", "#30363d"),
}

# The brown / gold look the tool had up to v2.2.0, kept as an option.
CLASSIC_COLORS = {
    "bg": "#1a1510",
    "panel": "#272018",
    "header": "#3d2e1a",
    "accent": "#daa850",
    "accent_hover": "#e8b85e",
    "on_accent": "#1a1510",
    "text": "#f0e6d4",
    "text_dim": "#b0a088",
    "selected": "#5c4320",
    "border": "#554430",
    "input_bg": "#1e1610",
    "success": "#9cc470",
    "warning": "#f0b040",
    "error": "#d44f40",
    "scope_save": "#4FC3F7",
    "scope_game": "#FFB74D",
    "tab_bg": "#2a3040",
    "tab_text": "#e0eaff",
    "tab_border": "#70a8ff",
    "btn_primary": ("#1565C0", "#ffffff", "#1565C0"),
    "btn_success": ("#2E7D32", "#ffffff", "#2E7D32"),
    "btn_warn": ("#F9A825", "#1a1510", "#F9A825"),
    "btn_danger": ("#B71C1C", "#ffffff", "#B71C1C"),
    "btn_neutral": ("#3d2e1a", "#f0e6d4", "#554430"),
}

# GitHub Light, high contrast.
LIGHT_COLORS = {
    "bg": "#f6f8fa",
    "panel": "#ffffff",
    "header": "#eaeef2",
    "accent": "#0969da",
    "accent_hover": "#0550ae",
    "on_accent": "#ffffff",
    "text": "#1f2328",
    "text_dim": "#57606a",
    "selected": "#b6e3ff",
    "border": "#afb8c1",
    "input_bg": "#ffffff",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "error": "#cf222e",
    "scope_save": "#0550ae",
    "scope_game": "#bc4c00",
    "tab_bg": "#ddf4ff",
    "tab_text": "#0a3069",
    "tab_border": "#0969da",
    "btn_primary": ("#0969da", "#ffffff", "#0550ae"),
    "btn_success": ("#1f883d", "#ffffff", "#1a7f37"),
    "btn_warn": ("#fff8c5", "#7d4e00", "#d4a72c"),
    "btn_danger": ("#ffebe9", "#a40e26", "#cf222e"),
    "btn_neutral": ("#eaeef2", "#1f2328", "#afb8c1"),
}

THEMES = {
    "dark": ("GitHub Dark (default)", DARK_COLORS),
    "classic": ("Classic (brown / gold)", CLASSIC_COLORS),
    "light": ("Light (high contrast)", LIGHT_COLORS),
}


def palette(mode: str) -> dict:
    return THEMES.get(mode, THEMES["dark"])[1]


# Active palette — mutated by apply_theme() so existing `COLORS[...]` reads
# during runtime pick up the new values after a switch. Widgets that inline-
# style via COLORS['x'] update on next repaint; widgets baked into the
# compiled stylesheet update immediately via setStyleSheet().
COLORS = dict(DARK_COLORS)

CATEGORY_COLORS = {
    "Equipment": "#d4a24e",
    "Material": "#c9b458",
    "Quest": "#e8a838",
    "Currency": "#dbb742",
    "Consumable": "#8cb369",
    "Ammo": "#c44536",
    "Misc": "#998b72",
}

# Kept for imports elsewhere; the live values are COLORS['tab_*'].
_TAB_SELECTED_BG = DARK_COLORS["tab_bg"]
_TAB_SELECTED_COLOR = DARK_COLORS["tab_text"]
_TAB_SELECTED_BORDER = DARK_COLORS["tab_border"]


# Qt style sheets cannot load data: URIs, so small images (combo arrow,
# check mark) are written once to a cache folder and referenced by path.
# Both are PNG, which Qt always reads; SVG would need the SVG plugin.
_CHECK_PNG_LIGHT = "iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAAAvElEQVR4nLXRLW5CQRDA8d0HmBoeTeAcDQ7NOZA9RC22qqfAEiwKRXoDeoKiwWDoD9FpsrzkQRCdZDOZ2fnPZ0r/LcioHoUeAwLqhv7AHE93ExXQzK/sMbgCUcUcuWwPYxxxwMvN1tGJJDW+otrs769ZaYoV6gJeBPQevl4zexfrCPpEH29hb4qYXII53hDbCN7hhG+MWm9YLOS5gH8wuZqrbSGhayzxehdqVi7s1kPnpiPgKqWUcs7nNvACWdcDUSi2Cp0AAAAASUVORK5CYII="
_CHECK_PNG_DARK = "iVBORw0KGgoAAAANSUhEUgAAAA4AAAAOCAYAAAAfSC3RAAABJElEQVR4nL1Su0oDQRQ9M64IIrl39pHM7ubhHwhWAcHGb7BM6Uf4B4KVX2ErASurVGJnmx/IGlKEIILg7l6bWVnWJMTG08zcmXPuPRwu8A9QAPRfRb8EageRByC3Ed0pYAXv8CbLss9dRLABj3odX5KQ3/pEBoCuT9QAxN3F1WUc0qnWagJAROR8tli9rrNeYQ+AGhBxGvG02/HFBjyq/f1MUkmbLtK2GRMRV4Q44Pu+9SUO+da97Te7e3HITwMbSBLxizGG4oive9aXJKLJpeOgFqaqCmuPQlV4Y0/rYV6WUwUcQ2FZqK+T+fxj4XhlXVid0m21/OJAP3paD8tSRPL8bLZ8f3auim2BgIg4jcxDHNJVM4xtaC7ExtjXbU59Jzfa+wZ5OUUhvjEPvAAAAABJRU5ErkJggg=="


def _asset_path(name: str, data: bytes) -> str:
    import os
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "crimson_gamemods_theme")
    path = os.path.join(folder, name)
    try:
        if not os.path.isfile(path):
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
    except OSError:
        return ""
    return path.replace("\\", "/")


def _rgb(fill: str):
    h = fill.lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (230, 237, 243)


def _png(width: int, height: int, rgba_rows) -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(row) for row in rgba_rows)
    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def _combo_arrow_uri(fill: str) -> str:
    """Path of a 10x6 downward triangle in the given colour (4x supersampled)."""
    r, g, b = _rgb(fill)
    w, h, ss = 10, 6, 4
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            hit = 0
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    py = y + (sy + 0.5) / ss
                    half = 5.0 * (1 - py / 6.0)
                    hit += abs(px - 5.0) <= half
            row += [r, g, b, round(255 * hit / (ss * ss))]
        rows.append(row)
    return _asset_path(f"arrow_{r:02x}{g:02x}{b:02x}.png", _png(w, h, rows))


_COMBO_ARROW_URI = _combo_arrow_uri(DARK_COLORS["text"])


def _check_uri(fill: str) -> str:
    r, g, b = _rgb(fill)
    light = (0.299 * r + 0.587 * g + 0.114 * b) > 128
    name = "check_light.png" if light else "check_dark.png"
    return _asset_path(name, _b64.b64decode(_CHECK_PNG_LIGHT if light else _CHECK_PNG_DARK))


def checkbox_css(c: dict, size: int = 16) -> str:
    """Checkbox indicator that is visible on every background: a bordered
    box, filled with the accent colour and a check mark when ticked."""
    return f"""
QCheckBox::indicator {{
    width: {size}px;
    height: {size}px;
    border: 1px solid {c['border']};
    border-radius: 3px;
    background-color: {c['input_bg']};
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}
QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
    image: url("{_check_uri(c['on_accent'])}");
}}
QCheckBox::indicator:disabled {{
    background-color: {c['header']};
}}
"""


def build_stylesheet(c: dict, tab_bg: str, tab_color: str, tab_border: str, arrow_fill: str) -> str:
    arrow = _combo_arrow_uri(arrow_fill)
    return f"""
QMainWindow, QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: Consolas, 'Courier New', monospace;
    font-size: 13px;
}}
QMenuBar {{
    background-color: {c['header']};
    color: {c['text']};
    border-bottom: 1px solid {c['border']};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background-color: {c['selected']};
}}
QMenu {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}
QMenu::item:selected {{
    background-color: {c['selected']};
}}
QTabWidget::pane {{
    border: 1px solid {c['border']};
    background-color: {c['bg']};
}}
QTabBar::tab {{
    background-color: {c['panel']};
    color: {c['text']};
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    border: 1px solid {c['border']};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background-color: {tab_bg};
    color: {tab_color};
    border-bottom: 3px solid {tab_border};
    font-weight: bold;
}}
QTabBar::tab:hover {{
    background-color: {c['selected']};
}}
QTableWidget {{
    background-color: {c['panel']};
    color: {c['text']};
    gridline-color: {c['border']};
    selection-background-color: {c['selected']};
    selection-color: {c['text']};
    border: 1px solid {c['border']};
    font-family: Consolas, monospace;
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 3px 6px;
}}
QHeaderView::section {{
    background-color: {c['header']};
    color: {c['text']};
    padding: 5px 8px;
    border: 1px solid {c['border']};
    font-weight: bold;
}}
QPushButton {{
    background-color: {c['header']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 6px 16px;
    border-radius: 3px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: {c['selected']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background-color: {c['accent']};
}}
QPushButton#accentBtn {{
    background-color: {c['accent']};
    color: {c['on_accent']};
}}
QPushButton#accentBtn:hover {{
    background-color: {c['accent_hover']};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {c['input_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 5px 8px;
    border-radius: 3px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    border-left: 1px solid {c['border']};
    background-color: {c['header']};
    width: 24px;
}}
QComboBox::down-arrow {{
    image: url("{arrow}");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['panel']};
    color: {c['text']};
    selection-background-color: {c['selected']};
    border: 1px solid {c['border']};
}}
QGroupBox {{
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}}
QStatusBar {{
    background-color: {c['header']};
    color: {c['text']};
    border-top: 1px solid {c['border']};
}}
QListWidget {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['selected']};
}}
QTextEdit {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}
QScrollBar:vertical {{
    background-color: {c['bg']};
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {c['bg']};
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QCheckBox {{
    color: {c['text']};
    spacing: 6px;
}}
{checkbox_css(c)}
/* ── Resize handles: visible bars so users know what's draggable ── */
QSplitter::handle {{
    background-color: {c['border']};
    border: 1px solid {c['accent']};
}}
QSplitter::handle:horizontal {{
    width: 6px;
    margin: 2px 1px;
    border-radius: 2px;
}}
QSplitter::handle:vertical {{
    height: 6px;
    margin: 1px 2px;
    border-radius: 2px;
}}
QSplitter::handle:hover {{
    background-color: {c['accent']};
    border-color: {c['text']};
}}
QSplitter::handle:pressed {{
    background-color: {c['scope_save']};
}}

/* Dock separators (between dock widgets and the central widget) */
QMainWindow::separator {{
    background-color: {c['border']};
    width: 5px;
    height: 5px;
}}
QMainWindow::separator:hover {{
    background-color: {c['accent']};
}}

QDockWidget {{
    border: 1px solid {c['border']};
}}
QDockWidget::title {{
    background: {c['header']};
    color: {c['text']};
    padding: 4px 8px;
    border-bottom: 2px solid {c['accent']};
}}
"""

def stylesheet_for(mode: str) -> str:
    c = palette(mode)
    return build_stylesheet(c, c["tab_bg"], c["tab_text"], c["tab_border"], c["text"])


DARK_STYLESHEET = stylesheet_for("dark")
CLASSIC_STYLESHEET = stylesheet_for("classic")
LIGHT_STYLESHEET = stylesheet_for("light")


def apply_theme(app, mode: str) -> str:
    """Apply a theme ('dark', 'classic', 'light') to the QApplication. Also
    mutates the module-level COLORS dict so widgets that read it during
    rebuild pick up the new palette. Returns the stylesheet applied."""
    if mode not in THEMES:
        mode = "dark"
    COLORS.update(palette(mode))
    sheet = stylesheet_for(mode)
    app.setStyleSheet(sheet)
    return sheet


# Old per-button colours -> role. Buttons used to carry a fixed Material
# colour each; the colour roughly meant the same thing everywhere, so it is
# mapped to the role it stood for.
_HEX_ROLE = {
    "1565c0": "primary", "0277bd": "primary", "0d47a1": "primary", "ff4466": "primary",
    "2e7d32": "success", "1b5e20": "success", "00695c": "success",
    "00796b": "success", "006064": "success", "4caf50": "success",
    "f9a825": "warn", "ff8800": "warn",
    "b71c1c": "danger", "cc3333": "danger", "ad1457": "danger", "6a1b1b": "danger",
    "7b1fa2": "neutral", "6a1b9a": "neutral", "4a148c": "neutral",
    "4527a0": "neutral", "37474f": "neutral", "424242": "neutral",
}


def button_css(role: str) -> str:
    """Colour declarations for a button of the given role in the active
    theme: 'primary', 'success', 'warn', 'danger' or 'neutral'. A role name
    may also be one of the old hex colours (e.g. '#1565C0'); it is mapped."""
    role = _HEX_ROLE.get(role.lstrip("#").lower(), role)
    bg, fg, bd = COLORS.get("btn_" + role, COLORS["btn_neutral"])
    return f"background-color: {bg}; color: {fg}; border: 1px solid {bd}; border-radius: 4px;"
