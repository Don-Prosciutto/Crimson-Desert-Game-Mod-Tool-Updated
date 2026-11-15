from __future__ import annotations
import base64 as _b64

# Every palette carries the same keys. Besides the base colours there are
# tab colours and button roles: buttons get their colour from what they do
# (primary / success / warn / danger / neutral), not a fixed hex per button,
# so every theme colours them consistently. See button_css().

# Abyss Teal - deep navy with a teal accent, the default since v2.5.
ABYSS_COLORS = {
    "bg": "#0a101c",
    "panel": "#132036",
    "header": "#182844",
    "accent": "#2dd4bf",
    "accent_hover": "#5eead4",
    "on_accent": "#04211d",
    "text": "#e6eef8",
    "text_dim": "#93a4bd",
    "selected": "#0f3434",
    "border": "#24365a",
    "input_bg": "#0e1626",
    "success": "#5be0a0",
    "warning": "#f5b547",
    "error": "#f87171",
    "scope_save": "#7fb2ff",
    "scope_game": "#f5b547",
    "tab_bg": "#0f3434",
    "tab_text": "#e6eef8",
    "tab_border": "#2dd4bf",
    "btn_primary": ("#2dd4bf", "#04211d", "#2dd4bf"),
    "btn_success": ("#1d5c43", "#e6fff3", "#2f7d5c"),
    "btn_warn": ("#3a2f12", "#f5b547", "#7a5e1e"),
    "btn_danger": ("#3b1a22", "#fca5a5", "#7f2a37"),
    "btn_neutral": ("#182844", "#e6eef8", "#24365a"),
    # new-look extras (other palettes fall back to panel/border)
    "side": "#0e1626",
    "border_soft": "#1e2e4a",
    "alt_row": "#11203a",
    "text_strong": "#ffffff",
}

# Graphite - neutral mid grey, the default from v2.3.0 to v2.4.9.
GRAPHITE_COLORS = {
    "bg": "#2b2d30",
    "panel": "#323438",
    "header": "#3c3f43",
    "accent": "#548af7",
    "accent_hover": "#6d9bf8",
    "on_accent": "#ffffff",
    "text": "#dfe1e5",
    "text_dim": "#a0a3aa",
    "selected": "#2e436e",
    "border": "#4a4d52",
    "input_bg": "#26282b",
    "success": "#6aab73",
    "warning": "#d8ab4e",
    "error": "#f07178",
    "scope_save": "#8fb5f5",
    "scope_game": "#d8ab4e",
    "tab_bg": "#3a4a66",
    "tab_text": "#ffffff",
    "tab_border": "#548af7",
    "btn_primary": ("#3574f0", "#ffffff", "#4a86f7"),
    "btn_success": ("#3d7a45", "#ffffff", "#4e8a55"),
    "btn_warn": ("#4b3f23", "#e3c07a", "#8a6d2b"),
    "btn_danger": ("#4a2c2e", "#f28b82", "#b3413c"),
    "btn_neutral": ("#3c3f43", "#dfe1e5", "#4a4d52"),
}

# GitHub Dark - the default in v2.2.1.
GITHUB_DARK_COLORS = {
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


# Design board direction A - warm bronze and gold on dark brown, fantasy feel.
DESERT_BRONZE_COLORS = {
    "bg": "#15120e",
    "panel": "#221d17",
    "header": "#2a231b",
    "accent": "#d9a441",
    "accent_hover": "#e8b95a",
    "on_accent": "#1a1408",
    "text": "#f3ede4",
    "text_dim": "#b5a994",
    "selected": "#3a2d17",
    "border": "#3f3528",
    "input_bg": "#1b1712",
    "success": "#8bc48a",
    "warning": "#f0a04b",
    "error": "#e5735f",
    "scope_save": "#8fb8e0",
    "scope_game": "#e8b95a",
    "tab_bg": "#3a2d17",
    "tab_text": "#fff6e6",
    "tab_border": "#d9a441",
    "btn_primary": ("#d9a441", "#1a1408", "#d9a441"),
    "btn_success": ("#2f4a2c", "#d4ecd0", "#4a6e46"),
    "btn_warn": ("#3a2d17", "#e8b95a", "#7a5e1e"),
    "btn_danger": ("#3b1d18", "#f2a493", "#7f3a2c"),
    "btn_neutral": ("#2a231b", "#f3ede4", "#3f3528"),
    "side": "#1b1712",
    "border_soft": "#332b21",
    "alt_row": "#1f1a14",
    "text_strong": "#ffffff",
}

# Design board direction C - light mode like an old map: parchment with a
# deep sea-blue accent.
PARCHMENT_COLORS = {
    "bg": "#f3eee4",
    "panel": "#fffdf8",
    "header": "#efe8da",
    "accent": "#1f5f7a",
    "accent_hover": "#174b61",
    "on_accent": "#ffffff",
    "text": "#2a241c",
    "text_dim": "#6b604f",
    "selected": "#dce9ee",
    "border": "#c9bca5",
    "input_bg": "#ffffff",
    "success": "#2e7d4f",
    "warning": "#9a6200",
    "error": "#b3261e",
    "scope_save": "#1f5f7a",
    "scope_game": "#9a5b00",
    "tab_bg": "#dce9ee",
    "tab_text": "#123848",
    "tab_border": "#1f5f7a",
    "btn_primary": ("#1f5f7a", "#ffffff", "#174b61"),
    "btn_success": ("#e3f1e8", "#1e5e39", "#2e7d4f"),
    "btn_warn": ("#fbf0d9", "#7a4d00", "#c99a3a"),
    "btn_danger": ("#fbe7e4", "#9b1c14", "#b3261e"),
    "btn_neutral": ("#efe8da", "#2a241c", "#c9bca5"),
    "side": "#eae3d5",
    "border_soft": "#ddd3c1",
    "alt_row": "#f8f4ec",
    "text_strong": "#17130e",
}

# Design board direction D - neutral slate with an indigo accent.
SLATE_INDIGO_COLORS = {
    "bg": "#0f1115",
    "panel": "#1a1e25",
    "header": "#20252e",
    "accent": "#7c83ff",
    "accent_hover": "#9ba1ff",
    "on_accent": "#0f1115",
    "text": "#e8eaf0",
    "text_dim": "#9aa3b2",
    "selected": "#23264a",
    "border": "#323844",
    "input_bg": "#14171c",
    "success": "#5bd6a2",
    "warning": "#f2b94b",
    "error": "#f87171",
    "scope_save": "#8ab4ff",
    "scope_game": "#f2b94b",
    "tab_bg": "#23264a",
    "tab_text": "#ffffff",
    "tab_border": "#7c83ff",
    "btn_primary": ("#7c83ff", "#0f1115", "#7c83ff"),
    "btn_success": ("#1d4a3a", "#dcfbec", "#2f6e55"),
    "btn_warn": ("#3a2f12", "#f2b94b", "#7a5e1e"),
    "btn_danger": ("#3b1a22", "#fca5a5", "#7f2a37"),
    "btn_neutral": ("#20252e", "#e8eaf0", "#323844"),
    "side": "#14171c",
    "border_soft": "#272c35",
    "alt_row": "#171a20",
    "text_strong": "#ffffff",
}

DARK_COLORS = ABYSS_COLORS

THEMES = {
    "dark": ("Abyss Teal (default)", ABYSS_COLORS),
    "desert_bronze": ("Desert Bronze", DESERT_BRONZE_COLORS),
    "slate_indigo": ("Slate Indigo", SLATE_INDIGO_COLORS),
    "parchment": ("Parchment Light", PARCHMENT_COLORS),
    "graphite": ("Graphite", GRAPHITE_COLORS),
    "github_dark": ("GitHub Dark", GITHUB_DARK_COLORS),
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


def _up_arrow_uri(fill: str) -> str:
    """Path of a 10x6 upward triangle in the given colour (spin boxes)."""
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
                    half = 5.0 * (py / 6.0)
                    hit += abs(px - 5.0) <= half
            row += [r, g, b, round(255 * hit / (ss * ss))]
        rows.append(row)
    return _asset_path(f"arrow_up_{r:02x}{g:02x}{b:02x}.png", _png(w, h, rows))


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
    border-radius: 5px;
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


UI_FONT = "'Segoe UI Variable Text', 'Segoe UI', 'Inter', 'Microsoft YaHei UI', sans-serif"
MONO_FONT = "'Cascadia Mono', Consolas, 'Courier New', monospace"


def build_stylesheet(c: dict, tab_bg: str, tab_color: str, tab_border: str, arrow_fill: str) -> str:
    arrow = _combo_arrow_uri(arrow_fill)
    up_arrow = _up_arrow_uri(arrow_fill)
    side = c.get("side", c["panel"])
    soft = c.get("border_soft", c["border"])
    alt = c.get("alt_row", c["bg"])
    strong = c.get("text_strong", c["text"])
    return f"""
QMainWindow, QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: {UI_FONT};
    font-size: 13px;
}}
QLabel {{
    background: transparent;
}}
QToolTip {{
    background-color: {c['header']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 8px;
}}
QMenuBar {{
    background-color: {side};
    color: {c['text']};
    border-bottom: 1px solid {soft};
    padding: 3px 4px;
}}
QMenuBar::item {{
    padding: 5px 10px;
    border-radius: 6px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background-color: {c['selected']};
}}
QMenu {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {c['selected']};
    color: {strong};
}}
QMenu::separator {{
    height: 1px;
    background: {soft};
    margin: 4px 8px;
}}
QTabWidget::pane {{
    border: 1px solid {soft};
    border-radius: 10px;
    background-color: {c['bg']};
    top: -1px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {c['text_dim']};
    padding: 8px 14px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {strong};
    border-bottom: 2px solid {tab_border};
}}
QTabBar::tab:hover {{
    color: {c['text']};
}}
QTableWidget, QTableView, QTreeWidget, QTreeView {{
    background-color: {c['panel']};
    alternate-background-color: {alt};
    color: {c['text']};
    gridline-color: {soft};
    selection-background-color: {c['selected']};
    selection-color: {strong};
    border: 1px solid {soft};
    border-radius: 10px;
    font-size: 12px;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px 8px;
}}
QHeaderView::section {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid {c['border']};
    border-right: 1px solid {soft};
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {c['panel']};
    border: none;
}}
QHeaderView {{
    background-color: {c['panel']};
    border: none;
}}
QHeaderView::section:vertical {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    padding: 0px 6px;
    border: none;
    border-right: 1px solid {soft};
    font-weight: 500;
}}
QAbstractSpinBox QLineEdit {{
    padding: 0px;
    margin: 0px;
    border: none;
    background: transparent;
}}
QPushButton {{
    background-color: {c['header']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 5px 12px;
    border-radius: 8px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {c['selected']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background-color: {c['accent']};
    color: {c['on_accent']};
}}
QPushButton:disabled {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    border-color: {soft};
}}
QPushButton:checked {{
    background-color: {c['selected']};
    border-color: {c['accent']};
    color: {strong};
}}
QPushButton#chip {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    border: 1px solid {c['border']};
    border-radius: 15px;
    padding: 5px 14px;
    font-weight: 600;
}}
QPushButton#chip:hover {{
    color: {c['text']};
    border-color: {c['accent']};
}}
QPushButton#chip:checked {{
    background-color: {c['selected']};
    color: {strong};
    border-color: {c['accent']};
}}
QFrame#actionBar {{
    background-color: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 12px;
}}
QFrame#actionBar QLabel {{
    background: transparent;
}}
QPushButton#accentBtn {{
    background-color: {c['accent']};
    color: {c['on_accent']};
    border: 1px solid {c['accent']};
}}
QPushButton#accentBtn:hover {{
    background-color: {c['accent_hover']};
    border-color: {c['accent_hover']};
}}
QPushButton#accentBtn:disabled {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    border-color: {soft};
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}}
QToolButton:hover {{
    background-color: {c['selected']};
    border-color: {soft};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background-color: {c['input_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 6px 10px;
    border-radius: 8px;
    selection-background-color: {c['selected']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {c['accent']};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    color: {c['text_dim']};
    background-color: {c['panel']};
}}
QSpinBox, QDoubleSpinBox {{
    padding: 5px 4px 5px 8px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 18px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {c['selected']};
    border-radius: 4px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{up_arrow}");
    width: 8px;
    height: 5px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{arrow}");
    width: 8px;
    height: 5px;
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
    background: transparent;
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
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QGroupBox {{
    color: {c['text']};
    background-color: transparent;
    border: 1px solid {c['border']};
    border-radius: 12px;
    margin-top: 14px;
    padding: 18px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {c['text_dim']};
    background-color: transparent;
}}
QStatusBar {{
    background-color: {side};
    color: {c['text_dim']};
    border-top: 1px solid {soft};
}}
QStatusBar QLabel {{
    color: {c['text_dim']};
}}
QListWidget, QListView {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {soft};
    border-radius: 10px;
    selection-background-color: {c['selected']};
    selection-color: {strong};
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
}}
QTextEdit, QTextBrowser {{
    background-color: {c['panel']};
    color: {c['text']};
    border: 1px solid {soft};
    border-radius: 10px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {c['text_dim']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 3px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {c['text_dim']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QProgressBar {{
    background-color: {c['input_bg']};
    border: 1px solid {soft};
    border-radius: 6px;
    text-align: center;
    color: {c['text']};
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 5px;
}}
QCheckBox, QRadioButton {{
    color: {c['text']};
    spacing: 8px;
    background: transparent;
}}
{checkbox_css(c)}
QSlider::groove:horizontal {{
    height: 4px;
    background: {c['border']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['accent']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
/* ── Resize handles: quiet bars that light up on hover ── */
QSplitter::handle {{
    background-color: {soft};
}}
QSplitter::handle:horizontal {{
    width: 4px;
    margin: 2px 1px;
    border-radius: 2px;
}}
QSplitter::handle:vertical {{
    height: 4px;
    margin: 1px 2px;
    border-radius: 2px;
}}
QSplitter::handle:hover {{
    background-color: {c['accent']};
}}
QSplitter::handle:pressed {{
    background-color: {c['accent_hover']};
}}

/* Dock separators (between dock widgets and the central widget) */
QMainWindow::separator {{
    background-color: {soft};
    width: 4px;
    height: 4px;
}}
QMainWindow::separator:hover {{
    background-color: {c['accent']};
}}

QDockWidget {{
    border: 1px solid {soft};
}}
QDockWidget::title {{
    background: {side};
    color: {c['text']};
    padding: 6px 10px;
    border-bottom: 1px solid {soft};
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
    # Setting the very same sheet again makes Qt re-polish every widget
    # (seconds at start-up) without changing anything.
    if app.styleSheet() != sheet:
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
