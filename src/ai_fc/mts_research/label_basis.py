"""V8 공식 채점 basis 선언 로더 — 해시가 맞을 때만 선언을 돌려준다 (U7, 2026-11-11).

선언 파일: data/mts_research/contracts/v8_official_label_basis_v1.json (기계 판독 정본)
결정: V8 공식 해소 basis = 원장 grid 유지. XNAS 는 진단 원장(scoring_excluded)·V15 A3 섀도 팔 전용.
표시 진단(U1)은 basis 라벨을 붙일 때 이 로더만 읽는다 — 재선언 금지. 해시가 다르면 XNAS 병기를 내지 않는다(fail-closed).
V8 계약·xnas 사전고정 문서는 이 결정 때문에 바뀌지 않는다. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..timeseries_v8.contracts import canonical_hash

LABEL_BASIS_RELATIVE = Path("data/mts_research/contracts/v8_official_label_basis_v1.json")
PINNED_LABEL_BASIS_HASH = "2835c1028cfc53d4c6f1b4d1f127fbded103787f7025aecb240ff8e1e79ba5ff"
OFFICIAL_BASIS = "ledger_grid"
NOTICE = "참고 의견, 매매 신호 아님"


def load_pinned_label_basis(root: Path) -> tuple[dict[str, Any] | None, str]:
    """(선언, 상태). 상태: ok · label_basis_file_missing · label_basis_hash_mismatch."""
    path = Path(root) / LABEL_BASIS_RELATIVE
    if not path.is_file():
        return None, "label_basis_file_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "label_basis_hash_mismatch"
    if canonical_hash(payload) != PINNED_LABEL_BASIS_HASH:
        return None, "label_basis_hash_mismatch"
    if ((payload.get("official_basis") or {}).get("label_basis")) != OFFICIAL_BASIS:
        return None, "label_basis_hash_mismatch"
    return payload, "ok"
