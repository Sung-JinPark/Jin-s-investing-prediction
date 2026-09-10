"""두 채점 경로가 같은 기후 기준선을 쓴다 — 그리고 T7 은 결과 전에 등록돼 있다.

2026-09-10 실측: 홀드아웃 채점(G1)은 동결 아티팩트의 `clim_base_rate` 를 썼는데
라이브 채점(`resolve.py`)은 계약 표를 읽었다. 계약 표는 아티팩트의 소수 4자리 전사인데
RV 3셀에서 전사가 어긋난다(rv_h21 0.6760 vs 0.67084797). 배선 자격 셀 두 개가 모두 그 안에
있어, 성숙 원점 60개 뒤 라이브 BSS 를 홀드아웃 BSS 와 비교할 때 기준이 달라진다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
HOLDOUT = ROOT / "data/timeseries_v13/runs/holdout_V13VOL_champion_aec80c65038b.json"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_live_scoring_uses_the_frozen_artifact_baseline() -> None:
    from ai_fc.timeseries_v13 import contracts as C
    from ai_fc.timeseries_v13.resolve import climatology_map

    contract = C.load_contract_v13(ROOT)
    pin = contract["frozen_coefficients"]
    frozen = C.load_frozen_coefficients(
        ROOT,
        expected_sha256=pin["sha256"],
        expected_content_hash=pin["content_hash"],
        expected_finalist_id=contract["gates"]["champion"]["finalist_id"],
    )
    live = climatology_map(contract, frozen)
    for cell, spec in frozen["cells"].items():
        assert abs(live[cell] - float(spec["clim_base_rate"])) < 1e-12, (
            f"{cell}: 라이브 기준선이 동결 아티팩트와 다르다")


def test_live_baseline_matches_what_the_holdout_actually_used() -> None:
    """상수 기준선의 Brier 는 BS = r(1-p)^2 + (1-r)p^2 로 닫혀 있다 — 역산해 대조한다."""
    if not HOLDOUT.is_file():
        pytest.skip("홀드아웃 산출물 없음")
    from ai_fc.timeseries_v13 import contracts as C
    from ai_fc.timeseries_v13.resolve import climatology_map

    contract = C.load_contract_v13(ROOT)
    pin = contract["frozen_coefficients"]
    frozen = C.load_frozen_coefficients(
        ROOT,
        expected_sha256=pin["sha256"],
        expected_content_hash=pin["content_hash"],
        expected_finalist_id=contract["gates"]["champion"]["finalist_id"],
    )
    live = climatology_map(contract, frozen)
    holdout = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    for cell, record in holdout["cells"].items():
        rate = float(record["guard"]["base_rate"])
        recorded = float(record["G1_vs_climatology"]["bs_baseline"])
        p = live[cell]
        predicted = rate * (1 - p) ** 2 + (1 - rate) * p ** 2
        assert abs(predicted - recorded) < 1e-9, (
            f"{cell}: 라이브 기준선으로 홀드아웃 bs_baseline 이 재현되지 않는다 "
            f"(예측 {predicted:.10f} vs 기록 {recorded:.10f})")


def test_contract_table_bytes_were_not_edited() -> None:
    """동결 좌표는 결과 후에 고치지 않는다 — 표는 그대로 두고 코드만 고쳤다."""
    declared = _contract()["climatology_base_rates"]
    assert declared["rv_exceedance"]["h21"] == 0.6760
    assert declared["rv_exceedance"]["h63"] == 0.8751
    assert declared["vix_touch"]["K25_h5"] == 0.3076


def test_t7_was_registered_before_any_origin_matured() -> None:
    """종결 조건은 결과를 보기 전에 못박아야 의미가 있다."""
    block = _contract()["live_forward_termination"]
    assert block["registered_before_results"] is True
    evidence = block["evidence_at_registration"]
    assert evidence["matured_origins"] == 0
    assert evidence["resolutions_ledger_rows"] == 0

    resolutions = ROOT / "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl"
    rows = 0
    if resolutions.is_file():
        rows = sum(1 for line in resolutions.read_text(encoding="utf-8").splitlines() if line.strip())
    if rows:
        pytest.skip("성숙 채점이 시작된 뒤에는 등록 시점 증거만 고정한다")

    rule = block["T7"]["rule"]
    assert "2셀 이상" in rule
    for cell in ("rv_h5", "rv_h21", "vix25_h21"):
        assert cell in rule, f"통과 셀 {cell} 이 T7 규칙에 없다"


def test_t7_does_not_touch_the_existing_gate_block() -> None:
    gate = _contract()["live_forward_gate"]
    assert gate["registered"] == "2026-09-08"
    assert gate["minimum_matured_origins_per_cell"] == 60
    assert gate["execution_path"] == "named_verb_guarded"
