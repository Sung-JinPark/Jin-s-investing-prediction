"""V15 정합성 섀도 테스트 공용 도우미 — tmp 사본 저장소·합성 행·합성 관측.

실저장소에는 쓰지 않는다(쓰기는 tmp_path 사본만). 네트워크 0. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REAL_CUTOFF = "2026-11-10T12:00:00+00:00"
NOW_FIXED = "2026-11-11T09:03:44+00:00"

_COPY_FILES = (
    "data/contracts/multivariate_timeseries_v15_coherence.yaml",
    "data/contracts/multivariate_timeseries_v8.yaml",
    "data/timeseries_v15/prereg/fork_patch_v1.json",
    "data/timeseries_v15/ledgers/approvals.jsonl",
    "src/ai_fc/timeseries_v2/model.py",
    "src/ai_fc/timeseries_v2/backtest.py",
    "src/ai_fc/timeseries_v2/features.py",
    "src/ai_fc/timeseries_v2/dfm_cache.py",
    "src/ai_fc/timeseries_v2/market_archive.py",
    "src/ai_fc/timeseries_v2/contracts.py",
    "src/ai_fc/timeseries/model.py",
    "src/ai_fc/timeseries/backtest.py",
)
_COPY_DIRS = ("src/ai_fc/timeseries_v15", "src/ai_fc/timeseries_v8")


def make_root(tmp_path: Path, *, track_open: bool = False) -> Path:
    """해시·계약 검증에 필요한 파일만 담은 tmp 저장소 사본."""
    root = tmp_path / "repo"
    for relative in _COPY_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for relative in _COPY_DIRS:
        shutil.copytree(ROOT / relative, root / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    reset_r3_allowlist(root)
    if track_open:
        set_track_open(root, True)
    return root


FIXTURE_FIRST_ORIGIN = "2026-01-02"


def reset_r3_allowlist(root: Path) -> None:
    """tmp 사본 계약을 r2 상태(r3 허용 목록 키 미기입·track_open·armed false)로 되돌린다.

    실계약은 r3 뒤 track_open true 지만 tmp 사본에는 실 prereg(mde_v1·identity 시도)를 복사하지 않는다 — 상태 의존
    단언은 실계약에 고정하지 않는다(spec_U3 리뷰 N18). r3 허용 목록 값만 되돌리므로 rule_hash 는 그대로다(C10).
    r2 상태 계약에는 아무것도 바꾸지 않는다(멱등).
    """
    import yaml

    path = root / "data/contracts/multivariate_timeseries_v15_coherence.yaml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(  first_origin_not_before: )'\d{4}-\d{2}-\d{2}'", r"\g<1>null", text, count=1)
    text = text.replace("mde:\n  status: computed\n", "mde:\n  status: not_computed\n", 1)
    text = re.sub(r"(?m)^  values_by_horizon: \{.*\}$",
                  "  values_by_horizon: {'5': null, '21': null, '63': null}", text, count=1)
    text = re.sub(r"(?m)^  per_arm:\n(?:    .*\n)+", "  per_arm: null\n", text, count=1)
    text = re.sub(r"(?m)^    summary_sha256: '[0-9a-f]{64}'$", "    summary_sha256: null", text, count=1)
    text = text.replace("development_protocol:\n  track_open: true\n", "development_protocol:\n  track_open: false\n", 1)
    text = text.replace("gates:\n  armed: true\n", "gates:\n  armed: false\n", 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    data = yaml.safe_load(text)
    assert data["live"]["first_origin_not_before"] is None
    assert data["mde"]["status"] == "not_computed" and data["mde"]["per_arm"] is None
    assert data["mde"]["values_by_horizon"] == {"5": None, "21": None, "63": None}
    assert data["mde"]["artifacts"]["summary_sha256"] is None
    assert data["development_protocol"]["track_open"] is False and data["gates"]["armed"] is False


def _replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


def set_track_open(root: Path, value: bool, *, preconditions: bool = True) -> None:
    """track_open 을 켠다. preconditions=True 면 r3 전제(첫 원점·MDE 기입·mde_v1 sha 핀·identity PASS·armed)도
    합성으로 채운다 — 로더가 track_open true 에 이 전제를 요구한다(계약 must_be_filled_before·armed_requires)."""
    import hashlib

    from ai_fc.timeseries_v8.contracts import canonical_hash

    if not value:
        return
    path = root / "data/contracts/multivariate_timeseries_v15_coherence.yaml"
    text = path.read_text(encoding="utf-8")
    text = _replace_once(text, "development_protocol:\n  track_open: false\n", "development_protocol:\n  track_open: true\n")
    if preconditions:
        prereg = root / "data/timeseries_v15/prereg"
        prereg.mkdir(parents=True, exist_ok=True)
        summary = prereg / "mde_v1.json"
        summary.write_text(json.dumps({"schema_version": 1, "kind": "fixture_mde_summary", "replay_sha256": {}},
                                      sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        identity = {"schema_version": 1, "kind": "v15_a0_live_identity_attempt", "v8_forecast_id": "v8-fixture",
                    "v8_origin": "2026-01-02", "status": "PASS", "max_abs_diff": 0.0, "mismatched_fields": [],
                    "computed_at": "2026-01-06T00:00:00+00:00"}
        identity["content_hash"] = canonical_hash(identity)
        (prereg / "a0_live_identity_2026-01-02_a1.json").write_text(json.dumps(identity), encoding="utf-8")
        digest = hashlib.sha256(summary.read_bytes()).hexdigest()
        text = _replace_once(text, "first_origin_not_before: null", f"first_origin_not_before: '{FIXTURE_FIRST_ORIGIN}'")
        text = _replace_once(text, "mde:\n  status: not_computed\n", "mde:\n  status: computed\n")
        text = _replace_once(text, "    summary_sha256: null\n", f"    summary_sha256: '{digest}'\n")
        text = _replace_once(text, "gates:\n  armed: false\n", "gates:\n  armed: true\n")
    path.write_text(text, encoding="utf-8", newline="\n")


def weekday_sessions(count: int, start: str = "2000-01-03") -> tuple[str, ...]:
    day = date.fromisoformat(start)
    out: list[str] = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return tuple(out)


def synthetic_market(count: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    endog = rng.normal(0.0002, 0.012, size=(count, 5))
    endog[:, 1] *= 3.0
    exog = rng.normal(0.0, 1.0, size=(count, 2))
    return endog, exog


def grid(h: int, *, shift: float = 0.0) -> list[float]:
    levels = (np.arange(200) + 0.5) / 200.0
    from scipy.stats import norm

    return [float(v) for v in shift + 0.01 * np.sqrt(h) * norm.ppf(levels)]


def horizons_block(*, shift: float = 0.0) -> dict[str, Any]:
    out = {}
    for h in (1, 5, 21, 63):
        values = grid(h, shift=shift)
        out[str(h)] = {"quantile_grid": values, "baseline_quantile_grid": grid(h, shift=0.0),
                       "p_up": float(np.mean(np.asarray(values) > 0)), "blend_weight": 1.0,
                       "recalibrated": True, "matured_pit_count": 900}
    return out


def v8_row(origin: str, knowledge_cutoff: str, *, number: int = 0) -> dict[str, Any]:
    return {
        "schema_version": 1, "forecast_id": f"tsv8-shadow-fake{number:04d}{origin.replace('-', '')}",
        "model_id": "shadow.mf_dfm_varx_calibrated_v8", "model_version": 8, "origin": origin,
        "iso_week": f"{date.fromisoformat(origin).isocalendar().year}-W{date.fromisoformat(origin).isocalendar().week:02d}",
        "knowledge_cutoff": knowledge_cutoff, "grid_levels_count": 200,
        "ensemble_weights": {"expanding": 0.5, "rolling": 0.5}, "block_length": 21, "ewma_lambda": 0.97,
        "horizons": horizons_block(),
    }


def write_v8_rows(root: Path, rows: list[dict[str, Any]]) -> None:
    path = root / "data/timeseries_v8/ledgers/shadow_forecasts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def stage_payload(root: Path, arm: str, reference: dict[str, Any], *, seed: int = 1234,
                  shift: float = 0.0, kernel: str | None = None) -> dict[str, Any]:
    from ai_fc.timeseries_v8.contracts import canonical_hash
    from ai_fc.timeseries_v15.arms import ARMS
    from ai_fc.timeseries_v15.calendar import calendar_hash
    from ai_fc.timeseries_v15.contracts import frozen_hash, load_contract_v15

    contract = load_contract_v15(root)
    payload = {
        "schema_version": 1, "kind": "v15_staged_forecast", "model_id": "shadow.mf_dfm_varx_coherence_v15",
        "model_version": 15, "arm": arm, "arm_spec": ARMS[arm].as_manifest(),
        "origin": reference["origin"], "iso_week": reference["iso_week"],
        "knowledge_cutoff": reference["knowledge_cutoff"], "data_snapshot_sha": "f" * 40,
        "v8_forecast_id": reference["forecast_id"], "contract_hash": frozen_hash(contract),
        "kernel_code_hash": kernel or contract["fork"]["frozen_kernel_code_hash"],
        "pipeline_code_hash": "p" * 64, "seed": seed,
        "seed_identity": {"model_id": "shadow.mf_dfm_varx_calibrated_v8", "model_version": 8},
        "config": {}, "grid_levels_count": 200,
        "ensemble_weights": dict(reference["ensemble_weights"]), "block_length": reference["block_length"],
        "ewma_lambda": reference["ewma_lambda"], "ewma_lambda_selected": reference["ewma_lambda"],
        "vol_mode_note": "v8", "horizons": horizons_block(shift=shift), "matured_origins_at_emit": 1000,
        "frame_provenance": {}, "calendar_hash": calendar_hash(reference["origin"]),
        "runtime_manifest": {"python": "x"}, "exchange_calendars_version": "4.13.2",
        "snapshot_method": "rev_list_first_parent_before_cutoff", "v8_run_head_sha": None,
        "probability_unit": "fraction", "official_status": "shadow_research_not_official",
        "notice": "참고 의견, 매매 신호 아님",
    }
    payload["content_hash"] = canonical_hash(payload)
    return payload


def write_stage(folder: Path, name: str, payload: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


@dataclass(frozen=True)
class Obs:
    series_id: str
    observation_time: str
    value: float
    observation_id: str = "obs"
    revision_seq: int = 1
    supersedes: str | None = None
    available_at: str = "2000-01-01T00:00:00+00:00"


def nasdaq_observations(start: str, end: str, *, base: float = 100.0, step: float = 0.001,
                        overrides: dict[str, float] | None = None) -> list[Obs]:
    """XNAS 세션마다 합성 NASDAQCOM 종가(로그 수익 step 고정)."""
    from ai_fc.timeseries_v15.calendar import sessions_between

    rows = []
    value = base
    for day in sessions_between(date.fromisoformat(start), date.fromisoformat(end)):
        value *= float(np.exp(step))
        close = (overrides or {}).get(day.isoformat(), value)
        rows.append(Obs("NASDAQCOM", day.isoformat(), close, observation_id=f"n-{day.isoformat()}"))
    return rows
