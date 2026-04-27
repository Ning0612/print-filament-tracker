from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from flask import session

_TRANSLATIONS_DIR = Path(__file__).parent / "translations"
_DEFAULT_LANG = "zh"


@lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    path = _TRANSLATIONS_DIR / f"{lang}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _discover_langs() -> frozenset[str]:
    return frozenset(p.stem for p in _TRANSLATIONS_DIR.glob("*.json"))


def get_locale() -> str:
    try:
        lang = session.get("lang", _DEFAULT_LANG)
    except RuntimeError:
        lang = _DEFAULT_LANG
    return lang if lang in _discover_langs() else _DEFAULT_LANG


def get_supported_langs() -> list[tuple[str, str]]:
    """Return [(code, native_name), ...] sorted by code. Extensible: add a new .json file."""
    result = []
    for lang in sorted(_discover_langs()):
        try:
            name = _load(lang).get("lang", {}).get(lang, lang)
        except Exception:
            name = lang
        result.append((lang, name))
    return result


def _resolve(lang: str, key: str) -> str | None:
    try:
        data = _load(lang)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for part in key.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data if isinstance(data, str) else None


def t(key: str, **kwargs) -> str:
    """Translate key for the current session locale, falling back to default lang."""
    lang = get_locale()
    value = _resolve(lang, key) or _resolve(_DEFAULT_LANG, key)
    if value is None:
        return key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value
    return value


def register_i18n(app) -> None:
    @app.context_processor
    def _inject():
        return {
            "t": t,
            "current_lang": get_locale,
            "supported_langs": get_supported_langs,
        }
