"""감시 임계 사전고정 파일 로더 — 해시가 맞을 때만 임계를 돌려준다.

사전고정 문서: docs/research/mts_upgrade/coherence_monitor_prereg_20261111.md
임계는 공시 라벨 부여에만 쓴다. 게이트·승격·숨김·재예측과 연결하지 않는다.
해시가 다르면 감시기는 모든 지표를 null 로 두고 status="threshold_hash_mismatch" 를 낸다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..timeseries_v8.contracts import canonical_hash

THRESHOLDS_RELATIVE = Path("data/mts_research/contracts/coherence_monitor_thresholds_v1.json")
PINNED_THRESHOLD_HASH = "bcc24081030d654a845a50dd4a434aebb11b6c0fae7213bcbae4457577702d76"
NOTICE = "참고 의견, 매매 신호 아님"


def load_pinned_thresholds(root: Path) -> tuple[dict[str, Any] | None, str]:
    """(임계, 상태). 상태: ok · threshold_file_missing · threshold_hash_mismatch."""
    path = root / THRESHOLDS_RELATIVE
    if not path.is_file():
        return None, "threshold_file_missing"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(payload) != PINNED_THRESHOLD_HASH:
        return None, "threshold_hash_mismatch"
    return payload, "ok"
