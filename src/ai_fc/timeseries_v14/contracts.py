"""V14 조건부 전이 계약 상수·로더 — 표적·좌표·라이브 포인터 키를 상수와 대조하고 동결 계수 핀은 fail-closed.

상수가 정본이 아니라 **계약이 정본**이다. 상수는 코드가 쓰는 값이고, `load_contract_v14` 가 계약의 같은 키와
대조해 하나라도 어긋나면 raise 한다 — 계약을 바꾸고 코드를 안 바꾸거나 그 반대면 verb 가 돌지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..timeseries_v13.contracts import canonical_hash, sha256_file  # V8 canonical_hash 재수출 — 무수정 재사용

MODEL_ID = "event_probability.volatility_v14_conditional"
MODEL_VERSION = 14
CONTRACT_ID = "timeseries_v14_conditional"
MODEL_NAME = "conditional_persistence_pb"
PROBABILITY_SPACE = "research_volatility_v14_conditional"
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v14_conditional.yaml")
COEFFICIENTS_RELATIVE = Path("data/timeseries_v14/vol/champion_coefficients.json")
# 포인터는 vol/ 밖에 둔다 — 레지스트리 timeseries_v14_ladder_results 가 data/timeseries_v14/vol/*.json 을
# immutable_files 로 감시하므로 매 실행 다시 써지는 포인터가 그 안에 있으면 바이트 변경 violation 이 된다.
LATEST_RELATIVE = Path("data/timeseries_v14/live/v14_latest.json")
LIVE_LEDGER_RELATIVE = Path("data/timeseries_v14/ledgers/v14_live.jsonl")
RESOLUTION_LEDGER_RELATIVE = Path("data/timeseries_v14/ledgers/v14_live_resolutions.jsonl")
APPROVALS_LEDGER_RELATIVE = Path("data/timeseries_v14/ledgers/approvals.jsonl")

CELL_ORDER = ("cvix25_h5", "cvix25_h21", "cvix25_h63", "crv_h5", "crv_h21", "crv_h63")
HORIZONS = (5, 21, 63)
K = 25.0                          # targets.vix_conditional_transition.K — 사용자 하드룰 VIX 25+
VIX_COND = 20.0                   # 조건 VIX_close_t < 20 (엄격)
THETA = 0.1694207105468098        # targets.rv_conditional_transition.theta — V13 동결값 승계(V14-D6 G1)
VIX_CONDITION_TEXT = "VIX_close_t < 20"
RV_CONDITION_TEXT = "RV21_ann_t finite and <= theta"
BLOCK = 13                        # gate.uncertainty.block_length
B = 2000                          # gate.uncertainty.replicates
SEED = 20261021                   # gate.uncertainty.seed — V13 seed(20260907) 가 아니다
CI_INTERVAL = (5, 95)
MIN_MATURED = 60                  # live_forward_gate.minimum_matured_origins_per_cell
ROLES = ("champion", "shadow")
DISPLAY_TIERS = ("t0_internal", "t2_hidden_panel", "t3_live_card")
LATE_CAPTURE = "late_capture"
APPROVAL_DECISION = "V14-D10"
# 라이브 패널 시작일 — 피처는 VIX_t 와 RV21_t(최근 22 종가)뿐이라 시작일은 p 에 영향이 없다(RV21 은 창 국소).
# 아카이브 꼬리(라이브 창)만 읽도록 V14 라이브 등록(2026-10-28) 전 약 200 거래일에서 자른다. 설계창·홀드아웃을 읽지 않는다.
LIVE_PANEL_START = "2026-01-01"
RV_WINDOW = 21

__all__ = [
    "MODEL_ID", "MODEL_VERSION", "CONTRACT_ID", "MODEL_NAME", "PROBABILITY_SPACE", "CONTRACT_RELATIVE",
    "COEFFICIENTS_RELATIVE", "LATEST_RELATIVE", "LIVE_LEDGER_RELATIVE", "RESOLUTION_LEDGER_RELATIVE",
    "APPROVALS_LEDGER_RELATIVE", "CELL_ORDER", "HORIZONS", "K", "VIX_COND", "THETA", "BLOCK", "B", "SEED",
    "CI_INTERVAL", "MIN_MATURED", "ROLES", "DISPLAY_TIERS", "LATE_CAPTURE", "LIVE_PANEL_START", "RV_WINDOW",
    "TimeSeriesV14Error", "canonical_hash", "sha256_file", "load_contract_v14", "live_pointer_config",
    "cell_specs", "load_frozen_coefficients", "approval_receipt_present",
]


class TimeSeriesV14Error(RuntimeError):
    """A V14 live invariant failed closed (contract, pin, partition, ledger)."""


def cell_specs() -> list[dict[str, Any]]:
    """6셀 사양 — CELL_ORDER 고정. 이름·K·θ·h·조건 문턱은 계약 targets 와 같다(load_contract_v14 가 대조)."""
    specs: list[dict[str, Any]] = []
    for h in HORIZONS:
        specs.append({"name": f"cvix25_h{h}", "target": "vix_conditional", "K": K, "cond_lt": VIX_COND, "h": h,
                      "condition": VIX_CONDITION_TEXT, "feature": "vix_close"})
    for h in HORIZONS:
        specs.append({"name": f"crv_h{h}", "target": "rv_conditional", "theta": THETA, "h": h,
                      "condition": RV_CONDITION_TEXT, "feature": "rv21_ann"})
    assert tuple(s["name"] for s in specs) == CELL_ORDER
    return specs


def _check_targets(payload: dict[str, Any]) -> None:
    targets = payload.get("targets") or {}
    vix_t = targets.get("vix_conditional_transition") or {}
    rv_t = targets.get("rv_conditional_transition") or {}
    if float(vix_t.get("K", -1)) != K or "< 20" not in str(vix_t.get("conditioning")):
        raise TimeSeriesV14Error("V14 contract vix target (K / conditioning < 20) differs from the coded constants")
    if float(rv_t.get("theta", -1)) != THETA or "<= theta" not in str(rv_t.get("conditioning")):
        raise TimeSeriesV14Error("V14 contract rv target (theta / conditioning <= theta) differs from the coded constants")
    if [int(h) for h in vix_t.get("horizons") or []] != list(HORIZONS) or \
            [int(h) for h in rv_t.get("horizons") or []] != list(HORIZONS):
        raise TimeSeriesV14Error("V14 contract horizons differ from the coded constants")
    if tuple(vix_t.get("cells") or ()) + tuple(rv_t.get("cells") or ()) != CELL_ORDER:
        raise TimeSeriesV14Error("V14 contract cell names differ from the coded constants")
    if int(targets.get("cell_count", -1)) != len(CELL_ORDER):
        raise TimeSeriesV14Error("V14 contract cell_count mismatch")


def _check_uncertainty(payload: dict[str, Any]) -> None:
    unc = ((payload.get("gate") or {}).get("uncertainty")) or {}
    if (int(unc.get("block_length", -1)), int(unc.get("replicates", -1)), unc.get("seed")) != (BLOCK, B, SEED):
        raise TimeSeriesV14Error("V14 contract gate.uncertainty (block_length/replicates/seed) differs from the coded constants")
    if list(unc.get("interval") or []) != list(CI_INTERVAL):
        raise TimeSeriesV14Error("V14 contract gate.uncertainty.interval is not CI90 [5, 95]")
    gate = payload.get("live_forward_gate") or {}
    if int(gate.get("minimum_matured_origins_per_cell", -1)) != MIN_MATURED:
        raise TimeSeriesV14Error("V14 live_forward_gate.minimum_matured_origins_per_cell differs from 60")


def load_contract_v14(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise TimeSeriesV14Error("V14 contract is missing")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_id") != CONTRACT_ID:
        raise TimeSeriesV14Error("V14 contract id mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV14Error("V14 contract model identity mismatch")
    _check_targets(payload)
    _check_uncertainty(payload)
    return payload


def live_pointer_config(contract: dict[str, Any]) -> dict[str, Any]:
    """계약 `live_pointer` 를 검증해 돌려준다. 키가 없으면(V14-D10 전) raise — verb 는 D10 뒤에만 돈다.

    champion_cells/shadow_cells 는 **데이터**다: 6셀의 어떤 분할이든(서로소 ∧ 합집합 = 6셀) 받는다. champion 이 0~6개여도
    된다(T7 은 champion 2개 이상에서만 걸린다 — live_verdict 가 인쇄한다). 경로 키는 코드 상수와 같아야 한다.
    """
    block = contract.get("live_pointer")
    if not isinstance(block, dict):
        raise TimeSeriesV14Error("V14 contract has no live_pointer (V14-D10 not registered)")
    champion = [str(c) for c in (block.get("champion_cells") or [])]
    shadow = [str(c) for c in (block.get("shadow_cells") or [])]
    if len(set(champion)) != len(champion) or len(set(shadow)) != len(shadow):
        raise TimeSeriesV14Error("live_pointer champion_cells/shadow_cells contain duplicates")
    if set(champion) & set(shadow):
        raise TimeSeriesV14Error("live_pointer champion_cells and shadow_cells overlap")
    if set(champion) | set(shadow) != set(CELL_ORDER):
        raise TimeSeriesV14Error("live_pointer champion_cells ∪ shadow_cells must be exactly the six V14 cells")
    if str(block.get("model")) != MODEL_NAME:
        raise TimeSeriesV14Error(f"live_pointer.model must be {MODEL_NAME}")
    for key, expected in (("pointer", LATEST_RELATIVE), ("ledger", LIVE_LEDGER_RELATIVE),
                          ("resolutions_ledger", RESOLUTION_LEDGER_RELATIVE)):
        if str(block.get(key)) != expected.as_posix():
            raise TimeSeriesV14Error(f"live_pointer.{key} must be {expected.as_posix()}")
    freshness = block.get("freshness") or {}
    if str(freshness.get("rule") or "nyse_trading_calendar") != "nyse_trading_calendar":
        raise TimeSeriesV14Error("live_pointer.freshness.rule must be nyse_trading_calendar")
    backfill = block.get("origin_backfill") or {}
    effective_from = str(backfill.get("effective_from") or "") or None
    if effective_from and str(backfill.get("pit_grade")) != LATE_CAPTURE:
        raise TimeSeriesV14Error("live_pointer.origin_backfill.pit_grade must be late_capture")
    # 라이브 패널 시작일은 코드 상수(build_live_panel)가 쓴다 — 계약 문면과 다르면 계약이 말하는 창과 다른 창을 읽는 것이다.
    if str(block.get("live_panel_start")) != LIVE_PANEL_START:
        raise TimeSeriesV14Error(f"live_pointer.live_panel_start must be {LIVE_PANEL_START} (the coded live panel start)")
    tier = str(block.get("display_tier") or "")
    if tier not in DISPLAY_TIERS:
        raise TimeSeriesV14Error("live_pointer.display_tier invalid")
    # 표시 사다리 정본은 publication.display_tier — 포인터 블록이 혼자 다른 tier 를 말하면 승격 우회가 된다.
    if tier != str((contract.get("publication") or {}).get("display_tier")):
        raise TimeSeriesV14Error("live_pointer.display_tier differs from publication.display_tier")
    frozen = contract.get("frozen_coefficients") or {}
    if str(frozen.get("path") or COEFFICIENTS_RELATIVE.as_posix()) != COEFFICIENTS_RELATIVE.as_posix():
        raise TimeSeriesV14Error(f"frozen_coefficients.path must be {COEFFICIENTS_RELATIVE.as_posix()}")
    return {
        "registered": str(block.get("registered") or ""),
        "approval_receipt": str(block.get("approval_receipt") or ""),
        "champion_cells": [c for c in CELL_ORDER if c in champion],
        "shadow_cells": [c for c in CELL_ORDER if c in shadow],
        "roles": {c: ("champion" if c in champion else "shadow") for c in CELL_ORDER},
        "max_missing_sessions": int(freshness.get("max_missing_sessions", 1)),
        "effective_from": effective_from,
        "display_tier": tier,
    }


def approval_receipt_present(root: Path, receipt_id: str, *, decision_id: str = APPROVAL_DECISION) -> bool:
    """approvals.jsonl 에 그 영수증이 있고 그 결정의 행이며 뒤 행이 supersedes 로 철회하지 않았는가."""
    path = root / APPROVALS_LEDGER_RELATIVE
    if not receipt_id or not path.is_file():
        return False
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    superseded = {str(row.get("supersedes")) for row in rows if row.get("supersedes")}
    return any(str(row.get("receipt_id")) == receipt_id and str(row.get("decision_id")) == decision_id
               and receipt_id not in superseded for row in rows)


def load_frozen_coefficients(root: Path, *, expected_sha256: str | None,
                             expected_content_hash: str | None) -> dict[str, Any]:
    """동결 계수 artifact — 파일 sha256 · content_hash 2자 대조 + 셀 사양 대조. 하나라도 어긋나면 raise.

    계약 핀(sha256·content_hash)이 null 이면 '핀 없음' — 호출부(발행)는 hold 로 닫는다.
    """
    if not expected_sha256 or not expected_content_hash:
        raise TimeSeriesV14Error("frozen coefficients are not pinned in the contract")
    path = root / COEFFICIENTS_RELATIVE
    if not path.is_file():
        raise TimeSeriesV14Error("frozen coefficients artifact is missing")
    if sha256_file(path) != expected_sha256:
        raise TimeSeriesV14Error("frozen coefficients sha256 mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    recorded = body.pop("content_hash", None)
    if recorded != expected_content_hash or canonical_hash(body) != expected_content_hash:
        raise TimeSeriesV14Error("frozen coefficients content hash mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION \
            or payload.get("model") != MODEL_NAME:
        raise TimeSeriesV14Error("frozen coefficients model identity mismatch")
    if (payload.get("reconciliation") or {}).get("pass") is not True:
        raise TimeSeriesV14Error("frozen coefficients reconciliation did not pass")
    cells = payload.get("cells") or {}
    if set(cells) != set(CELL_ORDER):
        raise TimeSeriesV14Error("frozen coefficients must carry all six V14 cells")
    for spec in cell_specs():
        cell = cells[spec["name"]]
        same = (cell.get("target") == spec["target"] and int(cell.get("h", -1)) == spec["h"]
                and cell.get("condition") == spec["condition"]
                and (float(cell.get("K", -1)) == K if spec["target"] == "vix_conditional"
                     else float(cell.get("theta", -1)) == THETA))
        if not same:
            raise TimeSeriesV14Error(f"frozen cell {spec['name']} spec differs from the contract targets")
        if len(cell.get("beta") or []) != 2 or len(cell.get("mu") or []) != 1 or len(cell.get("sd") or []) != 1:
            raise TimeSeriesV14Error(f"frozen cell {spec['name']} is not a one-feature logit with intercept")
        if cell.get("role") not in ROLES:
            raise TimeSeriesV14Error(f"frozen cell {spec['name']} role invalid")
        if not 0.0 <= float(cell.get("clim_base_rate", -1)) <= 1.0:
            raise TimeSeriesV14Error(f"frozen cell {spec['name']} climatology out of [0, 1]")
    return payload
