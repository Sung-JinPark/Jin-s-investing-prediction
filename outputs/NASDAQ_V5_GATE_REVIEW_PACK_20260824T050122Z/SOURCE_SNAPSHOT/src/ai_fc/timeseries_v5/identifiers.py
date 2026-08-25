"""Stable identifiers and canonical hashes for V5 append-only records."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any


def _normal(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normal(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any, *, length: int = 24) -> str:
    return f"{prefix}-{content_hash(value)[:length]}"
