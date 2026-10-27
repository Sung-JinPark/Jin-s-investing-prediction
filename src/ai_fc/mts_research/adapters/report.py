"""baseline_identity.json 생성 — §19.3 산출물 (W2 완료 증거).

실자료 read 는 replay_identity 목적의 legacy reproduction 이며, 노출 원장에 기록한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..artifacts import record_exposure
from ..records import require_utc
from ..snapshots import environment_lock_hash
from .pb import replay_vol_live_rows, replay_vol_resolutions
from .v8 import tier1_replay

REPORT_RELATIVE = Path("docs/research/mts_upgrade/baseline_identity.json")


def _summary_only(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "results"}


def build_baseline_identity_report(
    root: Path, *, now: datetime, run_id: str, tier2: dict[str, Any] | None = None
) -> dict[str, Any]:
    require_utc(now, field="now")
    record_exposure(
        root,
        run_id=run_id,
        purpose="replay_identity",
        series=["VIX", "NASDAQCOM", "DGS2"],
        window=["2007-01-01", None],
        windows_hit=[],
        allowed=True,
        reason_codes=[],
    )
    pb_live = replay_vol_live_rows(root)
    pb_resolutions = replay_vol_resolutions(root)
    v8 = tier1_replay(root)
    report = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "run_id": run_id,
        "environment_lock_hash": environment_lock_hash(),
        "pb_live": _summary_only(pb_live),
        "pb_resolutions": _summary_only(pb_resolutions),
        "v8_tier1": {
            k: v
            for k, v in v8.items()
            if k not in ("forecast_results", "resolution_results")
        },
        "v8_tier1_nonpass_rows": [
            r
            for r in (v8.get("forecast_results") or []) + (v8.get("resolution_results") or [])
            if r["status"] not in ("PASS",)
        ],
        "v8_tier2": tier2 or {"status": "NOT_RUN", "note": "별도 감독 실행 (고가 — 전체 walk-forward)"},
        "verdict": {
            "pb_identity": bool(not pb_live["failures"] and not pb_resolutions["failures"]),
            "v8_tier1_identity": bool(v8["ok"]),
        },
    }
    out = root / REPORT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
