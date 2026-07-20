"""루트 pytest 진입용 경로 설정 (v2 구조 개편 — pyproject testpaths 지원).

`cd src && python -m pytest`·`cd dualdb && python -m pytest` 기존 경로와 병존.
uv editable 설치 후에는 불필요해지나 무해 (sys.path 중복 삽입은 no-op에 가깝다).
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT / "src", _ROOT / "dualdb"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
