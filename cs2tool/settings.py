"""轻量配置（data/settings.json）。"""
from __future__ import annotations

import json
import os

_PATH = None


def init(path: str) -> None:
    global _PATH
    _PATH = path
    os.makedirs(os.path.dirname(path), exist_ok=True)


def load() -> dict:
    if _PATH and os.path.exists(_PATH):
        try:
            return json.load(open(_PATH, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(d: dict) -> None:
    if not _PATH:
        return
    json.dump(d, open(_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def get(key, default=None):
    return load().get(key, default)


def set(**kw) -> dict:
    d = load()
    d.update(kw)
    save(d)
    return d
