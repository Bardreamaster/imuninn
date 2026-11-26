"""Packaged frame-convention data (copies of protocol/frames/*.json, refreshed by tools/gen-frames.py)."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources


def _load(name: str) -> dict:
    return json.loads((resources.files("imuninn") / "data" / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def convention() -> dict:
    """protocol/frames/convention.json."""
    return _load("convention.json")


@lru_cache(maxsize=None)
def iphone_frames() -> dict:
    """protocol/frames/iphone-frames.json (lengths in mm)."""
    return _load("iphone-frames.json")


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


@lru_cache(maxsize=None)
def _name_index() -> dict[str, str]:
    data = iphone_frames()
    idx: dict[str, str] = {}
    for slug, m in data["models"].items():
        idx[_norm(slug)] = slug
        idx[_norm(m["name"])] = slug
        also = m.get("also_covers")
        for a in ([also] if isinstance(also, str) else also or []):
            idx[_norm(a)] = slug
    return idx


def resolve_model(model: str) -> str | None:
    """Dataset slug for a hardware identifier ("iPhone18,1"), a slug ("iphone-17-pro") or a
    marketing name ("iPhone 17 Pro", case and spacing ignored); None when unknown."""
    if not model:
        return None
    data = iphone_frames()
    if model in data["identifiers"]:
        return data["identifiers"][model]
    if model in data["models"]:
        return model
    return _name_index().get(_norm(model))
