"""zh/en 翻譯的遞迴 key 與 placeholder parity（非只比縮排）。"""
import json
import re
from pathlib import Path

_TRANS = Path(__file__).resolve().parent.parent / "web" / "translations"


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _placeholders(s: object) -> set:
    return set(re.findall(r"{(\w+)}", s)) if isinstance(s, str) else set()


def _load(name: str) -> dict:
    return _flatten(json.loads((_TRANS / name).read_text(encoding="utf-8")))


def test_zh_en_key_parity() -> None:
    zh, en = _load("zh.json"), _load("en.json")
    assert set(zh) == set(en), (
        f"missing in en: {set(zh) - set(en)}; missing in zh: {set(en) - set(zh)}"
    )


def test_zh_en_placeholder_parity() -> None:
    zh, en = _load("zh.json"), _load("en.json")
    mismatched = {
        k: (_placeholders(zh[k]), _placeholders(en[k]))
        for k in zh
        if _placeholders(zh[k]) != _placeholders(en.get(k))
    }
    assert not mismatched, f"placeholder mismatch: {mismatched}"
