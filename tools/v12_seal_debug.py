#!/usr/bin/env python
"""tools/v12_seal_debug.py — 봉인 해시 포맷 변종 대사 (읽기 전용, 일회성 진단).

`sunday_opus_loop.sh::sealed_hash()` 는 GNU `sha256sum` 출력 라인을 정렬해 재해시한다.
Git Bash(MSYS2)의 sha256sum 은 Windows 에서 **바이너리 모드가 기본**이라 구분자가
`  ` 가 아니라 ` *` 일 수 있다. 어떤 변종이 정본 e3ff2fdb… 를 재현하는지 확인한다.
"""
from __future__ import annotations

import hashlib
import json
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


def main() -> int:
    v8 = sorted((ROOT / "src/ai_fc/timeseries_v8").rglob("*.py"))
    pairs = [(_sha256(p), p.relative_to(ROOT).as_posix()) for p in v8]
    pairs += [(_sha256(ROOT / rel), rel) for rel in V2_SEALED]

    variants = {}
    for name, sep in (("two_space", "  "), ("star_binary", " *")):
        lines = sorted(f"{h}{sep}{rel}\n" for h, rel in pairs)
        variants[name] = hashlib.sha256("".join(lines).encode()).hexdigest()

    base = (ROOT / "outputs/timeseries_v12/loop/sealed_baseline.hash").read_text().strip()
    print(json.dumps({
        "baseline": base,
        "v8_py_files": len(v8),
        "v2_sealed_files": len(V2_SEALED),
        "variants": variants,
        "match": [k for k, v in variants.items() if v == base],
    }, indent=2))
    print("\n".join(f"  {h[:12]}  {rel}" for h, rel in sorted(pairs, key=lambda t: t[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
