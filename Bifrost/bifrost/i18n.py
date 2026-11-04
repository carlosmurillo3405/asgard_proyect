# -*- coding: utf-8 -*-
"""Translations for the Asgard system: English source text and a Spanish catalog.

SHARED FILE: the original lives in ``Common/i18n.py`` and is copied to each
program by ``python Common/sync.py``. Edit only the original.

The code is written in English. Each package keeps its catalogs in
``locale/<domain>.<language>.json`` (English text -> translation)::

    from .i18n import tr
    label.setText(tr("Connected"))
    tr("Session {code} started", code=session_id)

Without keyword arguments the text is returned untouched, so logging
templates keep working: ``log.info(tr("Session %s started"), session_id)``.
Never call :func:`tr` while a module is being imported: the language is chosen
later, when the program starts.
"""

from __future__ import annotations

import json
import locale as _locale
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LANGUAGES = ("en", "es")                     # "en" is the source language
LANGUAGE_NAMES = {"en": "English", "es": "Español"}
SETTINGS = ("auto", *LANGUAGES)

_LOCALE_DIR = Path(__file__).resolve().parent / "locale"
_extra_dirs: list[Path] = []
_catalog: dict[str, str] = {}
_language = "en"


def _match(code: str) -> str:
    # LANGUAGE puede ser una lista como «es_MX:en»; se usa la primera.
    first = code.strip().lower().replace("-", "_").split(":")[0]
    return "es" if first.startswith(("es", "spanish")) else "en"


def system_language() -> str:
    """``"es"`` when the user's system is in Spanish, otherwise ``"en"``."""
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "")
        if value and value not in ("C", "POSIX") and not value.startswith("C."):
            return _match(value)
    if sys.platform == "win32":
        try:
            import ctypes

            # 0x0A es el idioma principal «español» en un LANGID de Windows.
            return "es" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0A else "en"
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(["defaults", "read", "-g", "AppleLocale"],
                                    capture_output=True, text=True, timeout=2)
            if result.stdout.strip():
                return _match(result.stdout)
        except Exception:
            pass
    try:
        code = _locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    return _match(code)


def resolve(setting: str | None) -> str:
    """Turns a setting (``auto``, ``en`` or ``es``) into the language to use."""
    value = (setting or "auto").strip().lower()
    return value if value in LANGUAGES else system_language()


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        log.warning("Could not read the translation catalog %s: %s", path, error)
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def set_language(setting: str | None) -> str:
    """Activates ``en``, ``es`` or ``auto``. Returns the language in use."""
    global _language, _catalog
    language = resolve(setting)
    catalog: dict[str, str] = {}
    if language != "en":
        for folder in (_LOCALE_DIR, *_extra_dirs):
            for path in sorted(folder.glob(f"*.{language}.json")):
                catalog.update(_read(path))
    _language, _catalog = language, catalog
    return language


def add_catalog_dir(folder: str | Path) -> None:
    """Adds another folder with ``*.<language>.json`` catalogs (for example, the demo's)."""
    path = Path(folder)
    if path not in _extra_dirs:
        _extra_dirs.append(path)
        set_language(_language)


def language() -> str:
    """Language in use (``en`` or ``es``)."""
    return _language


def tr(text: str, **values: object) -> str:
    """Translation of ``text``; with keyword arguments it is also formatted."""
    translated = _catalog.get(text, text)
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        # Una traducción con un marcador equivocado no debe romper el programa.
        return text.format(**values)
