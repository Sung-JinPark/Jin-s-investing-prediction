"""V13-D14 라이브 판정 보고 확장(print_only) — status 산술 무변경·두 반창 대칭·기계확정 닫힌형 동치.

쓰기 테스트는 tmp_path 사본만. 실데이터 오라클은 as_of=2026-11-09 고정이고 쓰기 0(sha256 전후 비교).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import resolve as R
from ai_fc.timeseries_v13 import scoring as S
from ai_fc.timeseries_v13 import verdict_ledger as VL
from ai_fc.timeseries_v13 import verdict_report as VR
from ai_fc.timeseries_v13.live_verdict import NULL_DRAWS, _evaluate_cell, live_verdict, render_table

ROOT = Path(__file__).resolve().parents[2]
PINNED = "a" * 64
NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def _origin(i: int) -> str:
    return (date(2026, 1, 5) + timedelta(days=i)).isoformat()


def _row(cell: str, origin: str, *, p: float, label: float, base: float, sha: str = PINNED) -> dict:
    body = {"schema_version": 1, "resolution_id": f"v13vol-{origin}-{sha[:8]}-{cell}",
            "run_id": f"v13vol-{origin}-{sha[:8]}", "cell": cell, "origin": origin,
            "horizon_sessions": 5, "resolved_session": origin, "probability": p, "label": label,
            "brier_model": round((p - label) ** 2, 8), "brier_climatology": round((base - label) ** 2, 8),
            "climatology_base_rate": base, "coefficients_sha256": sha,
            "finalist_id": "V13VOL_champion_aec80c65038b", "holdout_status_at_forecast": "partial",
            "knowledge_cutoff": "2026-10-01T00:00:00+00:00"}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _mixed(cell: str, n: int, *, base: float = 0.42) -> list[dict]:
    return [_row(cell, _origin(d), p=0.8 if d % 4 == 0 else 0.1, label=1.0 if d % 4 == 0 else 0.0, base=base)
            for d in range(n)]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _tmp_repo(tmp_path: Path, *, drop_key: str | None = None) -> Path:
    src = ROOT / C.CONTRACT_RELATIVE
    dst = tmp_path / C.CONTRACT_RELATIVE
    dst.parent.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load(src.read_text(encoding="utf-8"))
    contract["frozen_coefficients"]["sha256"] = PINNED
    if drop_key:
        contract.pop(drop_key, None)
    dst.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (tmp_path / C.APPROVALS_LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / C.APPROVALS_LEDGER_RELATIVE, tmp_path / C.APPROVALS_LEDGER_RELATIVE)
    return tmp_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"


# 1 ───────────────────────────────────────────────────────────────────────────
def test_extension_does_not_change_status_arithmetic(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    rows = _mixed("vix25_h21", 60)
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    result = live_verdict(root, draws=NULL_DRAWS, panel={"dates": []})
    cell = result["cells"]["vix25_h21"]
    direct = _evaluate_cell(sorted(rows, key=lambda r: r["origin"]), minimum=60, min_events=20, min_episodes=5,
                            draws=NULL_DRAWS)
    assert cell["status"] == direct["status"]
    assert cell["paired_loss_vs_climatology"] == direct["paired_loss_vs_climatology"]
    assert cell["negative_control_pass_rate"] == direct["negative_control_pass_rate"]
    assert cell["report"]["scope"].startswith("print_only")
    assert result["report_extension"]["judgement_leg"] is False and result["report_extension"]["print_only"] is True
    assert result["writes"] == 0


# 2 ───────────────────────────────────────────────────────────────────────────
def test_log_score_matches_manual_and_refuses_boundary_p() -> None:
    p = np.array([0.2, 0.7, 0.9]); y = np.array([0.0, 1.0, 1.0])
    manual = -np.mean([np.log(0.8), np.log(0.7), np.log(0.9)])
    assert VR.log_score(p, y) == pytest.approx(manual, abs=1e-15)
    assert VR.log_score(np.array([0.0, 0.5]), np.array([0.0, 1.0])) is None
    assert VR.log_score(np.array([1.0, 0.5]), np.array([1.0, 1.0])) is None
    assert VR.log_score(np.array([np.nan]), np.array([1.0])) is None
    assert VR.log_score(np.array([]), np.array([])) is None


# 3 ───────────────────────────────────────────────────────────────────────────
def test_reliability_uses_contract_ten_bins() -> None:
    rows = _mixed("rv_h5", 40)
    rep = VR.report_extension("rv_h5", rows, panel=None, panel_status="archive_unavailable",
                              half_constants={"status": "missing", "values": {}})
    p = np.array([r["probability"] for r in rows]); y = np.array([r["label"] for r in rows])
    expected = S.murphy_reliability(p, y)
    for key in ("reliability", "resolution", "uncertainty", "brier_check", "curve"):
        assert rep["reliability"][key] == expected[key]
    assert rep["reliability"]["curve_n_total"] == 40
    # 구간 안 확률이 하나뿐이면(이 합성 모양) Murphy 분해는 Brier 와 정확히 같다
    assert rep["reliability"]["brier_check"] == pytest.approx(float(np.mean((p - y) ** 2)), abs=1e-12)


# 4 ───────────────────────────────────────────────────────────────────────────
def test_design_half_constants_require_pin_and_are_symmetric(tmp_path: Path) -> None:
    contract = C.load_contract_v13(ROOT)
    half = VR.design_half_constants(ROOT, contract)
    assert half["status"] == "ok"
    assert half["values"]["vix25_h21"]["early_fit"] == 0.6378968253968254
    assert half["values"]["vix25_h21"]["late_fit"] == 0.19593908629441625
    for name, pair in half["values"].items():
        assert set(pair) == {"early_fit", "late_fit"}, name
    assert half["windows"] == {"early_fit": ["2007-01-01", "2010-12-31"], "late_fit": ["2011-01-01", "2014-12-31"]}
    y = np.array([0.0, 1.0, 0.0])
    block = VR._half_block("vix25_h21", half, y)
    assert block["status"] == "ok" and "early_fit" in block and "late_fit" in block
    assert "selected_for_report" not in json.dumps(half) and "selected_for_report" not in json.dumps(block)

    # 1바이트 바뀐 ladder 사본 → pin_mismatch, 숫자 없음
    (tmp_path / C.LADDER_PB_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    raw = (ROOT / C.LADDER_PB_RELATIVE).read_bytes()
    (tmp_path / C.LADDER_PB_RELATIVE).write_bytes(raw[:-1] + (b" " if raw[-1:] != b" " else b"\n"))
    bad = VR.design_half_constants(tmp_path, contract)
    assert bad == {"status": "pin_mismatch", "values": {}}
    assert VR._half_block("vix25_h21", bad, y) == {"status": "pin_mismatch"}

    # 한 셀의 한 방향만 지운 합성 ladder(핀도 합성) → 그 셀 통째로 생략
    payload = json.loads(raw.decode("utf-8"))
    del payload["cells"]["rv_h5"]["pb_vs_clim"]["late_to_early"]
    synthetic = json.dumps(payload).encode("utf-8")
    (tmp_path / C.LADDER_PB_RELATIVE).write_bytes(synthetic)
    fake = {"gates": {"design_evidence": {"persistence_pb": {"sha256": hashlib.sha256(synthetic).hexdigest()}}}}
    partial = VR.design_half_constants(tmp_path, fake)
    assert partial["status"] == "ok" and "rv_h5" not in partial["values"] and "rv_h21" in partial["values"]
    assert VR._half_block("rv_h5", partial, y) == {"status": "cell_absent"}
    assert VR.design_half_constants(tmp_path / "nope", contract) == {"status": "missing", "values": {}}


# 5 ───────────────────────────────────────────────────────────────────────────
def test_rv_floor_matches_research_closed_form() -> None:
    from ai_fc.mts_research.audits.rv_mechanics import mechanical_positive   # 테스트만 연구 계층 import

    rng = np.random.default_rng(20261111)
    compared = 0
    for _ in range(50):
        returns = np.concatenate([[np.nan], rng.normal(0, rng.uniform(0.004, 0.03), 120)])
        for t in (25, 40, 77, 95):
            for h in (5, 21):
                ours = VR.rv_mechanical_floor(returns, t, h)
                theirs = mechanical_positive(returns, t, h, C.THETA_RV)["max_floor"]
                assert abs(ours - theirs) <= 1e-12
                compared += 1
    assert compared == 400
    # 알려진 부분이 자료 밖이면 nan(연구 계층은 거부) — 대체값 없음
    assert np.isnan(VR.rv_mechanical_floor(np.full(30, 0.01), 3, 5))


# 6 ───────────────────────────────────────────────────────────────────────────
def _panel_with_spike(n: int = 80) -> tuple[dict, list[str]]:
    dates = [_origin(i) for i in range(n)]
    ndx = np.cumprod(np.r_[100.0, np.exp(np.where(np.arange(1, n) == 40, 0.12, 0.001))])
    return {"dates": np.array(dates, dtype=object), "ndx": ndx}, dates


def test_mechanical_invariant_violation_is_reported_without_numbers() -> None:
    panel, dates = _panel_with_spike()
    floor = VR.rv_mechanical_floor(VR.panel_returns(panel), 41, 5)
    assert floor > C.THETA_RV
    rows = [_row("rv_h5", dates[41], p=0.3, label=0.0, base=0.55),
            _row("rv_h5", dates[25], p=0.3, label=1.0, base=0.55)]
    rep = VR.report_extension("rv_h5", rows, panel=panel, panel_status="ok",
                              half_constants={"status": "missing", "values": {}})
    mech = rep["mechanical"]
    assert mech["status"] == "invariant_violation" and mech["origins"] == [dates[41]]
    assert "mechanical_positives" not in mech and "share_of_events" not in mech
    # 라벨이 1이면 정상 — 기계 확정 1/1
    rows[0] = _row("rv_h5", dates[41], p=0.3, label=1.0, base=0.55)
    ok = VR.report_extension("rv_h5", rows, panel=panel, panel_status="ok",
                             half_constants={"status": "missing", "values": {}})["mechanical"]
    assert ok["status"] == "ok" and ok["mechanical_positives"] == 1 and ok["events"] == 2
    assert ok["nonmechanical"]["n"] == 1 and ok["panel_vintage"] == "latest_archive_not_pit"


# 7 ───────────────────────────────────────────────────────────────────────────
def test_archive_unavailable_degrades_only_mechanical_field(tmp_path: Path) -> None:
    rows = [_row("rv_h5", _origin(30 + i), p=0.3, label=float(i % 2), base=0.55) for i in range(6)]
    half = {"status": "missing", "values": {}}
    cases = [
        VR.report_extension("rv_h5", rows, panel=None, panel_status="archive_unavailable", half_constants=half),
        VR.report_extension("rv_h5", rows, panel={"dates": np.array([], dtype=object), "ndx": np.array([])},
                            panel_status="ok", half_constants=half),
        VR.report_extension("rv_h5", rows, panel={"dates": np.array(["1999-01-01"], dtype=object),
                                                  "ndx": np.array([1.0])}, panel_status="ok", half_constants=half),
    ]
    for rep in cases:
        assert rep["mechanical"]["status"] == "archive_unavailable"
        assert "mechanical_positives" not in rep["mechanical"]
        assert rep["log_score"]["model"] is not None and rep["reliability"]["curve_n_total"] == 6
    # 원점 일부만 패널에 있으면 partial + unlocated
    panel, dates = _panel_with_spike()
    some = rows[:3] + [_row("rv_h5", "2030-01-01", p=0.3, label=0.0, base=0.55)]
    rep = VR.report_extension("rv_h5", some, panel=panel, panel_status="ok", half_constants=half)
    assert rep["mechanical"]["status"] == "partial" and rep["mechanical"]["unlocated"] == 1
    # (a) tmp 루트(아카이브 없음)에서 live_verdict 경로 — status 정상, 기계 필드만 비움
    root = _tmp_repo(tmp_path)
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, [_row("rv_h5", _origin(i), p=0.3, label=0.0, base=0.55)
                                                      for i in range(5)])
    result = live_verdict(root, draws=6)
    assert result["cells"]["rv_h5"]["status"] == "insufficient_sample"
    assert result["cells"]["rv_h5"]["report"]["mechanical"]["status"] == "archive_unavailable"


# 8 ───────────────────────────────────────────────────────────────────────────
def test_vix_cells_report_mechanical_not_applicable() -> None:
    rep = VR.report_extension("vix25_h21", _mixed("vix25_h21", 8), panel=None, panel_status="ok",
                              half_constants={"status": "missing", "values": {}})
    assert rep["mechanical"] == {"status": "not_applicable_vix"}
    assert VR.report_extension("vix25_h21", [], panel=None, panel_status="ok",
                               half_constants={})["n"] == 0


# 9 ───────────────────────────────────────────────────────────────────────────
def test_real_ledger_oracle_as_of_20261109() -> None:
    watched = [ROOT / C.APPROVALS_LEDGER_RELATIVE, ROOT / R.RESOLUTION_LEDGER_RELATIVE,
               ROOT / C.CONTRACT_RELATIVE, ROOT / C.COEFFICIENTS_RELATIVE, ROOT / VL.APPLICATIONS_LEDGER_RELATIVE]
    before = [_sha(p) for p in watched]
    result = live_verdict(ROOT, as_of="2026-11-09", now=NOW)
    assert [_sha(p) for p in watched] == before and result["writes"] == 0
    v = result["cells"]["vix25_h21"]
    rep = v["report"]
    assert v["matured"] == 23 and v["events"] == 3
    assert v["brier_model"] == pytest.approx(0.1224, abs=1e-4)
    half = rep["constant_baselines"]["design_half_constants"]
    assert half["early_fit"]["brier"] == pytest.approx(0.3709, abs=1e-4)
    assert half["late_fit"]["brier"] == pytest.approx(0.1177, abs=1e-4)
    logs = (rep["log_score"]["model"], rep["log_score"]["climatology"], half["early_fit"]["log_score"],
            half["late_fit"]["log_score"])
    for got, want in zip(logs, (0.4343, 0.5862, 0.9420, 0.4022)):
        assert got == pytest.approx(want, abs=1e-4)
    rv5 = result["cells"]["rv_h5"]["report"]["mechanical"]
    assert (rv5["mechanical_positives"], rv5["events"]) == (7, 12)
    assert rv5["nonmechanical"]["n"] == 31 and rv5["panel_vintage"] == "latest_archive_not_pit"
    assert result["cells"]["rv_h21"]["report"]["mechanical"]["mechanical_positives"] == 0
    text = json.dumps(result, ensure_ascii=False, default=float)
    assert "selected_for_report" not in text and "design_late_constant" not in text
    assert all(c["status"] == "insufficient_sample" for c in result["cells"].values())
    table = render_table(result)
    assert "0.4343/0.5862/0.9420/0.4022" in table and "7/12" in table


# 10 ──────────────────────────────────────────────────────────────────────────
def test_checkpoint_field_uses_truncated_sample_and_fixed_draws(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path)
    rows = _mixed("rv_h21", 63)
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    result = live_verdict(root, draws=6, panel={"dates": []})
    cp = result["cells"]["rv_h21"]["checkpoint"]
    expected = _evaluate_cell(VL.checkpoint_sample(rows, 60), minimum=60, min_events=20, min_episodes=5,
                              draws=120)
    assert cp["k"] == 60 and cp["draws"] == 120 and cp["sample_rule"] == "ledger_first_recorded_k"
    assert cp["status"] == expected["status"]
    assert cp["ci90"] == expected["paired_loss_vs_climatology"]["ci90"]
    assert cp["negative_control_pass_rate"] == expected["negative_control_pass_rate"]
    # 정확히 60원점일 때도 같은 경로(재사용 분기 없음) — draws=6 이어도 체크포인트는 120
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows[:60])
    again = live_verdict(root, draws=6, panel={"dates": []})["cells"]["rv_h21"]
    assert again["checkpoint"]["negative_control_pass_rate"] == expected["negative_control_pass_rate"]
    assert again["checkpoint"]["draws"] == 120


# 11 ──────────────────────────────────────────────────────────────────────────
def test_contract_registers_extension_without_touching_report_bytes() -> None:
    contract = C.load_contract_v13(ROOT)
    report = contract["live_forward_verdict_report"]
    assert report["registered"] == "2026-10-21" and report["output"] == "print_only"
    assert report["applies_demotion"] is False and report["ledger_write"] is False
    assert report["re_verdict_cadence"] == ("셀이 60 에 닿은 뒤에는 성숙 원점이 +20 늘 때마다 verb 를 다시 돌린다(인쇄 전용). "
                                            "판정 적용(강등·종결)은 매번 사용자 승인 사항이며 자동화 밖이다.")
    ext = contract["live_forward_verdict_report_extension"]
    assert ext["judgement_leg"] is False and ext["output"] == "print_only" and ext["ledger_write"] is False
    assert ext["approval_receipt"] == "v13-approval:V13-D14:2026-11-11:r1"
    baselines = ext["fields"]["constant_baselines"]
    assert "[16,21)" in baselines["excluded"] and "design_half_constants" in baselines
    assert "design_late_constant" not in json.dumps(ext, ensure_ascii=False)
    assert "V13-D14" in contract["decisions_resolved"]


# 12 ──────────────────────────────────────────────────────────────────────────
def _section(text: str, head: str) -> str:
    start = text.find(head)
    if start < 0:
        return ""
    nxt = re.search(r"\n## ", text[start + len(head):])
    return text[start: start + len(head) + (nxt.start() if nxt else len(text))]


def test_no_comparison_sentence_in_docs() -> None:
    """이 묶음이 추가한 V13 문서 절에 상수 대비 우열 문장이 없다(리뷰 B4). 절이 아직 없으면 계약·런북만 본다."""
    texts = [(ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8").split("live_forward_verdict_report_extension:")[1],
             _section((ROOT / "docs/P1_OPERATIONS.md").read_text(encoding="utf-8"), "### V13 라이브 판정 체크포인트")]
    decisions = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")
    texts.append(_section(decisions, "## 2026-11-11 — U6·U7"))
    limits = (ROOT / "docs/KNOWN_LIMITS.md").read_text(encoding="utf-8")
    for marker in ("V13 점프 미표현", "V13 판정 적용은 사람 실행", "V13 사전 상수 기준선"):
        start = limits.find(marker)
        if start >= 0:
            texts.append(limits[start: start + 900])
    for text in texts:
        for word in ("뒤진다", "앞선다", "압승"):
            assert word not in text


# 13 ──────────────────────────────────────────────────────────────────────────
def test_live_verdict_cli_missing_contract_key_is_clean_error(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from ai_fc import config
    from ai_fc.cli import app

    root = _tmp_repo(tmp_path, drop_key="live_verdict_application")
    monkeypatch.setattr(config, "ROOT", root)
    response = CliRunner().invoke(app, ["timeseries-v13-vol-apply-verdict", "--approval-receipt",
                                        "v13-approval:V13-D15:2026-11-11:r1", "--dry-run"])
    assert response.exit_code == 1
    assert response.exception is None or isinstance(response.exception, SystemExit)
    assert "Traceback" not in response.output
    assert "live_verdict_application not registered" in response.output


# 13a ─────────────────────────────────────────────────────────────────────────
def test_as_of_rejects_non_iso_dates(tmp_path: Path, monkeypatch) -> None:
    """--as-of 절단은 문자열 비교다 — YYYY-MM-DD 가 아닌 표기는 조용히 틀린 표본 대신 거부(리뷰 비차단 11)."""
    from typer.testing import CliRunner

    from ai_fc import config
    from ai_fc.cli import app

    for bad in ("2026-11-9", "20261109", "2026/11/09", "2026-13-01", "x"):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            live_verdict(tmp_path, as_of=bad)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    response = CliRunner().invoke(app, ["timeseries-v13-vol-live-verdict", "--as-of", "2026-11-9"])
    assert response.exit_code == 1 and "Traceback" not in response.output
    assert "YYYY-MM-DD" in response.output
