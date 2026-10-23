"""V14 조건부 도구(tools/v14_cond_diagnostics.py · tools/v14_cond_run.py) — 합성 데이터·임시 경로만.

실제 아카이브·실제 원장은 건드리지 않는다: read_market_observations 는 monkeypatch, 러너의 ROOT 는 tmp_path.
러너는 실제 저장소 루트에 대해 어떤 모드로도 돌리지 않는다(평가 예산은 1회용이고 결과는 사전등록 커밋 전에 보지 않는다).

고정하는 것:
  (a) 조건부 부분집합 마스크·셀 사양  (b) 압축 부분열 라벨 = 전체 패널 라벨의 제한  (c) R1~R4·가드 밴드
  (c′) label_free_report 는 라벨 빌더가 터져도 같은 등록을 낸다 — 라벨 접촉 플래그는 구조에서 나온다(F10)
  (c″) P0 도구는 산출물이 있으면 덮어쓰지 않는다(F3)
  (d) 러너 거부 경로 — 양성 대조(유효 사양은 None) + 각 거부 사유 문자열(F21): 원장 중복 · prereg null · track 닫힘 ·
      예산(카운터·원장 행 수 중 큰 값, F2) · evaluation_index 불일치(F2) · rung 키 uncertainty 불일치(F14) · 공유 구현 상수(F16)
  (e) 합성 rung: G0·MDE 6셀 전수(untestable 은 정보용, F1/F5) · MDE 표가 판정 표보다 먼저 · reliability/log_score(F4/F12)
  (f) 사전등록 제외 쌍은 family 밖이지만 통계는 남는다 · 분모 불일치면 아무것도 쓰지 않는다(F15) · 원장 행 해시
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
P0 = pytest.importorskip("v14_cond_diagnostics")
RUN = pytest.importorskip("v14_cond_run")
PB3 = pytest.importorskip("v13_vol_rung3_pb")

from ai_fc.timeseries_v13 import features as F  # noqa: E402
from ai_fc.timeseries_v13.contracts import canonical_hash  # noqa: E402

CONTRACT = ROOT / "data/contracts/multivariate_timeseries_v14_conditional.yaml"
THETA = 0.1694207105468098
KEY = "rung1_conditional_blocks"
CELLS = ["cvix25_h5", "cvix25_h21", "cvix25_h63", "crv_h5", "crv_h21", "crv_h63"]
BLOCKS = ["E1_fomc_in_window", "P1_vix_lev_net_oi"]
UNCERTAINTY = {"bootstrap": "stationary_block", "block_length": 13, "replicates": 2000, "seed": 20261021, "interval": [5, 95]}
G0 = "G0:conditional_pb_vs_climatology"


class _Obs:
    def __init__(self, series_id: str, day: str, value: float):
        self._row = {"series_id": series_id, "observation_time": day, "value": value, "available_at": day + "T23:00:00+00:00"}

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002 — pydantic 시그니처 흉내
        return dict(self._row)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _synthetic_panel(seed: int = 7) -> tuple[list[str], np.ndarray, np.ndarray]:
    """2005-01-03~2014-12-31 영업일. 평온(VIX≈14)↔스트레스(VIX≈28) 국면이 ~40세션마다 바뀐다 — 조건부 사건·국면이 양쪽 반창에 생기도록."""
    days = np.arange(np.datetime64("2005-01-03"), np.datetime64("2015-01-01"), dtype="datetime64[D]")
    days = days[np.is_busday(days)]
    rng = np.random.default_rng(seed)
    n = len(days)
    stressed = np.zeros(n, bool)
    state, i = False, 0
    while i < n:
        length = int(rng.integers(25, 60))
        stressed[i:i + length] = state
        state = not state
        i += length
    vix = np.where(stressed, 28.0 + rng.normal(0, 2.5, n), 14.0 + rng.normal(0, 2.0, n))
    sigma = np.where(stressed, 0.022, 0.007)
    ndx = 2000.0 * np.exp(np.cumsum(rng.normal(0, 1, n) * sigma))
    return [str(d) for d in days], vix, ndx


def _observations(dates, vix, ndx) -> list[_Obs]:
    out = []
    for d, v, q in zip(dates, vix, ndx):
        out.append(_Obs("VIX", d, float(v)))
        out.append(_Obs("NASDAQCOM", d, float(q)))
    return out


def _synthetic_ctx(seed: int = 7) -> dict:
    dates, vix, ndx = _synthetic_panel(seed)
    panel = F.build_panel(_observations(dates, vix, ndx), start="2005-01-01", end="2014-12-31")
    n = len(panel["dates"])
    rng = np.random.default_rng(seed + 1)
    marks = {"fomc_scheduled": np.zeros(n), "bls_empsit": np.zeros(n), "bls_cpi": np.zeros(n)}
    marks["fomc_scheduled"][::31] = 1.0
    marks["bls_empsit"][3::21] = 1.0
    marks["bls_cpi"][11::21] = 1.0
    p1 = rng.normal(0, 0.3, n); p1[rng.random(n) < 0.03] = np.nan
    p3 = rng.normal(0, 0.2, n)
    return P0.context_from_panel([str(d) for d in panel["dates"]], panel["vix"], panel["rv21"], theta=THETA, marks=marks, p1=p1, p3=p3)


def _spec(prereg: str | None = "abcdef12", *, excluded: list[dict] | None = None, planned_tests: int = 12,
          evaluation_index: int = 1, uncertainty: dict | None = None) -> dict:
    return {"registered": "2026-10-22", "prereg_commit": prereg, "experiment_label": "V14COND_rung1_test",
            "rung_name": "conditional_blocks_vs_conditional_pb", "results_path": "data/timeseries_v14/vol/ladder_rung1_test.json",
            "evaluation_index": evaluation_index,
            "uncertainty": dict(UNCERTAINTY) if uncertainty is None else uncertainty,
            "planned_tests": planned_tests,
            "blocks": [{"id": "E1_fomc_in_window", "class": "calendar", "definition": "test"},
                       {"id": "P1_vix_lev_net_oi", "class": "positioning", "definition": "test"}],
            "excluded_cells": list(excluded or []), "family": {"representative": "binomial"}}


def _reject_constant(token: str):
    raise AssertionError(f"JSON 에 {token} 토큰이 있다")


# ── (a) 조건부 부분집합 마스크 ───────────────────────────────────────────────
def test_conditional_subset_masks_follow_the_contract_thresholds() -> None:
    vix = np.array([12.0, 19.999, 20.0, 25.0, np.nan, 18.0])
    rv = np.array([np.nan, 0.10, THETA, THETA + 1e-9, 0.40, 0.05])
    vix_spec = {"target": "vix_conditional", "K": 25.0, "cond_lt": 20.0, "h": 5}
    rv_spec = {"target": "rv_conditional", "theta": THETA, "h": 5}
    assert P0.conditional_subset(vix_spec, vix, rv).tolist() == [True, True, False, False, False, True]
    assert P0.conditional_subset(rv_spec, vix, rv).tolist() == [False, True, True, False, False, True]
    # champion 피처: vix 셀 VIX_t · rv 셀 fill_rv_nan(θ) — 부분집합 안에서는 raw 그대로
    assert np.array_equal(P0.champion_feature(vix_spec, vix, rv), vix, equal_nan=True)
    rv_feat = P0.champion_feature(rv_spec, vix, rv)
    assert rv_feat[0] == THETA and rv_feat[1] == 0.10


def test_v14_cell_specs_come_from_the_contract() -> None:
    specs = P0.v14_cell_specs(_contract())
    assert [s["name"] for s in specs] == CELLS
    assert all(s["K"] == 25.0 and s["cond_lt"] == 20.0 for s in specs[:3])
    assert all(s["theta"] == THETA for s in specs[3:])


# ── (b) 부분집합 라벨 = 전체 패널 라벨의 제한 ───────────────────────────────
def test_compact_labels_equal_full_panel_labels_at_subset_origins() -> None:
    ctx = _synthetic_ctx()
    for spec in P0.v14_cell_specs(_contract()):
        cc = RUN.compact_cell(spec, ctx, P0.cell_blocks(spec, ctx))
        if spec["target"] == "vix_conditional":
            full = F.labels_vix(ctx["vix"], 25.0, spec["h"])
            assert (ctx["vix"][cc["idx"]] < 20.0).all()
        else:
            full = F.labels_rv(ctx["rv_raw"], THETA, spec["h"])
            assert np.isfinite(ctx["rv_raw"][cc["idx"]]).all() and (ctx["rv_raw"][cc["idx"]] <= THETA).all()
        assert np.array_equal(cc["y"], full[cc["idx"]])
        assert np.isfinite(cc["y"]).all()
        assert ctx["design"][cc["idx"]].all(), "설계창 밖 원점이 섞였다"
        assert (np.diff(cc["idx"]) > 0).all(), "시간순 압축"
        assert cc["me"].sum() > 0 and cc["ml"].sum() > 0
        assert all(d < "2011-01-01" for d, m in zip(cc["dates"], cc["me"]) if m)


# ── (c) R1·R2·R3 플래그 ─────────────────────────────────────────────────────
def test_r1_r2_r3_flags_on_hand_built_arrays() -> None:
    rng = np.random.default_rng(3)
    n = 400
    level = rng.normal(15, 3, n)
    sub = np.ones(n, bool)
    sub_e = np.arange(n) < 200
    sub_l = ~sub_e
    # R1: champion 피처와 거의 같은 열
    x = level + rng.normal(0, 0.1, n)
    e = P0.diagnose_block(x, level, sub, sub_e, sub_l)
    assert e["R1_auto_reject"] and not e["R2_coverage_fail"] and not e["R3_block_degenerate_cell"]
    # R2: early 반창 커버리지 0.5
    x = rng.normal(0, 1, n); x[:100] = np.nan
    e = P0.diagnose_block(x, level, sub, sub_e, sub_l)
    assert e["R2_coverage_fail"] and abs(e["coverage_early"] - 0.5) < 1e-9 and e["coverage_late"] == 1.0
    assert not e["R1_auto_reject"]
    # R3: late 반창 최빈값 점유율 0.95
    x = rng.normal(0, 1, n); x[200:390] = 0.0
    e = P0.diagnose_block(x, level, sub, sub_e, sub_l)
    assert e["R3_block_degenerate_cell"] and e["mode_share_late"] >= 0.90 and not e["R2_coverage_fail"]
    # 커버리지·상관은 부분집합 안에서만 센다 — 부분집합 밖 값은 무시
    x = rng.normal(0, 1, n); sub2 = sub.copy(); sub2[:50] = False; x[:50] = np.nan
    e = P0.diagnose_block(x, level, sub2, sub2 & sub_e, sub2 & sub_l)
    assert e["coverage_early"] == 1.0


def test_registration_applies_r1_r2_block_level_and_r3_cell_level_and_r4_vacancy() -> None:
    cells = ["cvix25_h5", "crv_h5"]
    def blk(r1=False, r2=False, r3=False):
        return {"R1_auto_reject": r1, "R2_coverage_fail": r2, "R3_block_degenerate_cell": r3,
                "abs_corr_vs_conditional_champion_feature": 0.9 if r1 else 0.1,
                "coverage_early": 0.5 if r2 else 1.0, "coverage_late": 1.0}
    lf = {
        "cvix25_h5": {"blocks": {"E1_fomc_in_window": blk(r3=True), "E2_macro_release_in_window": blk(), "E3_log_sessions_to_next_fomc": blk(),
                                 "P1_vix_lev_net_oi": blk(r2=True), "P3_nq_lev_net_oi": blk(),
                                 "D1_log_sessions_since_event": blk(r1=True), "D2_log_sessions_since_any_vix25": blk(r2=True)}},
        "crv_h5": {"blocks": {"E1_fomc_in_window": blk(), "E2_macro_release_in_window": blk(), "E3_log_sessions_to_next_fomc": blk(),
                              "P1_vix_lev_net_oi": blk(), "P3_nq_lev_net_oi": blk(),
                              "D1_log_sessions_since_event": blk(), "D2_log_sessions_since_any_vix25": blk()}},
    }
    reg = P0.register(P0.block_summary(lf, cells), lf, cells)
    assert reg["by_class"]["calendar"]["registered"] == "E1_fomc_in_window"          # R3 는 등록을 막지 않는다
    assert reg["by_cell"]["cvix25_h5"]["calendar"]["family_eligible"] is False      # 그 셀만 제외
    assert reg["by_cell"]["crv_h5"]["calendar"]["family_eligible"] is True
    assert reg["by_class"]["positioning"]["registered"] == "P3_nq_lev_net_oi"       # P1 은 한 셀의 R2 로 블록 미달 → 다음 후보
    assert reg["by_class"]["regime_memory"]["status"] == "vacant_R4"                # D1 R1 · D2 R2 → 공석
    assert reg["registered_blocks"] == ["E1_fomc_in_window", "P3_nq_lev_net_oi"]
    assert reg["excluded_cells_proposed"] == [{"cell": "cvix25_h5", "block": "E1_fomc_in_window",
                                               "reason": reg["excluded_cells_proposed"][0]["reason"]}]


def test_guard_verdict_follows_marginal_band() -> None:
    guard_cfg = _contract()["episode_guard"]
    def rep(ev, nev, er, ner):
        return {"counts_ok": min(ev, nev) >= 20, "min_episodes": min(er, ner)}
    assert P0.v14_guard_verdict(rep(50, 50, 6, 7), guard_cfg)["verdict"] == "ok"
    assert P0.v14_guard_verdict(rep(50, 50, 4, 7), guard_cfg) == {"episode_band": "marginal", "verdict": "episode_thin", "reason": "marginal_band_display_only"}
    assert P0.v14_guard_verdict(rep(50, 50, 2, 7), guard_cfg)["verdict"] == "untestable_by_construction"
    assert P0.v14_guard_verdict(rep(10, 50, 6, 7), guard_cfg)["reason"] == "min_events_per_half_per_class"


# ── (c′) F10: label_free 섹션은 라벨을 받지도 만들지도 않는다 — 구조에서 판정 ─────
def test_label_free_report_survives_poisoned_label_builders_and_flags_come_from_structure(monkeypatch) -> None:
    contract, ctx = _contract(), _synthetic_ctx()
    before = P0.build_report(contract, ctx)
    assert before["label_free_section_touches_labels"] is False
    assert before["guard_section_touches_labels"] is True
    assert P0._references_labels(P0.label_free_report) is False
    assert P0._references_labels(P0.guard_report) is True
    assert P0._references_labels(P0.build_report) is True            # build_report 는 guard_report 를 부른다

    def boom(*args, **kwargs):
        raise AssertionError("label_free 경로가 라벨을 만들었다")
    monkeypatch.setattr(P0.F, "labels_vix", boom)
    monkeypatch.setattr(P0.F, "labels_rv", boom)
    monkeypatch.setattr(P0, "full_labels", boom)
    label_free = P0.label_free_report(contract, ctx)
    assert label_free["registration"] == before["label_free"]["registration"]
    assert label_free["cells"] == before["label_free"]["cells"]
    assert label_free["summary"] == before["label_free"]["summary"]
    with pytest.raises(AssertionError):
        P0.guard_report(contract, ctx)


# ── (c″) F3: P0 도구는 산출물을 덮어쓰지 않는다 ───────────────────────────────
def _temp_root(tmp_path: Path, mutate, ledger_rows: list[dict] | None = None) -> Path:
    contract = _contract()
    mutate(contract)
    (tmp_path / "data/contracts").mkdir(parents=True)
    (tmp_path / "data/contracts/multivariate_timeseries_v14_conditional.yaml").write_text(
        yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (tmp_path / "data/timeseries_v14/ledgers").mkdir(parents=True)
    (tmp_path / "data/timeseries_v14/ledgers/v14_experiments.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in (ledger_rows or [])), encoding="utf-8")
    return tmp_path


@pytest.fixture
def no_archive(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("실제 아카이브를 읽으면 안 된다")
    monkeypatch.setattr(RUN, "read_market_observations", _boom)
    monkeypatch.setattr(P0, "read_market_observations", _boom)


@pytest.mark.usefixtures("no_archive")
def test_p0_tool_refuses_to_overwrite_an_existing_diagnostics_file(tmp_path: Path, capsys) -> None:
    root = _temp_root(tmp_path, lambda c: None)
    out = root / P0.OUT_RELATIVE
    out.parent.mkdir(parents=True)
    out.write_text('{"sentinel": true}\n', encoding="utf-8")
    assert P0.main(["--root", str(root)]) == 2                       # 아카이브를 읽기 전에 거부한다(no_archive 가 보증)
    text = capsys.readouterr().out
    assert "덮어쓰지 않는다" in text and "삭제" in text and "diagnostics_content_hash" in text
    assert out.read_text(encoding="utf-8") == '{"sentinel": true}\n'


def test_p0_tool_writes_when_absent_and_hash_verifies(tmp_path: Path, monkeypatch) -> None:
    root = _temp_root(tmp_path, lambda c: None)
    ctx = _synthetic_ctx()
    monkeypatch.setattr(P0, "read_market_observations", lambda r: [])
    monkeypatch.setattr(P0, "panel_context", lambda observations, *, theta: ctx)
    assert P0.main(["--root", str(root)]) == 0
    raw = (root / P0.OUT_RELATIVE).read_bytes()
    assert raw.count(b"\r\n") == 0
    payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    assert canonical_hash({k: v for k, v in payload.items() if k != "content_hash"}) == payload["content_hash"]
    assert payload["label_free_section_touches_labels"] is False and payload["guard_section_touches_labels"] is True
    assert payload["label_contact_check"]["label_free_function"] == "label_free_report"
    assert payload["evaluations_consumed"] == 0
    assert P0.main(["--root", str(root)]) == 2                       # 두 번째는 덮어쓰기 거부


# ── (d) 러너 거부 경로 — 양성 대조 + 사유 문자열 ────────────────────────────
def _with_spec(spec: dict, **protocol):
    def mutate(c):
        c[KEY] = spec
        c["development_protocol"].update(protocol)
    return mutate


def _run_main(root: Path, capsys) -> tuple[int, str]:
    code = RUN.main(["--rung", "1", "--root", str(root)])
    return code, capsys.readouterr().out


def test_refuse_reason_positive_control_accepts_a_valid_registration(tmp_path: Path) -> None:
    contract = _contract()
    contract[KEY] = _spec()
    empty = tmp_path / "v14_experiments.jsonl"
    empty.write_text("", encoding="utf-8")
    assert RUN.refuse_reason(contract, KEY, empty) is None
    assert RUN.refuse_reason(contract, KEY, tmp_path / "missing.jsonl") is None


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_label_already_in_ledger(tmp_path: Path, capsys) -> None:
    root = _temp_root(tmp_path, _with_spec(_spec()), ledger_rows=[{"experiment_label": "V14COND_rung1_test"}])
    code, out = _run_main(root, capsys)
    assert code == 2 and "already in ledger" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_without_prereg_commit(tmp_path: Path, capsys) -> None:
    code, out = _run_main(_temp_root(tmp_path, _with_spec(_spec(prereg=None))), capsys)
    assert code == 2 and "prereg_commit" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_track_is_closed(tmp_path: Path, capsys) -> None:
    code, out = _run_main(_temp_root(tmp_path, _with_spec(_spec(), track_open=False)), capsys)
    assert code == 2 and "track_open" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_budget_counter_is_exhausted(tmp_path: Path, capsys) -> None:
    root = _temp_root(tmp_path, _with_spec(_spec(evaluation_index=5), evaluations_spent=4))
    code, out = _run_main(root, capsys)
    assert code == 2 and "예산 소진" in out and "4/4" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_counts_ledger_rows_as_spent_budget_even_when_counter_says_zero(tmp_path: Path, capsys) -> None:
    rows = [{"experiment_label": f"V14COND_other_{i}"} for i in range(4)]
    root = _temp_root(tmp_path, _with_spec(_spec(), evaluations_spent=0), ledger_rows=rows)
    code, out = _run_main(root, capsys)
    assert code == 2 and "예산 소진" in out and "ledger" in out and "행 4" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_evaluation_index_disagrees_with_spent(tmp_path: Path, capsys) -> None:
    code, out = _run_main(_temp_root(tmp_path, _with_spec(_spec(evaluation_index=2), evaluations_spent=0)), capsys)
    assert code == 2 and "evaluation_index" in out and "spent+1=1" in out
    # 원장에 1행이 있으면(카운터 0) spent=1 → index 2 가 맞고 1 은 틀리다
    rows = [{"experiment_label": "V14COND_other_0"}]
    root = _temp_root(tmp_path / "b", _with_spec(_spec(evaluation_index=1), evaluations_spent=0), ledger_rows=rows)
    code, out = _run_main(root, capsys)
    assert code == 2 and "evaluation_index" in out and "ledger" in out


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_rung_uncertainty_differs_from_gate(tmp_path: Path, capsys) -> None:
    code, out = _run_main(_temp_root(tmp_path / "seed", _with_spec(_spec(uncertainty={**UNCERTAINTY, "seed": 20260907}))), capsys)
    assert code == 2 and "uncertainty.seed" in out
    code, out = _run_main(_temp_root(tmp_path / "interval", _with_spec(_spec(uncertainty={**UNCERTAINTY, "interval": [2.5, 97.5]}))), capsys)
    assert code == 2 and "uncertainty.interval" in out
    code, out = _run_main(_temp_root(tmp_path / "missing", _with_spec(_spec(uncertainty=None) | {"uncertainty": None})), capsys)
    assert code == 2 and "uncertainty 가 없다" in out


def test_refuse_reason_checks_shared_bootstrap_constants(monkeypatch, tmp_path: Path) -> None:
    contract = _contract()
    contract[KEY] = _spec()
    empty = tmp_path / "v14_experiments.jsonl"
    empty.write_text("", encoding="utf-8")
    assert RUN.refuse_reason(contract, KEY, empty) is None
    monkeypatch.setattr(RUN.C, "BLOCK_LENGTH", 12)
    reason = RUN.refuse_reason(contract, KEY, empty)
    assert reason is not None and "contracts.py" in reason and "BLOCK_LENGTH=12" in reason


@pytest.mark.usefixtures("no_archive")
def test_runner_refuses_when_rung_key_is_missing(tmp_path: Path, capsys) -> None:
    root = _temp_root(tmp_path, lambda c: None)
    code, out = _run_main(root, capsys)
    assert code == 2 and KEY in out
    assert not (root / "data/timeseries_v14/vol").exists()
    assert (root / "data/timeseries_v14/ledgers/v14_experiments.jsonl").read_text(encoding="utf-8") == ""


# ── (e)(f) 합성 rung ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def synthetic() -> dict:
    """유효한 사전등록: 가드 untestable 셀 × 등록 블록 전부를 excluded_cells 로, planned_tests = 자격 셀 × 블록."""
    contract, ctx = _contract(), _synthetic_ctx()
    guard = P0.guard_report(contract, ctx)
    untestable = list(guard["cells_untestable"])
    assert untestable and len(untestable) < len(CELLS), "합성 패널 전제: 일부 셀만 untestable"
    excluded = [{"cell": c, "block": b, "reason": "guard untestable_by_construction (synthetic)"} for c in untestable for b in BLOCKS]
    spec = _spec(excluded=excluded, planned_tests=(len(CELLS) - len(untestable)) * len(BLOCKS))
    payload = RUN.run_rung(contract, spec, ctx, rung=1, b=40, null_draws=4)
    return {"contract": contract, "ctx": ctx, "spec": spec, "payload": payload, "untestable": untestable}


def test_mde_table_lists_every_cell_block_direction_and_prints_before_the_verdict_table(synthetic) -> None:
    payload = synthetic["payload"]
    rows = RUN.mde_rows(payload)
    assert len(rows) == len(CELLS) * 2 * (1 + len(BLOCKS))            # 6셀 × 2방향 × (G0 + 2블록) = 36
    assert {(c, b) for c, b, _, _, _ in rows} == {(c, b) for c in CELLS for b in [G0] + BLOCKS}
    buf = io.StringIO()
    with redirect_stdout(buf):
        RUN.render(payload)
    text = buf.getvalue()
    i_mde, i_verdict = text.index("=== MDE"), text.index("=== 판정 ===")
    assert 0 <= i_mde < i_verdict
    for cell, block, direction, mde, informational in rows:
        assert mde is not None
        assert mde >= 0 if informational else mde > 0
        assert informational == (cell in synthetic["untestable"])
        assert text.index(f"{cell:11s} {block:34s} {direction:14s}") < i_verdict
    assert payload["bootstrap"]["seed"] == 20261021 and payload["bootstrap"]["block_length"] == 13
    assert payload["bootstrap"]["ci_implementation"].startswith("tools/v13_vol_run.block_boot_ci")
    assert "_boot_lower_fast" in payload["bootstrap"]["null_implementation"]
    assert payload["holdout_read"] is False and payload["sealed_read"] is False
    assert payload["promotion"].startswith("none")
    assert RUN.denominator_mismatch(synthetic["spec"], payload) is None


def test_g0_is_reported_for_all_six_cells_and_untestable_cells_are_informational(synthetic) -> None:
    payload, untestable = synthetic["payload"], set(synthetic["untestable"])
    assert set(payload["cells"]) == set(CELLS)
    assert set(payload["cells_untestable"]) == untestable
    for cell, entry in payload["cells"].items():
        g0 = entry["conditional_pb_vs_climatology"]
        assert g0 is not None and set(g0) >= {"early_to_late", "late_to_early", "adopted_ci_both", "neg_control_pass_rate", "pb_beats_climatology"}
        assert g0["informational_only"] is (cell in untestable)
        for d in ("early_to_late", "late_to_early"):
            assert g0[d]["mde"] is not None and g0[d]["ci90"] and "clim_base_rate" in g0[d]
        assert entry["champion_rule_outcome"]["rule"] in ("a", "b", "c")
        assert entry["guard"]["early"]["verdict"] in ("ok", "episode_thin", "untestable_by_construction")
        for bname, be in entry["blocks"].items():
            assert "paired" in be and be["paired"]["early_to_late"]["mde"] is not None
            if cell in untestable:
                assert be["verdict"] == "excluded_preregistered"
                assert be["informational_only"] is True
                assert be["runtime_guard_verdict"] == "untestable_by_construction"
                assert be["reason"] == "guard untestable_by_construction (synthetic)"
                assert "adopted" not in be and isinstance(be["would_pass_gate"], bool)
            else:
                assert be["verdict"] in ("adopted", "adopted_episode_thin", "measured_zero", "null_leak")
                assert isinstance(be["adopted"], bool) and "informational_only" not in be
        if cell in untestable:
            assert entry["verdict"] == "untestable_by_construction"
            assert entry["champion_rule_outcome"] == {"rule": "c", "champion": "hold",
                                                      "note": entry["champion_rule_outcome"]["note"]}
    assert payload["tests_run"] == payload["planned_tests"] == (len(CELLS) - len(untestable)) * len(BLOCKS)
    assert sum(v["n"] for v in payload["by_class"].values()) == payload["tests_run"]
    assert payload["tests_run"] >= payload["k_obs_adopted"] >= 0
    assert 0.0 <= payload["family_p_binomial"] <= 1.0
    assert all(a.split("|")[0] not in untestable for a in payload["adopted"])


def test_reliability_and_log_score_are_reported_per_direction_without_nan_tokens(synthetic) -> None:
    payload = synthetic["payload"]
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)      # NaN/Infinity 토큰이 있으면 여기서 터진다
    json.loads(text, parse_constant=_reject_constant)
    for entry in payload["cells"].values():
        g0 = entry["conditional_pb_vs_climatology"]
        for d in ("early_to_late", "late_to_early"):
            rel, ls = g0[d]["reliability"], g0[d]["log_score"]
            assert set(rel) == set(ls) == {"conditional_pb", "conditional_climatology"}
            for model in rel:
                assert {"reliability", "resolution", "uncertainty", "brier_check", "curve"} <= set(rel[model])
                assert isinstance(rel[model]["curve"], list) and rel[model]["curve"]
                assert ls[model] <= 0.0 and np.isfinite(ls[model])
            # 기후 상수는 해상도 0 — Murphy 분해의 자명 기준
            assert abs(rel["conditional_climatology"]["resolution"]) < 1e-12
            for be in entry["blocks"].values():
                prel, pls = be["paired"][d]["reliability"], be["paired"][d]["log_score"]
                assert set(prel) == set(pls) == {"conditional_pb", "candidate"}
                assert all(np.isfinite(v) and v <= 0.0 for v in pls.values())
    assert "판정 다리" in payload["scoring_note"]


def test_excluded_pair_on_a_testable_cell_leaves_family_but_keeps_statistics_and_fails_the_denominator(synthetic) -> None:
    contract, ctx, base = synthetic["contract"], synthetic["ctx"], synthetic["payload"]
    testable = [c for c in CELLS if c not in synthetic["untestable"]]
    cell = testable[0]
    spec = _spec(excluded=synthetic["spec"]["excluded_cells"] + [{"cell": cell, "block": BLOCKS[0], "reason": "R3 (synthetic)"}],
                 planned_tests=base["tests_run"] - 1)
    payload = RUN.run_rung(contract, spec, ctx, rung=1, b=40, null_draws=4)
    be = payload["cells"][cell]["blocks"][BLOCKS[0]]
    assert be["verdict"] == "excluded_preregistered" and be["reason"] == "R3 (synthetic)"
    assert be["runtime_guard_verdict"] in ("testable", "episode_thin") and be["informational_only"] is True
    assert "paired" in be and "adopted" not in be
    assert payload["tests_run"] == base["tests_run"] - 1
    assert payload["by_class"]["calendar"]["n"] == base["by_class"]["calendar"]["n"] - 1
    assert f"{cell}|{BLOCKS[0]}" not in payload["adopted"]
    assert payload["cells"][cell]["blocks"][BLOCKS[1]]["verdict"] == base["cells"][cell]["blocks"][BLOCKS[1]]["verdict"]
    # 판정 자격 셀의 단독 제외는 사전등록 셀 집합 != 런타임 untestable 집합 → 페일클로즈(쓰지 않는다)
    reason = RUN.denominator_mismatch(spec, payload)
    assert reason is not None and "excluded_cells" in reason


def test_ledger_row_content_hash_verifies_and_results_hash_matches(synthetic, tmp_path: Path) -> None:
    spec, payload = synthetic["spec"], synthetic["payload"]
    out, row = RUN.write_outputs(tmp_path, spec, payload)
    written = json.loads(out.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    assert canonical_hash({k: v for k, v in written.items() if k != "content_hash"}) == written["content_hash"]
    assert out.read_bytes().count(b"\r\n") == 0
    lines = (tmp_path / RUN.LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    stored = json.loads(lines[0])
    assert stored == row
    assert PB3.content_hash({k: v for k, v in stored.items() if k != "content_hash"}) == stored["content_hash"]
    assert stored["model"] == "event_probability.volatility_v14_conditional"
    assert stored["backtest_windows_opened"] == 0 and stored["holdout_slot_consumed"] == 0
    assert stored["window"] == ["2007-01-01", "2014-12-31"]
    assert stored["prereg_commit"] == "abcdef12" and stored["evaluation_index"] == 1
    assert stored["planned_tests"] == stored["tests_run"] == payload["tests_run"]
    assert stored["results_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    # 같은 라벨로 두 번째 실행은 거부된다 (예산 1회용)
    contract = _contract()
    contract[KEY] = spec
    reason = RUN.refuse_reason(contract, KEY, tmp_path / RUN.LEDGER_RELATIVE)
    assert reason is not None and "already in ledger" in reason


@pytest.fixture
def fast_main(monkeypatch, synthetic):
    """main() 경로를 합성 ctx·경량 bootstrap 으로 — 아카이브 미접촉."""
    original = RUN.run_rung
    monkeypatch.setattr(RUN, "read_market_observations", lambda root: [])
    monkeypatch.setattr(P0, "panel_context", lambda observations, *, theta: synthetic["ctx"])
    monkeypatch.setattr(RUN, "run_rung", lambda c, s, ctx, *, rung: original(c, s, ctx, rung=rung, b=40, null_draws=4))


@pytest.mark.usefixtures("fast_main")
def test_main_refuses_to_write_when_runtime_denominator_differs_from_preregistration(tmp_path: Path, capsys, synthetic) -> None:
    valid = synthetic["spec"]
    # planned_tests 불일치
    root = _temp_root(tmp_path / "planned", _with_spec({**valid, "planned_tests": valid["planned_tests"] + 1}))
    code, out = _run_main(root, capsys)
    assert code == 2 and "planned_tests" in out and "=== MDE" not in out
    assert not (root / valid["results_path"]).exists()
    assert (root / RUN.LEDGER_RELATIVE).read_text(encoding="utf-8") == ""
    # 런타임 untestable 셀을 사전등록이 제외하지 않음 — 분모(tests_run)는 맞지만 셀 집합이 어긋난다
    root = _temp_root(tmp_path / "excluded", _with_spec({**valid, "excluded_cells": []}))
    code, out = _run_main(root, capsys)
    assert code == 2 and "excluded_cells" in out and "planned_tests" not in out
    assert not (root / valid["results_path"]).exists()
    assert (root / RUN.LEDGER_RELATIVE).read_text(encoding="utf-8") == ""


@pytest.mark.usefixtures("fast_main")
def test_main_writes_results_and_one_ledger_row_when_preregistration_matches(tmp_path: Path, capsys, synthetic) -> None:
    valid = synthetic["spec"]
    root = _temp_root(tmp_path, _with_spec(valid))
    code, out = _run_main(root, capsys)
    assert code == 0
    assert 0 <= out.index("=== MDE") < out.index("=== 판정 ===") < out.index("wrote ")
    written = json.loads((root / valid["results_path"]).read_text(encoding="utf-8"), parse_constant=_reject_constant)
    assert written["tests_run"] == written["planned_tests"] == valid["planned_tests"]
    assert set(written["cells_untestable"]) == set(synthetic["untestable"])
    rows = (root / RUN.LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["experiment_label"] == valid["experiment_label"]
    # 같은 루트에서 재실행은 원장 중복으로 거부된다
    code, out = _run_main(root, capsys)
    assert code == 2 and "already in ledger" in out
