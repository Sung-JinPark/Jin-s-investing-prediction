"""V8 XNAS 진단 라벨 원장 (설계서 P1) — 오라클은 실제 저장소 데이터, 쓰기는 tmp 사본에만.

실데이터 오라클은 고정 원점 집합과 '<= 2026-11-09' 기준일로 묶어 원장이 자라도 깨지지 않게 한다.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research import v8_xnas_labels as X
from ai_fc.mts_research.artifacts import MtsArtifactError, read_chain

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
AS_OF = date(2026, 11, 9)

# 2026-11-11 기준 원장 해소 29쌍 — 지평별 고정 원점 집합
RESOLVED_ORIGINS = {
    1: {"2026-08-14", "2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25",
        "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-10-30"},
    21: {"2026-08-14", "2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25",
         "2026-10-02"},
}
RESOLVED_ORIGINS[5] = set(RESOLVED_ORIGINS[1])
FIRST_TWELVE = RESOLVED_ORIGINS[1] | {"2026-11-06"}

COPY_FOR_TMP = [
    "data/timeseries_v2/ledgers/market_observations.jsonl",
    "data/timeseries_v8/ledgers/shadow_forecasts.jsonl",
    "data/timeseries_v8/ledgers/shadow_resolutions.jsonl",
    "data/timeseries_v13/ledgers/vol_live_resolutions.jsonl",
    "data/timeseries_daily6m/ledgers/forecasts.jsonl",
    "data/timeseries_daily6m/ledgers/resolutions.jsonl",
    "data/mts_research/contracts/coherence_monitor_thresholds_v1.json",
    "data/contracts/nyse_holidays.yaml",
]
SHADOW_LEDGERS = [X.V8_FORECAST_LEDGER, X.V8_RESOLUTION_LEDGER]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_hashes() -> dict[str, str]:
    """설계 §3.0 — 봉인 모델 코드 해시(V8·V2·daily6m)를 실행 전후로 대조한다."""
    from ai_fc.timeseries_daily6m.contracts import model_code_hash as daily6m_hash
    from ai_fc.timeseries_v2.contracts import model_code_hash as v2_hash
    from ai_fc.timeseries_v8.contracts import model_code_hash as v8_hash

    return {"v8": v8_hash(ROOT), "v2": v2_hash(ROOT), "daily6m": daily6m_hash(ROOT)}


@pytest.fixture(scope="module")
def real():
    before = {p: _sha(ROOT / p) for p in SHADOW_LEDGERS}
    code_before = _code_hashes()
    context = X._load_context(ROOT, now=NOW, as_of=AS_OF)
    pairs = X._pairs(context)
    rows = [p["row"] for p in pairs if p["row"] is not None]
    summary = X._summary(context, pairs)
    integrity = X.integrity_checks(ROOT, _context=context, _pairs_cache=pairs)
    after = {p: _sha(ROOT / p) for p in SHADOW_LEDGERS}
    return {"context": context, "pairs": pairs, "rows": rows, "summary": summary,
            "integrity": integrity, "before": before, "after": after,
            "code_before": code_before, "code_after": _code_hashes()}


def _fixed(rows, horizons=(1, 5, 21)):
    """원장 해소 29쌍(고정 원점 집합)에 해당하는 행만."""
    return [r for r in rows if r["h"] in horizons and r["origin"] in RESOLVED_ORIGINS[r["h"]]]


def _row(rows, origin, h):
    return next(r for r in rows if r["origin"] == origin and r["h"] == h)


# --- 오라클 1·2: grid 에서 빠지는 2026 XNAS 세션과 영향 행 -----------------------------


def test_grid_drops_2026_confirmed_and_projected(real):
    grid = real["summary"]["grid"]
    assert grid["confirmed_dropped_since_first_origin"] == ["2026-10-12"]
    assert "2026-11-11" in grid["projected_dropped_next_120d"]
    assert real["summary"]["single_episode"] is True
    assert real["summary"]["single_episode_note"] == "2026-10-12 holiday"


def test_affected_resolved_rows_exactly_six(real):
    fixed = _fixed(real["rows"])
    affected = sorted((r["origin"], r["h"]) for r in fixed
                      if r["xnas_target_session"] != r["grid_target_session"])
    assert affected == sorted([
        ("2026-09-11", 21), ("2026-09-18", 21), ("2026-09-25", 21), ("2026-10-02", 21),
        ("2026-10-09", 1), ("2026-10-09", 5),
    ])
    first = _row(fixed, "2026-09-11", 21)
    assert (first["xnas_target_session"], first["grid_target_session"]) == ("2026-10-12", "2026-10-13")
    h1 = _row(fixed, "2026-10-09", 1)
    assert round(h1["y_ledger"], 5) == -0.00153 and round(h1["y_xnas"], 5) == -0.00440
    h5 = _row(fixed, "2026-10-09", 5)
    assert h5["ledger_grid_scores"]["pit"] == pytest.approx(0.065)
    assert h5["pit"] == pytest.approx(0.02)
    assert all(r["dropped_sessions_confirmed"] == ["2026-10-12"] for r in fixed
               if (r["origin"], r["h"]) in affected)


# --- 오라클 3: 항등식·CRPS 비트 재현 --------------------------------------------------


def test_identity_and_crps_bit_reproduction(real):
    fixed = _fixed(real["rows"])
    assert len(fixed) == 29
    assert all(r["stage"] == "reconciled" for r in fixed)
    assert max(abs(r["identity_resid"]) for r in fixed) <= X.IDENTITY_TOLERANCE
    assert all(r["ledger_grid_scores"]["crps_bit_reproduced"] for r in fixed)
    crps = real["integrity"]["v8"]["crps_bit_reproduction"]
    assert crps["failures"] == [] and crps["max_abs_diff"] < 1e-12 and crps["n"] >= 29


# --- 오라클 4: 발행 시점 post_dated -------------------------------------------------------


def test_post_dated_h1_all_h5_only_first(real):
    timing = [r for r in real["summary"]["emission_timing"]["rows"] if r["origin"] in FIRST_TWELVE]
    assert len(timing) == 12
    assert all(r["h1_target_closed_at_emit"] for r in timing)
    assert [r["origin"] for r in timing if r["h5_target_closed_at_emit"]] == ["2026-08-14"]
    h1_rows = [r for r in real["rows"] if r["h"] == 1 and r["origin"] in FIRST_TWELVE]
    assert len(h1_rows) == 12 and all(r["target_closed_at_emit"] for r in h1_rows)


# --- 수용 기준: basis 별 skill 재현 ------------------------------------------------------


def test_skill_by_basis_reproduces_audit(real):
    fixed = _fixed(real["rows"])
    grid_records = [{"origin": r["origin"], "h": r["h"], **r["ledger_grid_scores"]} for r in fixed]
    grid = X._skill_cohort(grid_records, 8)
    xnas = X._skill_cohort(fixed, 8)
    assert round(grid["h5"]["skill"], 4) == 0.0068 and round(xnas["h5"]["skill"], 4) == -0.0073
    assert round(grid["h21"]["skill"], 4) == 0.0155 and round(xnas["h21"]["skill"], 4) == -0.0018
    assert round(grid["h1"]["skill"], 4) == -0.0543 and round(xnas["h1"]["skill"], 4) == -0.0572
    assert grid["h21"]["sufficiency"] == "insufficient"  # n_origin 7 < 8 (사전고정 최소 표본)
    lo, hi = xnas["h5"]["ci90"]
    assert lo < 0 < hi


def _fixed_context(context):
    """고정 원점 12개·해소 29쌍으로 묶은 문맥 — 원장이 자라도 요약 오라클이 그대로다."""
    resolved = {(o, h) for h, origins in RESOLVED_ORIGINS.items() for o in origins}
    return dataclasses.replace(
        context,
        forecasts=[f for f in context.forecasts if f["origin"] in FIRST_TWELVE],
        resolutions=[r for r in context.resolutions if (r["origin"], int(r["horizon"])) in resolved],
    )


def test_summary_skill_by_basis_wiring(real):
    context = _fixed_context(real["context"])
    skill = X._summary(context, X._pairs(context))["skill_by_basis"]
    grid = skill[X.GRID_BASIS]
    matched = skill[X.LABEL_BASIS]["matched_ledger_rows"]
    closed = skill[X.LABEL_BASIS]["all_closed_targets"]
    # grid basis = 원장 model_crps·baseline_crps (ledger_grid_scores), XNAS = 행 자체 점수
    assert [round(grid[f"h{h}"]["skill"], 4) for h in (1, 5, 21)] == [-0.0543, 0.0068, 0.0155]
    assert [round(matched[f"h{h}"]["skill"], 4) for h in (1, 5, 21)] == [-0.0572, -0.0073, -0.0018]
    assert [grid[f"h{h}"]["n"] for h in (1, 5, 21)] == [11, 11, 7]
    assert [matched[f"h{h}"]["n"] for h in (1, 5, 21)] == [11, 11, 7]
    assert [closed[f"h{h}"]["n"] for h in (1, 5, 21)] == [12, 11, 8]
    assert round(closed["h1"]["skill"], 4) == -0.0395 and round(closed["h21"]["skill"], 4) == -0.0302
    # 미달 지평이 있으면 평균도 미달 — n 과 함께 전파
    for block in (grid, matched):
        mean = block["mean_h1_h5_h21"]
        assert mean["sufficiency"] == "insufficient" and mean["insufficient_horizons"] == ["h21"]
        assert mean["n"] == 29 and mean["n_by_h"] == {"h1": 11, "h5": 11, "h21": 7}
    assert round(matched["mean_h1_h5_h21"]["skill"], 4) == -0.0221
    assert round(grid["mean_h1_h5_h21"]["skill"], 4) == -0.0106  # 감사 보고 −1.06%


def test_unresolved_pairs_exposed_to_holidays(real):
    pairs = [p for p in real["pairs"] if p["origin"] in FIRST_TWELVE]
    resolved = {(o, h) for h, origins in RESOLVED_ORIGINS.items() for o in origins}
    unresolved = [p for p in pairs if (p["origin"], p["h"]) not in resolved]
    assert len(unresolved) == 19
    exposed = [p for p in unresolved if p["dropped_sessions_confirmed"] or p["dropped_sessions_projected"]]
    projected = [p for p in unresolved if p["dropped_sessions_projected"]]
    assert len(exposed) == 18 and len(projected) == 17
    assert {(p["origin"], p["h"]) for p in unresolved if p not in exposed} == {("2026-11-06", 1)}
    first_h63 = next(p for p in unresolved if p["origin"] == "2026-08-14" and p["h"] == 63)
    assert first_h63["xnas_target_session"] == "2026-11-12"
    assert first_h63["grid_target_session"] == "2026-11-16"
    assert first_h63["ledger_resolution_eta"] == "2026-11-24T03:10:00+00:00"


def test_ledger_resolution_eta_holiday_monday():
    assert X.ledger_resolution_eta(date(2026, 11, 16)).isoformat() == "2026-11-24T03:10:00+00:00"
    # 2027-01-18(월) MLK → H.10 화 16:15 ET → 수 03:10Z
    assert X.ledger_resolution_eta(date(2027, 1, 11)).isoformat() == "2027-01-20T03:10:00+00:00"


# --- 오라클 7: basis 분리 -----------------------------------------------------------------


def test_summary_keeps_bases_separate(real):
    summary = real["summary"]
    assert set(summary["skill_by_basis"]) == {X.GRID_BASIS, X.LABEL_BASIS}
    assert summary["label_basis_mixing"] == "prohibited"
    text = json.dumps(summary["skill_by_basis"])
    for forbidden in ("mixed", "combined", "pooled", "all_bases"):
        assert forbidden not in text
    for key in ("display_only", "scoring_excluded", "notice", "n", "n_origins", "n_dates", "single_episode"):
        assert key in summary
    assert summary["notice"] == "참고 의견, 매매 신호 아님"
    assert summary["primary_comparison"]["basis_pair"][1].endswith("matched_ledger_rows")
    assert any("serial overlap ignored" in c for c in summary["bootstrap"]["caveats"])


# --- 무결성 (CAL-05/06) ---------------------------------------------------------------------


def test_integrity_checks_pass_on_repository(real):
    integrity = real["integrity"]
    assert integrity["status"] == "PASS", integrity["failed_checks"]
    assert integrity["v13"]["n"] >= 189 and integrity["v13"]["mismatches"] == []
    assert integrity["daily6m"]["mismatches"] == []
    assert integrity["v8"]["forecast_id_derivation_mismatch"] == []
    assert integrity["v8_grid"]["ledger_vs_predicted_grid_mismatch"] == []
    archive = real["summary"]["archive"]
    assert "2019-04-19" in archive["non_session_rows"]["NASDAQCOM"]["dates"]
    assert archive["non_session_rows"]["VIX"]["n"] >= 33


def test_sealed_code_and_shadow_ledgers_untouched(real):
    from ai_fc.timeseries_v8.contracts import model_code_hash

    assert real["before"] == real["after"]
    assert real["code_before"] == real["code_after"]
    forecasts = X._read_jsonl(ROOT, X.V8_FORECAST_LEDGER)
    assert model_code_hash(ROOT) == forecasts[-1]["model_code_hash"]


# --- 오라클 5: 합성 아카이브 — 비세션 행 무시·세션 결측 fail-closed --------------------


def _synthetic(cal: X.XnasCalendar, *, drop: date | None = None, extra: date | None = None):
    closes = {}
    value = 20000.0
    for index, day in enumerate(cal.sessions):
        value *= math.exp(0.001 * ((index % 7) - 3))
        if day != drop:
            closes[day] = value
    if extra is not None:
        closes[extra] = 1.0  # 비세션 행 — 조회되면 수익이 터무니없어진다
    series = {name: frozenset(closes) for name in X.GRID_CONFIRM_SERIES}
    series["NASDAQCOM"] = frozenset(closes)
    return X.NasdaqArchive(closes=closes, series_dates=series, as_of=date(2026, 12, 31))


def _forecast(origin: str) -> dict:
    grid = list(np.linspace(-0.1, 0.1, 200))
    block = {"quantile_grid": grid, "baseline_quantile_grid": grid, "p_up": 0.6}
    return {"forecast_id": "tsv8-shadow-synthetic", "model_id": "synthetic", "origin": origin,
            "knowledge_cutoff": "2026-11-17T03:10:00+00:00", "grid_levels_count": 200,
            "horizons": {str(h): block for h in X.HORIZONS}}


def test_non_session_archive_row_does_not_shift_target():
    cal = X.XnasCalendar.build(date(2026, 11, 1), date(2026, 12, 31))
    clean = _synthetic(cal)
    noisy = _synthetic(cal, extra=date(2026, 11, 26))  # 추수감사절(비세션)
    grid = list(cal.sessions)
    a = X.diagnose_row(_forecast("2026-11-20"), 5, clean, cal, grid, None)
    b = X.diagnose_row(_forecast("2026-11-20"), 5, noisy, cal, grid, None)
    assert a["xnas_target_session"] == b["xnas_target_session"] == "2026-11-30"
    assert a["y_xnas"] == b["y_xnas"]


def test_missing_xnas_session_fails_closed():
    cal = X.XnasCalendar.build(date(2026, 11, 1), date(2026, 12, 31))
    archive = _synthetic(cal, drop=date(2026, 11, 24))
    grid = list(cal.sessions)
    assert X.diagnose_row(_forecast("2026-11-20"), 5, archive, cal, grid, None) is None
    with pytest.raises(X.V8XnasLabelError):
        X.xnas_target_session(date(2026, 11, 26), 1, cal)  # 비세션 원점


def test_grid_dropped_sessions_projection():
    cal = X.XnasCalendar.build(date(2026, 10, 1), date(2026, 12, 31))
    grid = [d for d in cal.sessions if d != date(2026, 11, 11)]
    assert X.grid_dropped_sessions(date(2026, 11, 6), date(2026, 11, 16), grid, cal) == [date(2026, 11, 11)]
    assert X.grid_target_session(date(2026, 11, 6), 5, grid) == date(2026, 11, 16)
    assert X.xnas_target_session(date(2026, 11, 6), 5, cal) == date(2026, 11, 13)


# --- 오라클 6·8: tmp 사본에서 append 멱등·체인·원본 무변경 ----------------------------


@pytest.fixture(scope="module")
def tmp_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("xnas") / "repo"
    for relative in COPY_FOR_TMP:
        source = ROOT / relative
        if source.is_file():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return root


def _args(append: bool) -> argparse.Namespace:
    return argparse.Namespace(as_of=AS_OF.isoformat(), append=append, report=None, kind=None,
                              now=NOW.isoformat())


def test_cli_append_idempotent_and_chain(tmp_repo):
    before = {p: _sha(tmp_repo / p) for p in SHADOW_LEDGERS}
    code, dry = X.run_cli(tmp_repo, _args(False))
    assert code == 0 and dry["mode"] == "dry_run" and dry["integrity_status"] == "PASS"
    assert not (tmp_repo / X.LEDGER_RELATIVE).exists()
    code, first = X.run_cli(tmp_repo, _args(True))
    assert code == 0 and first["appended"] == len(dry["rows"]) > 0
    code, second = X.run_cli(tmp_repo, _args(True))
    assert code == 0 and second["appended"] == 0
    rows = read_chain(tmp_repo, X.LEDGER_RELATIVE)
    assert len(rows) == first["appended"]
    assert all(r["scoring_excluded"] and r["display_only"] for r in rows)
    assert all(r["label_basis"] == X.LABEL_BASIS for r in rows)
    summary = json.loads((tmp_repo / X.SUMMARY_RELATIVE).read_text(encoding="utf-8"))
    assert summary["ledger"]["fresh_rows_covered"] is True
    assert summary["integrity"]["diagnostics_chain"]["ok"] is True
    assert {p: _sha(tmp_repo / p) for p in SHADOW_LEDGERS} == before


def test_measured_change_without_input_change_is_recomputation(tmp_repo):
    rows = read_chain(tmp_repo, X.LEDGER_RELATIVE)
    assert rows, "선행 테스트가 원장을 만든다"
    original = {k: v for k, v in rows[0].items() if k not in ("previous_hash", "content_hash")}
    ulp = dict(original, y_xnas=original["y_xnas"] + 1e-15)  # 환경 간 ulp 차이 — 정정 아님
    assert X.append_diagnostics(tmp_repo, [ulp]) == 0
    revised = dict(original, y_xnas=original["y_xnas"] + 1e-6)
    assert X.append_diagnostics(tmp_repo, [revised]) == 1
    assert X.append_diagnostics(tmp_repo, [revised]) == 0
    latest = read_chain(tmp_repo, X.LEDGER_RELATIVE)[-1]
    assert latest["diagnostic_id"] == f"{original['diagnostic_key']}-c1"
    assert latest["supersedes"] == original["diagnostic_id"]
    assert latest["correction_reason"] == "recomputation"  # 입력 출처 해시가 그대로


def test_tampered_ledger_fails_closed(tmp_repo, tmp_path):
    copy = tmp_path / "copy"
    target = copy / X.LEDGER_RELATIVE
    target.parent.mkdir(parents=True)
    lines = (tmp_repo / X.LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["y_xnas"] = 0.0
    target.write_text("\n".join([json.dumps(tampered)] + lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(MtsArtifactError):
        read_chain(copy, X.LEDGER_RELATIVE)


# --- run_cli 종단: 아카이브 개정 회복 경로·거부 경로 --------------------------------------


def _make_repo(base: Path) -> Path:
    root = base / "repo"
    for relative in COPY_FOR_TMP:
        source = ROOT / relative
        if source.is_file():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return root


def _revise_nasdaq(root: Path, day: str, factor: float) -> None:
    """tmp 아카이브 사본에 NASDAQCOM 개정 행(revision_seq+1, supersedes) 1개를 덧붙인다."""
    path = root / "data/timeseries_v2/ledgers/market_observations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    prior = max((json.loads(line) for line in lines
                 if f'"observation_time":"{day}"' in line and '"NASDAQCOM"' in line),
                key=lambda row: row["revision_seq"])
    revised = dict(prior, observation_id="market-observation-testrevision000000000000",
                   revision_seq=prior["revision_seq"] + 1, supersedes=prior["observation_id"],
                   value=prior["value"] * factor, available_at="2026-11-11T09:00:00+00:00",
                   vintage_start="2026-11-11T09:00:00+00:00")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(revised, sort_keys=True, separators=(",", ":")) + "\n")


def _args_at(as_of: str, append: bool) -> argparse.Namespace:
    return argparse.Namespace(as_of=as_of, append=append, report=None, kind=None, now=NOW.isoformat())


def test_archive_revision_recovers_through_run_cli(tmp_path):
    root = _make_repo(tmp_path)
    shadow_before = {p: _sha(root / p) for p in SHADOW_LEDGERS}
    code, first = X.run_cli(root, _args(True))
    assert code == 0 and first["appended"] > 0
    _revise_nasdaq(root, "2026-10-12", 1.001)  # 원장 grid 가 건너뛴 날의 종가 +0.1%

    code, dry = X.run_cli(root, _args(False))
    integrity = dry["summary"]["integrity"]
    assert code == 0 and integrity["status"] == "PASS", integrity["failed_checks"]
    grid = integrity["v8_grid"]
    assert grid["identity_resid_violations"] == 0 and grid["identity_resid_unexplained"] == []
    explained = grid["identity_resid_explained_by_archive_revision"]
    assert {("2026-10-09", 1), ("2026-09-11", 21)} <= {(e["origin"], e["h"]) for e in explained}
    assert all("2026-10-12" in e["revised_sessions"] for e in explained)

    code, second = X.run_cli(root, _args(True))
    assert code == 0 and second["mode"] == "append" and second["appended"] > 0
    rows = read_chain(root, X.LEDGER_RELATIVE)
    corrections = rows[first["appended"]:]
    assert len(corrections) == second["appended"]
    assert all(r["diagnostic_id"] == f"{r['diagnostic_key']}-c1" for r in corrections)
    assert all(r["correction_reason"] == "archive_revision" for r in corrections)
    originals = {r["diagnostic_id"] for r in rows[:first["appended"]]}
    assert all(r["supersedes"] in originals for r in corrections)
    h1 = next(r for r in corrections if r["origin"] == "2026-10-09" and r["h"] == 1)
    assert h1["identity_status"] == "explained_by_archive_revision"
    assert h1["archive_revised_inputs"][0]["day"] == "2026-10-12"

    code, third = X.run_cli(root, _args(True))
    assert code == 0 and third["appended"] == 0  # 개정 반영 뒤 멱등
    assert {p: _sha(root / p) for p in SHADOW_LEDGERS} == shadow_before  # V8 원장 무변경

    # 소급 기준일 append 거부 — 원장에 reconciled 뒤 provisional 이 붙지 않게
    size = (root / X.LEDGER_RELATIVE).stat().st_size
    code, back = X.run_cli(root, _args_at("2026-10-30", True))
    assert code == 2 and back["mode"] == "append_refused" and "소급" in back["detail"]
    assert X.run_cli(root, _args_at("2026-10-30", False))[0] == 0
    assert (root / X.LEDGER_RELATIVE).stat().st_size == size


def test_tampered_diagnostics_ledger_refuses_append_via_cli(tmp_path):
    root = _make_repo(tmp_path)
    assert X.run_cli(root, _args(True))[0] == 0
    path = root / X.LEDGER_RELATIVE
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["y_xnas"] = 0.0
    path.write_text("\n".join([json.dumps(tampered)] + lines[1:]) + "\n", encoding="utf-8")
    before = _sha(path)
    code, payload = X.run_cli(root, _args(True))
    assert code == 2 and payload["mode"] == "append_refused"
    assert "diagnostics_chain" in payload["summary"]["integrity"]["failed_checks"]
    assert _sha(path) == before


def _resolution(y: float) -> dict:
    return {"resolved_session": "2026-11-23", "model_crps": 0.0, "baseline_crps": 0.0,
            "covered_p10_p90": True, "actual_log_return": y}


def test_identity_violation_status_split():
    assert X._identity_status(1e-15, []) == "ok"
    assert X._identity_status(1e-6, []) == "violation"
    revised = [{"day": "2026-10-12", "observation_id": "x", "revision_seq": 2, "supersedes": "y"}]
    assert X._identity_status(1e-6, revised) == "explained_by_archive_revision"
    cal = X.XnasCalendar.build(date(2026, 11, 1), date(2026, 12, 31))
    archive = _synthetic(cal)
    forecast = _forecast("2026-11-20")
    exact = math.log(archive.close(date(2026, 11, 23)) / archive.close(date(2026, 11, 20)))
    good = X.diagnose_row(forecast, 1, archive, cal, list(cal.sessions), _resolution(exact))
    assert good["identity_status"] == "ok"
    bad = X.diagnose_row(forecast, 1, archive, cal, list(cal.sessions), _resolution(0.5))
    assert bad["identity_status"] == "violation"  # 개정 없는 위반은 FAIL 쪽으로 남는다
