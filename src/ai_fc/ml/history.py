"""ML/시장 확률 이력 — append-only JSONL (파일이 진실, DB는 파생).

data/ml_history/YYYY.jsonl 에 실행당 1행. DB 테이블(ml_forecasts·ml_sentiment·
market_implied)은 여기서 언제든 재구축 가능하므로 sync --rebuild에 안전.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator


def history_dir(root: Path) -> Path:
    return root / "data" / "ml_history"


def append_run(root: Path, payload: dict) -> Path:
    """실행 결과 1건을 연도별 JSONL에 append. payload에 run_ts 없으면 부여."""
    payload.setdefault("run_ts", datetime.now().isoformat(timespec="seconds"))
    d = history_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{payload['run_ts'][:4]}.jsonl"
    # newline="" 로 LF 고정 — .gitattributes가 data/ml_history/** 를 -text(바이트 보존)로
    # 두므로 Windows 텍스트모드 CRLF는 기존 LF run들과 EOL이 뒤섞여 드리프트를 낸다.
    with out.open("a", encoding="utf-8", newline="") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return out


def iter_history(root: Path) -> Iterator[dict]:
    """전체 이력을 시간순으로 순회 (파일명 정렬 = 연도순, 행 순서 = append 순)."""
    d = history_dir(root)
    if not d.exists():
        return
    for path in sorted(d.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
