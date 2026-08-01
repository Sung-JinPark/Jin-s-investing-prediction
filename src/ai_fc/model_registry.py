"""Model lifecycle registry with explicit approval boundaries."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .integrity import repository_context


class Lifecycle(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    CHAMPION = "champion"
    DEMOTED = "demoted"
    RETIRED = "retired"


class ModelCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    display_name: str
    version: str
    lifecycle: Lifecycle
    target: str
    code_version: str
    data_fingerprint: str | None = None
    params: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    limitations: str = ""
    promotion_allowed: bool = False


DEFAULT_MODELS = (
    ("bl.gbm_v1", "GBM v1", Lifecycle.CHAMPION, "terminal/barrier/path", "공식 시나리오 기준선; fat tail·점프를 직접 모형화하지 않음"),
    ("bl.rw_drift", "Random walk + drift", Lifecycle.BASELINE, "terminal", "표본 평균·분산 민감"),
    ("bl.uncond_base", "Unconditional base rate", Lifecycle.BASELINE, "event", "도메인 고유 이벤트 표본 부족"),
    ("bl.seasonal_base", "Seasonal base rate", Lifecycle.BASELINE, "event", "월·분기 셀 표본 부족"),
    ("bl.hist_sim", "Historical simulation", Lifecycle.BASELINE, "terminal/path", "과거 분포 반복 가정"),
    ("bl.block_boot", "Block bootstrap", Lifecycle.BASELINE, "path", "블록 길이 민감"),
    ("shadow.ewma", "EWMA volatility", Lifecycle.SHADOW, "volatility/path", "GBM 입력 개선 후보; 미승격"),
    ("shadow.garch11", "GARCH(1,1)", Lifecycle.SHADOW, "volatility/path", "EWMA 대비 paired 검증 전"),
    ("shadow.bl_rnd", "Breeden-Litzenberger RND", Lifecycle.SHADOW, "risk-neutral terminal", "QQQ↔IXIC 프록시·옵션 스냅샷 제약; 참조 전용"),
    ("shadow.chronos2", "Chronos-2", Lifecycle.SHADOW, "quantile/reference", "체크포인트 pin·로컬 paired 평가 전"),
    ("shadow.timesfm25", "TimesFM 2.5", Lifecycle.SHADOW, "quantile/reference", "비교군; 공급망 pin 전"),
)


def register_defaults(conn: sqlite3.Connection, root: Path) -> None:
    context = repository_context(root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for model_id, name, lifecycle, target, limitations in DEFAULT_MODELS:
        card = ModelCard(
            model_id=model_id, display_name=name, version="1", lifecycle=lifecycle,
            target=target, code_version=context.head or "working-tree",
            data_fingerprint=context.source_fingerprint,
            params={"seed": 42} if model_id.startswith(("bl.", "shadow.")) else {},
            limitations=limitations,
            promotion_allowed=model_id == "bl.gbm_v1",
        )
        conn.execute(
            """INSERT INTO model_registry
               (model_id,display_name,version,lifecycle,target,code_version,data_fingerprint,
                params_json,metrics_json,limitations,promotion_allowed,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(model_id) DO UPDATE SET
                 display_name=excluded.display_name,target=excluded.target,
                 data_fingerprint=excluded.data_fingerprint,limitations=excluded.limitations,
                 updated_at=excluded.updated_at""",
            (card.model_id, card.display_name, card.version, card.lifecycle.value,
             card.target, card.code_version, card.data_fingerprint,
             json.dumps(card.params, sort_keys=True), json.dumps(card.metrics, sort_keys=True),
             card.limitations, int(card.promotion_allowed), now, now),
        )


def transition(
    conn: sqlite3.Connection, model_id: str, lifecycle: Lifecycle | str, *,
    approved: bool = False,
) -> None:
    target = Lifecycle(lifecycle)
    row = conn.execute(
        "SELECT lifecycle,promotion_allowed FROM model_registry WHERE model_id=?", (model_id,)
    ).fetchone()
    if row is None:
        raise KeyError(model_id)
    current = Lifecycle(row["lifecycle"])
    allowed = {
        Lifecycle.BASELINE: {Lifecycle.CANDIDATE, Lifecycle.RETIRED},
        Lifecycle.CANDIDATE: {Lifecycle.SHADOW, Lifecycle.RETIRED},
        Lifecycle.SHADOW: {Lifecycle.CHAMPION, Lifecycle.RETIRED},
        Lifecycle.CHAMPION: {Lifecycle.DEMOTED},
        Lifecycle.DEMOTED: {Lifecycle.CHAMPION, Lifecycle.RETIRED},
        Lifecycle.RETIRED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(f"invalid lifecycle transition: {current.value} -> {target.value}")
    if target is Lifecycle.CHAMPION and (not approved or not row["promotion_allowed"]):
        raise PermissionError("champion promotion requires metrics gate and explicit user approval")
    if target is Lifecycle.CHAMPION:
        conn.execute(
            "UPDATE model_registry SET lifecycle='demoted',updated_at=? WHERE lifecycle='champion'",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
    conn.execute(
        "UPDATE model_registry SET lifecycle=?,updated_at=? WHERE model_id=?",
        (target.value, datetime.now(timezone.utc).isoformat(timespec="seconds"), model_id),
    )
    conn.commit()


def arena_rows(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for row in conn.execute("SELECT * FROM model_registry ORDER BY lifecycle,model_id"):
        metrics = json.loads(row["metrics_json"] or "{}")
        out.append({
            "model_id": row["model_id"], "name": row["display_name"],
            "version": row["version"], "lifecycle": row["lifecycle"],
            "target": row["target"], "metrics": metrics,
            "n_insufficient": int(metrics.get("n_unique", 0)) < 30,
            "limitations": row["limitations"],
            "promotion_enabled": bool(row["promotion_allowed"] and row["lifecycle"] != "champion"),
        })
    return out
