"""rung-7/8 공공영역 블록 — 사전등록·PIT·산출물 대사 검사 (rung-4 테스트 미러).

새로 생긴 위험은 둘이다: ① 외부 적재(달력·CFTC)의 PIT 규칙이 발표 전 값을 원점에 쓰는 것 ② 결과 후 블록·규칙이 바뀌는 것.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
diag = pytest.importorskip("v13_vol_rung7_diagnostics")
cftc = pytest.importorskip("v13_fetch_cftc_tff")

CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml"
LEDGER = ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_window_count_uses_the_label_window_only() -> None:
    """블록 창 = 세션 i+1..i+h — 라벨(labels_vix) 과 같은 창. 당일(i) 의 이벤트는 세지 않는다."""
    marks = np.zeros(10); marks[3] = 1.0; marks[7] = 1.0
    out = diag.window_count(marks, 3)
    assert out[2] == 1.0 and out[3] == 0.0, "i=3 의 창은 4..6 — 당일(3) 이벤트는 제외"
    assert out[4] == 1.0 and out[6] == 1.0
    assert np.isnan(out[7:]).all(), "창이 패널을 넘는 원점(i >= n-h)은 NaN(라벨과 동일)"


def test_sessions_since_counts_from_the_last_event_inclusive_of_today() -> None:
    flags = np.array([False, True, False, False, True, False])
    out = diag.sessions_since(flags)
    assert np.isnan(out[0]) and out[1] == 0 and out[3] == 2 and out[4] == 0 and out[5] == 1


def test_cftc_availability_is_never_before_the_friday_release() -> None:
    """보고 기준일(화) + 7달력일 = 다음 화요일 — 금요일 15:30 ET 공표보다 항상 늦다. 2013 셧다운 백로그는 11-08 고정."""
    avail, rule = cftc.available_at(date(2012, 3, 6))          # 화요일
    assert avail == "2012-03-13" and rule.startswith("report_date_plus_7")
    assert date.fromisoformat(avail) > date(2012, 3, 9), "금요일 공표 전에 쓰지 않는다"
    avail, rule = cftc.available_at(date(2013, 10, 15))
    assert avail == "2013-11-08" and rule.startswith("shutdown_backlog")
    avail, _ = cftc.available_at(date(2013, 11, 5))
    assert avail == "2013-11-12"


def test_positioning_series_never_uses_an_unreleased_report() -> None:
    rows = [json.loads(l) for l in (ROOT / "data/timeseries_v13/exog/cftc_tff_positions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    vix = sorted((r for r in rows if r["contract_code"] == "1170E1"), key=lambda r: r["report_date"])
    for r in vix:
        assert r["available_at"] > r["report_date"], r
        assert (date.fromisoformat(r["available_at"]) - date.fromisoformat(r["report_date"])).days >= 7
    # 2008-12~2009-05 미보고 구간은 step-fill 되지 않는다 (stale 21일 → NaN)
    dates = ["2009-03-03"]
    out = diag.positioning_series(dates, "1170E1", "lev_net_over_oi")
    assert np.isnan(out[0]), "6개월 미보고 구간을 직전 보고로 채우면 안 된다"


def test_scheduled_events_exclude_unscheduled_fomc_and_record_shutdown_vintage() -> None:
    rows = [json.loads(l) for l in (ROOT / "data/timeseries_v13/exog/scheduled_events_2007_2014.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    scheduled = [r for r in rows if r["kind"] == "fomc_scheduled"]
    unscheduled = [r for r in rows if r["kind"] == "fomc_unscheduled"]
    assert len(scheduled) == 64 and all(r["in_block"] for r in scheduled)
    assert len(unscheduled) == 18 and not any(r["in_block"] for r in unscheduled)
    assert "2008-01-21" in {r["event_date"] for r in unscheduled}, "2008-01-22 긴급 인하 전 전화회의는 비예정"
    shifted = {(r["kind"], r["event_date"]): r["originally_scheduled"] for r in rows if r.get("shutdown_shift")}
    assert shifted == {("bls_empsit", "2013-10-22"): "2013-10-04", ("bls_empsit", "2013-11-08"): "2013-11-01",
                       ("bls_cpi", "2013-10-30"): "2013-10-16", ("bls_cpi", "2013-11-20"): "2013-11-15"}


def test_contract_registers_both_rungs_before_results() -> None:
    contract = _contract()
    for key, n_blocks in (("rung7_public_blocks", 3), ("rung8_public_blocks", 3)):
        spec = contract[key]
        assert spec["prereg_commit"] and spec["prereg_commit"] != "null", "결과 전 커밋 해시가 기입돼야 한다"
        assert spec["backtest_windows_opened"] == 0 and spec["holdout_slot_consumed"] == 0
        assert len(spec["blocks"]) == n_blocks
        assert {b["class"] for b in spec["blocks"]} == {"calendar", "positioning", "regime_memory"}, "클래스당 1블록"
        assert "홀드아웃 결과로 셀을 고르지 않는다" in spec["cells"] or "9셀 전수" in spec["cells"]
        assert spec["diagnostics"].endswith("rung7_candidate_diagnostics.json")
    r7 = contract["rung7_public_blocks"]["selection_rules_applied"]
    assert r7["R1_auto_reject_abs_corr_gt"] == 0.85 and r7["R3_block_degenerate_mode_share_ge"] == 0.90
    assert contract["development_protocol"]["evaluations_spent"] == 8


def test_diagnostics_are_label_free_and_rules_were_applied_as_registered() -> None:
    path = ROOT / "data/timeseries_v13/prereg/rung7_candidate_diagnostics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["label_free"] is True
    from ai_fc.timeseries_v13.contracts import canonical_hash
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    assert canonical_hash(body) == payload["content_hash"]
    summary = payload["summary"]
    assert not summary["D1_log_sessions_since_event"]["R1_auto_reject_any_cell"], "0.844 는 0.85 미만 — 규칙상 통과"
    assert sorted(summary["E1_fomc_in_window"]["R3_degenerate_cells"]) == ["rv_h63", "vix25_h63", "vix30_h63"]
    excluded = {(e["cell"], e["block"]) for e in _contract()["rung7_public_blocks"]["excluded_cells"]}
    assert excluded == {(c, "E1_fomc_in_window") for c in ("rv_h63", "vix25_h63", "vix30_h63")}


@pytest.mark.parametrize("rung,label", [(7, "V13VOL_rung7_public"), (8, "V13VOL_rung8_public_secondary")])
def test_result_artifact_matches_the_ledger_row(rung: int, label: str) -> None:
    out = ROOT / f"data/timeseries_v13/vol/ladder_rung{rung}_public.json"
    if not out.is_file():
        pytest.skip(f"rung-{rung} 미실행")
    payload = json.loads(out.read_text(encoding="utf-8"))
    from ai_fc.timeseries_v13.contracts import canonical_hash
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    assert canonical_hash(body) == payload["content_hash"]
    assert payload["holdout_read"] is False and payload["sealed_read"] is False
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next(r for r in rows if r["experiment_label"] == label)
    assert row["results_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert row["prereg_commit"] == _contract()[f"rung{rung}_public_blocks"]["prereg_commit"]
    # 채택 셀은 전부 퇴화(episode_thin) — 배선·홀드아웃 근거가 아니다
    for key in payload["adopted"]:
        assert payload["cells"][key]["verdict"] == "adopted_episode_thin", key
