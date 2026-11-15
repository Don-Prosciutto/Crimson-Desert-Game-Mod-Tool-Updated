
from __future__ import annotations

import json
import os
import sys
import logging
from typing import Dict, List, Optional, Set, Any

log = logging.getLogger(__name__)

_MY_DIR = os.path.dirname(os.path.abspath(__file__))
_BYPASS = "\u200b"

_current_lang: str = "en"

_translations: Dict[str, str] = {}
_legacy_translations: Dict[str, str] = {}
_english_to_key: Dict[str, str] = {}
_names_data: Dict[str, Any] = {}
_reverse: Dict[str, str] = {}        # translation -> English (tab names)

_harvest: Set[str] = set()

_installed: bool = False
_patched_count: int = 0

_needs_language_picker: bool = False


def _locale_dirs() -> List[str]:
    dirs: List[str] = []

    try:
        from lang_pack_downloader import USER_LOCALE_DIR
        dirs.append(str(USER_LOCALE_DIR))
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        dirs.append(os.path.join(os.path.dirname(sys.executable), "locale"))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(os.path.join(meipass, "locale"))
    dirs.append(os.path.join(_MY_DIR, "locale"))
    dirs.append(os.path.join(_MY_DIR, "dist", "locale"))
    seen = set()
    out = []
    for d in dirs:
        key = os.path.normcase(os.path.abspath(d)) if d else ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _load_json(lang: str) -> Dict[str, Any]:
    variants = [f"{lang}.json"]
    aliases = {
        "ja": ["ja_JP"], "ko": ["ko_KR"], "zh": ["zh_CN"],
        "zh-tw": ["zh_TW"], "de": ["de_DE"], "fr": ["fr_FR"],
        "es": ["es_ES"], "it": ["it_IT"], "pl": ["pl_PL"],
        "ru": ["ru_RU"], "tr": ["tr_TR"], "pt-br": ["pt_BR"],
    }
    for alias in aliases.get(lang, []):
        variants.append(f"{alias}.json")
    short = lang.split("_")[0].split("-")[0]
    if short != lang:
        variants.append(f"{short}.json")
    # Packs from every place are merged. Lowest: a pack downloaded earlier
    # (it can be older than the tool); then the packs inside the tool; then
    # files placed next to the .exe (own fixes). Later ones win.
    dirs = _locale_dirs()

    def _k(d):
        return os.path.normcase(os.path.abspath(d))
    try:
        from lang_pack_downloader import USER_LOCALE_DIR as _udir
        user_key = _k(str(_udir))
    except Exception:
        user_key = None
    exe_key = (_k(os.path.join(os.path.dirname(sys.executable), "locale"))
               if getattr(sys, "frozen", False) else None)
    low = [d for d in dirs if _k(d) == user_key]
    high = [d for d in dirs if exe_key and _k(d) == exe_key]
    mid = [d for d in dirs if d not in low and d not in high]
    merged: Dict[str, Any] = {}
    for d in low + list(reversed(mid)) + high:
        for v in reversed(variants):            # the exact code wins over an alias
            p = os.path.join(d, v)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        merged.update(data)
                except Exception as e:
                    log.warning("Failed to load %s: %s", p, e)
    return merged


def _load_names(lang: str) -> Dict[str, Any]:
    if lang == "en":
        return {}
    for d in _locale_dirs():
        p = os.path.join(d, f"names_{lang}.json")
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning("Failed to load %s: %s", p, e)
    short = lang.split("_")[0].split("-")[0]
    if short != lang:
        return _load_names(short)
    return {}


_DOTTED_KEY_RE = None

def _looks_like_legacy_key(k: str) -> bool:
    if not k or "_" == k[0]:
        return False
    if " " in k:
        return False
    if "." not in k:
        return False
    return k.islower()


def _load_translations(lang: str) -> None:
    global _translations, _legacy_translations, _english_to_key, _names_data, _reverse
    _reverse = {}

    _translations = {}
    _legacy_translations = {}
    _english_to_key = {}
    _names_data = {}

    en_data = _load_json("en")
    if isinstance(en_data, dict):
        for k, v in en_data.items():
            if k.startswith("_") or not isinstance(v, str) or not v:
                continue
            if _looks_like_legacy_key(k):
                _english_to_key[v] = k

    if lang == "en":
        return

    target = _load_json(lang)
    log.info("gui_i18n: loading lang=%r from dirs=%s -> %d entries",
             lang, _locale_dirs(), len(target))
    if not target:
        log.warning("gui_i18n: no locale pack found for %r", lang)
    for k, v in target.items():
        if k.startswith("_") or not isinstance(v, str) or not v:
            continue
        if _looks_like_legacy_key(k):
            _legacy_translations[k] = v
        else:
            _translations[k] = v

    _reverse = {}
    for _en, _loc in _translations.items():
        _reverse.setdefault(_loc, _en)
    _names_data = _load_names(lang)
    log.info("gui_i18n: loaded %d english-keyed, %d legacy-keyed, %d english->key, %d names",
             len(_translations), len(_legacy_translations),
             len(_english_to_key), len(_names_data))


def _classify_and_load(lang: str) -> None:
    _load_translations(lang)


def tr(text: Any, **fmt: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    if text.startswith(_BYPASS):
        return text[len(_BYPASS):]

    if _current_lang == "en":
        out = text
    else:
        out = _translations.get(text)
        if out is None:
            key = _english_to_key.get(text)
            if key is not None:
                out = _legacy_translations.get(key)
        if out is None:
            if text in _legacy_translations:
                out = _legacy_translations[text]
        if out is None:
            _harvest.add(text)
            out = text

    if fmt:
        try:
            out = out.format(**fmt)
        except Exception:
            pass
    return out


def current_language() -> str:
    return _current_lang


def set_language(lang: str) -> None:
    global _current_lang
    if lang and lang != "en":
        try:
            from lang_pack_downloader import is_pack_local as _probe
            if not _probe(lang):
                log.warning(
                    "gui_i18n: language pack %r not installed; "
                    "translations will fall back to English.", lang,
                )
        except Exception:
            pass
    _current_lang = lang or "en"
    _load_translations(_current_lang)
    try:
        import sys as _sys
        mod = _sys.modules.get("item_db")
        if mod is not None:
            pass
    except Exception:
        pass


def needs_language_picker() -> bool:
    return _needs_language_picker


def set_needs_language_picker(flag: bool) -> None:
    global _needs_language_picker
    _needs_language_picker = bool(flag)


def available_languages() -> List[str]:
    codes: Set[str] = set()
    for d in _locale_dirs():
        if not os.path.isdir(d):
            continue
        try:
            for fname in os.listdir(d):
                if fname.endswith(".json") and not fname.startswith("names_"):
                    codes.add(fname[:-5])
        except OSError:
            pass
    codes.add("en")
    return sorted(codes)


def compute_startup_language(config_path: str) -> str:
    cfg: Dict[str, Any] = {}
    try:
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f) or {}
    except Exception:
        cfg = {}

    default = cfg.get("default_lang")
    if isinstance(default, str) and default.strip():
        return default.strip()

    legacy = cfg.get("language")
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()

    set_needs_language_picker(True)
    return "en"


def translate_item_name(key: Any, fallback: str = "") -> str:
    if _current_lang == "en" or not _names_data:
        return fallback
    items = _names_data.get("items", {})
    if not isinstance(items, dict):
        return fallback
    v = items.get(str(key)) or items.get(key)
    return v if v else fallback


def translate_quest_name(key: Any, fallback: str = "") -> str:
    if _current_lang == "en" or not _names_data:
        return fallback
    section = _names_data.get("quests", {})
    if not isinstance(section, dict):
        return fallback
    v = section.get(str(key)) or section.get(key)
    return v if v else fallback


def translate_name(kind: str, key: Any, fallback: str = "") -> str:
    if _current_lang == "en" or not _names_data:
        return fallback
    section = _names_data.get(kind, {})
    if not isinstance(section, dict):
        return fallback
    v = section.get(str(key)) or section.get(key)
    return v if v else fallback


def harvest_missing() -> List[str]:
    return sorted(_harvest)


def dump_harvest(path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(_harvest), f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning("dump_harvest failed: %s", e)


def bypass(text: str) -> str:
    return _BYPASS + text


def _patch_method(cls, name: str, arg_indices=(0,)) -> bool:
    global _patched_count
    try:
        orig = getattr(cls, name)
    except AttributeError:
        return False
    if getattr(orig, "__gui_i18n_patched__", False):
        return False

    def wrapper(self, *args, **kw):
        if args:
            new_args = list(args)
            for i in arg_indices:
                if i < len(new_args) and isinstance(new_args[i], str):
                    new_args[i] = tr(new_args[i])
            args = tuple(new_args)
        return orig(self, *args, **kw)

    wrapper.__gui_i18n_patched__ = True
    wrapper.__name__ = name
    try:
        setattr(cls, name, wrapper)
        _patched_count += 1
        return True
    except (TypeError, AttributeError):
        return False


def _patch_staticmethod(cls, name: str, str_arg_positions=(0, 1)) -> bool:
    global _patched_count
    try:
        orig = getattr(cls, name)
    except AttributeError:
        return False
    if getattr(orig, "__gui_i18n_patched__", False):
        return False

    def wrapper(*args, **kw):
        new_args = list(args)
        for i in str_arg_positions:
            if i < len(new_args) and isinstance(new_args[i], str):
                new_args[i] = tr(new_args[i])
        return orig(*new_args, **kw)

    wrapper.__gui_i18n_patched__ = True
    wrapper.__name__ = name
    try:
        setattr(cls, name, wrapper)
        _patched_count += 1
        return True
    except (TypeError, AttributeError):
        return False


_TAB_EN = "__gui_i18n_en__"


def _install_tab_patches(W) -> None:
    """Tab texts are translated on screen, but the code keeps seeing the
    English name: it is stored as the tab's data and tabText() returns it.
    (The tool finds its pages by their English tab names.)"""
    global _patched_count

    def _bar(obj):
        return obj.tabBar() if isinstance(obj, W.QTabWidget) else obj

    def _english(args):
        for a in args:
            if isinstance(a, str):
                if a.startswith(_BYPASS):
                    return a[len(_BYPASS):]
                if a in _translations or a in _legacy_translations:
                    return a
                # some callers pass an already translated text (tr("Mounts"))
                return _reverse.get(a, a)
        return None

    def _store(obj, idx, english):
        try:
            if english is not None and isinstance(idx, int) and idx >= 0:
                _bar(obj).setTabData(idx, (_TAB_EN, english))
        except Exception:
            pass

    def _wrap(cls, name, index_pos=None):
        global _patched_count
        orig = getattr(cls, name, None)
        if orig is None or getattr(orig, "__gui_i18n_patched__", False):
            return

        def wrapper(self, *args, **kw):
            english = _english(args)
            new_args = tuple(tr(a) if isinstance(a, str) else a for a in args)
            res = orig(self, *new_args, **kw)
            idx = res if index_pos is None else (args[index_pos] if len(args) > index_pos else -1)
            _store(self, idx, english)
            return res

        wrapper.__gui_i18n_patched__ = True
        wrapper.__name__ = name
        try:
            setattr(cls, name, wrapper)
            _patched_count += 1
        except (TypeError, AttributeError):
            pass

    for cls in (W.QTabWidget, W.QTabBar):
        _wrap(cls, "addTab")
        _wrap(cls, "insertTab")
        _wrap(cls, "setTabText", index_pos=0)
        orig_tt = getattr(cls, "tabText", None)
        if orig_tt is None or getattr(orig_tt, "__gui_i18n_patched__", False):
            continue

        def tab_text(self, index, _orig=orig_tt):
            try:
                d = _bar(self).tabData(index)
                if isinstance(d, tuple) and len(d) == 2 and d[0] == _TAB_EN:
                    return d[1]
            except Exception:
                pass
            return _orig(self, index)

        tab_text.__gui_i18n_patched__ = True
        tab_text.__name__ = "tabText"
        try:
            setattr(cls, "tabText", tab_text)
            _patched_count += 1
        except (TypeError, AttributeError):
            pass


def _install_qt_patches() -> None:
    global _patched_count
    from PySide6 import QtWidgets, QtGui, QtCore

    W = QtWidgets
    G = QtGui

    _patch_method(W.QWidget, "setWindowTitle")
    _patch_method(W.QWidget, "setToolTip")
    _patch_method(W.QWidget, "setStatusTip")
    _patch_method(W.QWidget, "setWhatsThis")
    _patch_method(W.QWidget, "setAccessibleName")
    _patch_method(W.QWidget, "setAccessibleDescription")

    _patch_method(W.QLabel, "setText")
    _patch_method(W.QAbstractButton, "setText")
    for cls in (W.QLabel, W.QPushButton, W.QCheckBox, W.QRadioButton,
                W.QToolButton, W.QCommandLinkButton):
        _patch_method(cls, "__init__")

    _patch_method(W.QGroupBox, "setTitle")
    _patch_method(W.QGroupBox, "__init__")

    _patch_method(G.QAction, "setText")
    _patch_method(G.QAction, "setToolTip")
    _patch_method(G.QAction, "setStatusTip")
    _patch_method(G.QAction, "setWhatsThis")
    _patch_method(G.QAction, "setIconText")
    _patch_method(G.QAction, "__init__")

    _patch_method(W.QMenu, "setTitle")
    _patch_method(W.QMenu, "__init__")
    _patch_method(W.QMenu, "addAction", arg_indices=(0,))
    _patch_method(W.QMenu, "addMenu", arg_indices=(0,))
    _patch_method(W.QMenuBar, "addMenu", arg_indices=(0,))

    _install_tab_patches(W)
    _patch_method(W.QTabWidget, "setTabToolTip", arg_indices=(1,))
    _patch_method(W.QTabWidget, "setTabWhatsThis", arg_indices=(1,))
    _patch_method(W.QTabBar, "setTabToolTip", arg_indices=(1,))

    def _patch_header_labels(cls, name):
        global _patched_count
        try:
            orig = getattr(cls, name)
        except AttributeError:
            return
        if getattr(orig, "__gui_i18n_patched__", False):
            return

        def wrapper(self, labels, *a, **kw):
            if isinstance(labels, (list, tuple)):
                labels = [tr(x) if isinstance(x, str) else x for x in labels]
            return orig(self, labels, *a, **kw)
        wrapper.__gui_i18n_patched__ = True
        setattr(cls, name, wrapper)
        _patched_count += 1

    _patch_header_labels(W.QTableWidget, "setHorizontalHeaderLabels")
    _patch_header_labels(W.QTableWidget, "setVerticalHeaderLabels")
    _patch_header_labels(W.QTreeWidget, "setHeaderLabels")

    _patch_method(W.QTableWidgetItem, "__init__")
    _patch_method(W.QTableWidgetItem, "setText")
    _patch_method(W.QTableWidgetItem, "setToolTip")
    _patch_method(W.QTableWidgetItem, "setWhatsThis")

    _patch_method(W.QListWidgetItem, "__init__")
    _patch_method(W.QListWidgetItem, "setText")
    _patch_method(W.QListWidgetItem, "setToolTip")
    _patch_method(W.QListWidgetItem, "setWhatsThis")

    _patch_method(W.QTreeWidgetItem, "setText", arg_indices=(1,))
    _patch_method(W.QTreeWidgetItem, "setToolTip", arg_indices=(1,))
    _patch_method(W.QTreeWidgetItem, "setWhatsThis", arg_indices=(1,))

    try:
        _tw_orig = W.QTreeWidgetItem.__init__

        def _tw_init(self, *args, **kw):
            new_args = list(args)
            for i, a in enumerate(new_args):
                if isinstance(a, list) and all(isinstance(x, str) or x is None for x in a):
                    new_args[i] = [tr(x) if isinstance(x, str) else x for x in a]
            return _tw_orig(self, *new_args, **kw)
        _tw_init.__gui_i18n_patched__ = True
        W.QTreeWidgetItem.__init__ = _tw_init
        _patched_count += 1
    except Exception:
        pass


    _patch_method(W.QLineEdit, "setPlaceholderText")
    _patch_method(W.QPlainTextEdit, "setPlaceholderText")
    _patch_method(W.QTextEdit, "setPlaceholderText")

    _orig_combo_add_item = W.QComboBox.addItem
    if not getattr(_orig_combo_add_item, "__gui_i18n_patched__", False):
        def _combo_add_item(self, *args, **kw):
            args = list(args)
            english = None
            if args and isinstance(args[0], str):
                english = args[0]
                args[0] = tr(args[0])
            elif len(args) >= 2 and isinstance(args[1], str):
                english = args[1]
                args[1] = tr(args[1])
            if english is not None and "userData" not in kw:
                if (args and isinstance(args[0], str) and len(args) == 1) or \
                   (len(args) == 2 and not isinstance(args[0], str)):
                    kw["userData"] = english
            return _orig_combo_add_item(self, *args, **kw)
        _combo_add_item.__gui_i18n_patched__ = True
        W.QComboBox.addItem = _combo_add_item
        _patched_count += 1

    _patch_method(W.QComboBox, "insertItem", arg_indices=(1,))
    _patch_method(W.QComboBox, "setItemText", arg_indices=(1,))
    _patch_method(W.QComboBox, "setPlaceholderText")

    _orig_combo_current_text = W.QComboBox.currentText
    if not getattr(_orig_combo_current_text, "__gui_i18n_patched__", False):
        def _combo_current_text(self):
            try:
                idx = self.currentIndex()
                if idx >= 0:
                    data = self.itemData(idx)
                    if isinstance(data, str) and data:
                        return data
            except Exception:
                pass
            return _orig_combo_current_text(self)
        _combo_current_text.__gui_i18n_patched__ = True
        W.QComboBox.currentText = _combo_current_text
        _patched_count += 1

    _orig_combo_add_items = W.QComboBox.addItems
    if not getattr(_orig_combo_add_items, "__gui_i18n_patched__", False):
        def _combo_add_items(self, items):
            if isinstance(items, (list, tuple)):
                start_index = self.count()
                translated = [tr(x) if isinstance(x, str) else x for x in items]
                _orig_combo_add_items(self, translated)
                for offset, original in enumerate(items):
                    if isinstance(original, str):
                        try:
                            self.setItemData(start_index + offset, original)
                        except Exception:
                            pass
                return None
            return _orig_combo_add_items(self, items)
        _combo_add_items.__gui_i18n_patched__ = True
        W.QComboBox.addItems = _combo_add_items
        _patched_count += 1

    _patch_method(W.QListWidget, "addItem", arg_indices=(0,))
    _patch_method(W.QListWidget, "insertItem", arg_indices=(1,))

    _orig_lw_add_items = W.QListWidget.addItems

    def _lw_add_items(self, items):
        if isinstance(items, (list, tuple)):
            items = [tr(x) if isinstance(x, str) else x for x in items]
        return _orig_lw_add_items(self, items)
    if not getattr(_orig_lw_add_items, "__gui_i18n_patched__", False):
        _lw_add_items.__gui_i18n_patched__ = True
        W.QListWidget.addItems = _lw_add_items
        _patched_count += 1

    _patch_method(W.QDockWidget, "__init__")
    _patch_method(W.QDockWidget, "setWindowTitle")
    _patch_method(W.QStatusBar, "showMessage")
    _patch_method(W.QToolBar, "__init__")
    _patch_method(W.QToolBar, "setWindowTitle")
    _patch_method(W.QToolBar, "addAction", arg_indices=(0,))

    _patch_method(W.QMessageBox, "setText")
    _patch_method(W.QMessageBox, "setInformativeText")
    _patch_method(W.QMessageBox, "setDetailedText")
    _patch_method(W.QMessageBox, "setWindowTitle")
    _patch_method(W.QMessageBox, "addButton", arg_indices=(0,))
    for sname in ("information", "warning", "critical", "question", "about"):
        _patch_staticmethod(W.QMessageBox, sname, str_arg_positions=(1, 2))
    _patch_staticmethod(W.QMessageBox, "aboutQt", str_arg_positions=(1,))

    for sname in ("getText", "getInt", "getDouble", "getItem", "getMultiLineText"):
        _patch_staticmethod(W.QInputDialog, sname, str_arg_positions=(1, 2))

    for sname in ("getOpenFileName", "getSaveFileName", "getOpenFileNames",
                  "getExistingDirectory"):
        _patch_staticmethod(W.QFileDialog, sname, str_arg_positions=(1,))

    _patch_method(W.QProgressDialog, "__init__")
    _patch_method(W.QProgressDialog, "setLabelText")
    _patch_method(W.QProgressDialog, "setCancelButtonText")
    _patch_method(W.QProgressDialog, "setWindowTitle")

    _patch_method(W.QErrorMessage, "showMessage")

    _patch_staticmethod(W.QToolTip, "showText", str_arg_positions=(1,))

    try:
        _patch_staticmethod(W.QWhatsThis, "showText", str_arg_positions=(1,))
    except Exception:
        pass


def _install_item_db_adapter() -> None:
    try:
        import item_db
    except Exception:
        return
    cls = getattr(item_db, "ItemNameDB", None)
    if cls is None or getattr(cls.get_name, "__gui_i18n_patched__", False):
        return
    orig_get_name = cls.get_name

    def get_name(self, key):
        info = self.items.get(key)
        english = info.name if (info and info.name) else f"Unknown ({key})"
        if _current_lang != "en":
            loc = translate_item_name(key, english)
            return loc
        return english
    get_name.__gui_i18n_patched__ = True
    cls.get_name = get_name


def install(app=None, lang: str = "en") -> None:
    global _installed
    log.info("gui_i18n: install(lang=%r) called; current_lang=%r", lang, _current_lang)
    set_language(lang)
    if _installed:
        log.info("gui_i18n: install already done, only switched language to %r", _current_lang)
        return
    _installed = True
    try:
        _install_qt_patches()
        log.info("gui_i18n: patched %d Qt setter(s)", _patched_count)
    except Exception as e:
        log.error("gui_i18n: Qt patch install failed: %s", e)
    try:
        _install_item_db_adapter()
    except Exception as e:
        log.error("gui_i18n: item_db adapter install failed: %s", e)
    try:
        from PySide6.QtWidgets import QPushButton, QLabel
        b = QPushButton("Set Stack")
        l = QLabel(); l.setText("Inventory")
        log.info("gui_i18n self-test: QPushButton('Set Stack')->%r  QLabel.setText('Inventory')->%r",
                 b.text(), l.text())
        b.deleteLater(); l.deleteLater()
    except Exception as e:
        log.error("gui_i18n self-test failed: %s", e)


def patched_setter_count() -> int:
    return _patched_count
