#!/usr/bin/env python
"""tools/v12_seal_check.py — V12 루프 봉인 대사 (읽기 전용).

봉인 정본 = timeseries_v8 전체 .py + timeseries_v2 봉인 8개 파일.
sunday_opus_loop.sh 의 sealed_hash() 와 동일한 규약(`sha256sum` 출력 라인 정렬 후 재해시)을
파이썬으로 재현한다. 정본 해시는 e3ff2fdb… 로 시작한다.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

V2_SEALED = [
    "src/ai_fc/timeseries_v2/contracts.py",
    "src/ai_fc/timeseries_v2/market_archive.py",
    "src/ai_fc/timeseries_v2/dfm_cache.py",
    "src/ai_fc/timeseries_v2/features.py",
    "src/ai_fc/timeseries_v2/model.py",
    "src/ai_fc/timeseries_v2/backtest.py",
    "src/ai_fc/timeseries_v2/pipeline.py",
    "src/ai_fc/timeseries_v2/artifact.py",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sealed_hash() -> str:
    """`sha256sum` 라인 정렬 후 재해시.

    구분자는 ``" *"`` — Git Bash(MSYS2) 의 sha256sum 은 Windows 에서 **바이너리 모드가
    기본**이라 `hash *path` 로 출력한다. POSIX 텍스트모드(`hash  path`)로 재현하면
    정본 e3ff2fdb… 가 아니라 f1108f52… 가 나온다 (S1-1 실측, tools/v12_seal_debug.py).
    """
    lines = []
    for path in sorted((ROOT / "src/ai_fc/timeseries_v8").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        lines.append(f"{_sha256(path)} *{rel}\n")
    for rel in V2_SEALED:
        lines.append(f"{_sha256(ROOT / rel)} *{rel}\n")
    lines.sort()
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def ledger_hash() -> str:
    """v8 원장 .jsonl 을 glob 순서대로 이어붙인 바이트의 sha256 (cat *.jsonl 재현)."""
    h = hashlib.sha256()
    for path in sorted((ROOT / "data/timeseries_v8/ledgers").glob("*.jsonl")):
        h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    loop = ROOT / "outputs/timeseries_v12/loop"
    sealed = sealed_hash()
    ledger = ledger_hash()
    base = (loop / "sealed_baseline.hash").read_text().strip()
    lbase = (loop / "ledger_baseline.hash").read_text().strip()
    out = {
        "sealed": sealed,
        "sealed_baseline": base,
        "sealed_match": sealed == base,
        "sealed_prefix_ok": sealed.startswith("e3ff2fdb"),
        "ledger": ledger,
        "ledger_baseline": lbase,
        "ledger_match": ledger == lbase,
    }
    print(json.dumps(out, indent=2))
    return 0 if (out["sealed_match"] and out["ledger_match"] and out["sealed_prefix_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
