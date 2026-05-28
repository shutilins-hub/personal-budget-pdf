from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app_config import debug_exports_enabled as config_debug_exports_enabled, get_app_config
from privacy import sanitize_text


EXPORTS_DIR = get_app_config().exports_dir
DEBUG_EXPORTS_ENV = "BUDGET_DEBUG_EXPORTS"
DEBUG_TEXT_MAX_CHARS = 12000
DEBUG_LIST_MAX_ITEMS = 1000


def debug_exports_enabled() -> bool:
    return config_debug_exports_enabled()


def ensure_debug_exports_dir() -> Path:
    EXPORTS_DIR.mkdir(exist_ok=True)
    return EXPORTS_DIR


def sanitize_debug_data(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {sanitize_text(str(key)): sanitize_debug_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_debug_data(item) for item in value[:DEBUG_LIST_MAX_ITEMS]]
    if isinstance(value, tuple):
        return tuple(sanitize_debug_data(item) for item in value[:DEBUG_LIST_MAX_ITEMS])
    return value


def sanitized_text_excerpt(text: str, max_chars: int = DEBUG_TEXT_MAX_CHARS) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    excerpt = "\n".join(lines)[:max_chars]
    return sanitize_text(excerpt)


def sanitize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()
    safe = frame.copy()
    for column in safe.columns:
        if safe[column].dtype == object:
            safe[column] = safe[column].map(lambda value: sanitize_text(value) if isinstance(value, str) else value)
    return safe


def write_debug_text(filename: str, text: str, *, max_chars: int = DEBUG_TEXT_MAX_CHARS) -> bool:
    if not debug_exports_enabled():
        return False
    path = ensure_debug_exports_dir() / filename
    path.write_text(sanitized_text_excerpt(text, max_chars=max_chars), encoding="utf-8")
    return True


def write_debug_json(filename: str, data: Any) -> bool:
    if not debug_exports_enabled():
        return False
    path = ensure_debug_exports_dir() / filename
    path.write_text(json.dumps(sanitize_debug_data(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def write_debug_tsv(filename: str, frame: pd.DataFrame) -> bool:
    if not debug_exports_enabled():
        return False
    path = ensure_debug_exports_dir() / filename
    sanitize_dataframe(frame).to_csv(path, sep="\t", index=False)
    return True
