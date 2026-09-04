#!/usr/bin/env python
"""tools/v12_sha256.py — 산출물 sha256 (읽기 전용). result JSON 의 artifacts 항목용."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out = {}
    for rel in sys.argv[1:]:
        path = ROOT / rel
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
