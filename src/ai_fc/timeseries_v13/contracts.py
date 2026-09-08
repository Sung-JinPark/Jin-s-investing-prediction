"""V13-VOL 계약 상수·로더 — 동결 계수 핀 대조는 여기서 fail-closed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..timeseries_v8.contracts import canonical_hash  # 봉인 모듈의 공개 함수 재사용 (무수정)

MODEL_ID = "event_probability.volatility_v13"
MODEL_VERSION = 13
PROBABILITY_SPACE = "research_volatility_v13_base_rate"
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v13_vol.yaml")
COEFFICIENTS_RELATIVE = Path("data/timeseries_v13/vol/champion_coefficients.json")
LATEST_RELATIVE = Path("data/timeseries_v13/vol/vol_latest.json")
LIVE_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live.jsonl")
EXPERIMENT_LEDGER_RELATIVE = Path("data/timeseries_v13/ledgers/vol_experiments.jsonl")
LADDER_EWMA_RELATIVE = Path("data/timeseries_v13/vol/ladder_ewma_logit.json")
LADDER_PB_RELATIVE = Path("data/timeseries_v13/vol/ladder_pb_baseline.json")
CELL_ORDER = ("vix25_h5", "vix25_h21", "vix25_h63", "vix30_h5", "vix30_h21", "vix30_h63",
              "rv_h5", "rv_h21", "rv_h63")
DISPLAY_TIERS = ("t0_internal", "t2_hidden_panel", "t3_live_card")
EWMA_ALPHA = 2.0 / (21 + 1)
DESIGN_WINDOW = ("2007-01-01", "2014-12-31")
THETA_RV = 0.1694
Z80 = 1.2815515655446004          # Φ⁻¹(0.90) — 80% 양측 대역
BLOCK_LENGTH = 13
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260907

__all__ = [
    "MODEL_ID", "MODEL_VERSION", "PROBABILITY_SPACE", "CONTRACT_RELATIVE", "COEFFICIENTS_RELATIVE",
    "LATEST_RELATIVE", "LIVE_LEDGER_RELATIVE", "EXPERIMENT_LEDGER_RELATIVE", "LADDER_EWMA_RELATIVE",
    "LADDER_PB_RELATIVE", "CELL_ORDER", "DISPLAY_TIERS", "EWMA_ALPHA", "DESIGN_WINDOW", "THETA_RV", "Z80",
    "BLOCK_LENGTH", "BOOTSTRAP_REPLICATES", "BOOTSTRAP_SEED", "TimeSeriesV13VolError", "canonical_hash",
    "sha256_file", "load_contract_v13", "display_tier", "load_frozen_coefficients", "cell_specs",
]


class TimeSeriesV13VolError(RuntimeError):
    """A V13-VOL invariant failed closed (contract, pin, freshness, ledger)."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_contract_v13(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        raise TimeSeriesV13VolError("V13 contract is missing")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_id") != "timeseries_v13_vol":
        raise TimeSeriesV13VolError("V13 contract id mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV13VolError("V13 contract model identity mismatch")
    return payload


def display_tier(root: Path) -> str:
    """계약의 publication.display_tier — 계약이 없으면 t0(내부)로 페일클로즈."""
    path = root / CONTRACT_RELATIVE
    if not path.is_file():
        return DISPLAY_TIERS[0]
    publication = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("publication") or {}
    tier = publication.get("display_tier")
    return tier if tier in DISPLAY_TIERS else DISPLAY_TIERS[0]


def cell_specs() -> list[dict[str, Any]]:
    """9셀 사양 — CELL_ORDER 고정. K·θ·h 는 계약 targets 와 같다 (post_hoc_target_addition 금지)."""
    specs: list[dict[str, Any]] = []
    for K in (25, 30):
        for h in (5, 21, 63):
            specs.append({"name": f"vix{K}_h{h}", "target": "vix_touch", "K": K, "h": h})
    for h in (5, 21, 63):
        specs.append({"name": f"rv_h{h}", "target": "rv_exceedance", "theta": THETA_RV, "h": h})
    assert tuple(s["name"] for s in specs) == CELL_ORDER
    return specs


def load_frozen_coefficients(
    root: Path,
    *,
    expected_sha256: str | None,
    expected_content_hash: str | None,
    expected_finalist_id: str | None,
) -> dict[str, Any]:
    """동결 계수 artifact — 파일 sha256 · content_hash · finalist_id 3자 대조. 하나라도 어긋나면 raise."""
    if not expected_sha256 or not expected_content_hash or not expected_finalist_id:
        raise TimeSeriesV13VolError("frozen coefficients are not pinned in the contract")
    path = root / COEFFICIENTS_RELATIVE
    if not path.is_file():
        raise TimeSeriesV13VolError("frozen coefficients artifact is missing")
    if sha256_file(path) != expected_sha256:
        raise TimeSeriesV13VolError("frozen coefficients sha256 mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    recorded = body.pop("content_hash", None)
    if recorded != expected_content_hash or canonical_hash(body) != expected_content_hash:
        raise TimeSeriesV13VolError("frozen coefficients content hash mismatch")
    if payload.get("finalist_id") != expected_finalist_id:
        raise TimeSeriesV13VolError("frozen coefficients finalist mismatch")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise TimeSeriesV13VolError("frozen coefficients model identity mismatch")
    cells = payload.get("cells") or {}
    if not cells or not set(cells) <= set(CELL_ORDER):
        raise TimeSeriesV13VolError("frozen coefficients cell set invalid")
    return payload
