"""수집 공통 규칙 (스펙 §4): UA 명시·1초 지연·3회 지수 백오프·원본 보존 후 파싱."""

from __future__ import annotations

import hashlib
import time
import urllib.request
from datetime import date
from pathlib import Path

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dualdb-research/1.0"}
_last_request = 0.0


def get(url: str, timeout: int | None = None) -> bytes:
    global _last_request
    wait = config.REQ_DELAY - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    last: Exception | None = None
    for attempt in range(config.REQ_RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout or config.REQ_TIMEOUT) as resp:
                _last_request = time.time()
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 ** attempt * 2)
    raise last  # type: ignore[misc]


def save_raw(source: str, name: str, body: bytes, ext: str) -> Path:
    """원본을 data/raw/{source}/{date}_{hash}.{ext}로 보존 (원칙 5 — 재현 가능성)."""
    d = config.RAW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(body).hexdigest()[:10]
    path = d / f"{date.today().isoformat()}_{name}_{h}.{ext}"
    if not path.exists():
        path.write_bytes(body)
    return path
