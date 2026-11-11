"""V15-VOL 섀도 발행·검증 (명세 U5 §8.3) — 전부 tmp_path 사본. 실저장소 쓰기 0."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_fc.timeseries_v15_vol import contracts as C
from ai_fc.timeseries_v15_vol import shadow as SH
from ai_fc.timeseries_v15_vol import verdict as V
from v15_vol_fixtures import (ARMING, V13_LIVE, V15_SHADOW, arm, edit_contract, make_root, protected_hashes,
                              read_jsonl, write_arming, write_jsonl)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(C.ARMING_ENV, raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    before = protected_hashes()
    yield
    assert protected_hashes() == before, "실저장소 V13/V15 파일이 바뀌었다"


def _rehash(row: dict) -> dict:
    body = {k: v for k, v in row.items() if k != "content_hash"}
    row["content_hash"] = C.canonical_hash(body)
    return row


def _add_v13_origin(root: Path, as_of: str) -> dict:
    """tmp V13 원장에 핀 sha 새 행 1개(마지막 행 복제) — V13 이 계속 발행하는 상황."""
    rows = read_jsonl(root / V13_LIVE)
    new = json.loads(json.dumps(rows[-1]))
    sha = new["coefficients_sha256"]
    new.update({"as_of": as_of, "run_id": f"v13vol-{as_of}-{sha[:8]}"})
    new.pop("pit_grade", None)
    write_jsonl(root / V13_LIVE, rows + [_rehash(new)])
    return new


def _pinned_v13_rows(root: Path) -> list[dict]:
    sha = C.load_contract_v15_vol(root)["parent_v13"]["coefficients_sha256"]
    return [r for r in read_jsonl(root / V13_LIVE) if r["coefficients_sha256"] == sha]


@pytest.fixture()
def live_root(tmp_path: Path) -> Path:
    root = make_root(tmp_path)
    arm(root)
    write_arming(root, effective_from="2026-10-01")
    result = SH.publish_shadow_v15_vol(root, now=NOW)
    assert result["status"] == "live", result
    return root


def test_unarmed_contract_holds_without_writes(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    result = SH.publish_shadow_v15_vol(root, now=NOW)
    assert result == {"status": "hold", "reasons": ["not_armed"], "appended": 0}
    assert not (root / V15_SHADOW).exists() and not (root / ARMING).exists()
    assert SH.verify_shadow_v15_vol(root)["ok"]


def test_armed_publish_respects_effective_from_and_is_idempotent(live_root: Path) -> None:
    rows = read_jsonl(live_root / V15_SHADOW)
    pinned = _pinned_v13_rows(live_root)
    after = [r for r in pinned if r["as_of"] >= "2026-10-01"]
    assert rows and len(rows) == len(after)
    assert all(r["as_of"] >= "2026-10-01" for r in rows)
    again = SH.publish_shadow_v15_vol(live_root, now=NOW)
    assert again["appended"] == 0
    assert SH.verify_shadow_v15_vol(live_root)["ok"]
    row = rows[0]
    assert row["reference_opinion_only"] is True and row["trading_signal"] is False
    assert row["derivation"] == "pure_function_of_v13_row"
    assert set(row["cells"]["vix25_h5"]) == {"calm", "p_pb", "p_r1", "p_r2", "p_r3", "clim", "cond"}
    assert "p_r2" not in row["cells"]["rv_h5"] and "p_r2" not in row["cells"]["vix25_h21"]


def test_arming_row_written_only_in_main_ci_context(tmp_path: Path, monkeypatch) -> None:
    root = make_root(tmp_path)
    arm(root)
    held = SH.publish_shadow_v15_vol(root, now=NOW)
    assert held == {"status": "hold", "reasons": ["arming_pending_ci"], "appended": 0}
    assert not (root / ARMING).exists() and not (root / V15_SHADOW).exists()
    assert SH.verify_shadow_v15_vol(root)["ok"]          # 무장행 부재는 실패 아님(로컬·PR)

    monkeypatch.setenv(C.ARMING_ENV, C.ARMING_ENV_VALUE)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_SHA", "")
    incomplete = SH.publish_shadow_v15_vol(root, now=NOW)
    assert incomplete["reasons"] == ["arming_context_incomplete"] and not (root / ARMING).exists()

    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    first = SH.publish_shadow_v15_vol(root, now=datetime(2026, 11, 13, 11, 25, tzinfo=timezone.utc))  # 금
    assert first["armed_now"] is True and first["effective_from"] == "2026-11-16"                   # 월
    rows = read_jsonl(root / ARMING)
    assert len(rows) == 1 and rows[0]["github_sha"] == "a" * 40 and C.arming_row_hash_ok(rows[0])
    second = SH.publish_shadow_v15_vol(root, now=datetime(2026, 11, 20, 11, 25, tzinfo=timezone.utc))
    assert second["armed_now"] is False and len(read_jsonl(root / ARMING)) == 1
    assert SH.verify_shadow_v15_vol(root)["ok"]


def test_arming_skips_thanksgiving(tmp_path: Path, monkeypatch) -> None:
    root = make_root(tmp_path)
    arm(root)
    monkeypatch.setenv(C.ARMING_ENV, C.ARMING_ENV_VALUE)
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    result = SH.publish_shadow_v15_vol(root, now=datetime(2026, 11, 25, 11, 25, tzinfo=timezone.utc))  # 수
    assert result["effective_from"] == "2026-11-27"                                                    # 11-26 휴장


def test_two_arming_rows_raise(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    row = write_arming(root, effective_from="2026-10-01")
    (root / ARMING).write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(C.TimeSeriesV15VolError):
        C.read_arming(root)


def test_silent_hold_is_a_verify_failure(live_root: Path, monkeypatch) -> None:
    constants = live_root / C.CONSTANTS_RELATIVE
    constants.write_bytes(constants.read_bytes() + b" ")
    held = SH.publish_shadow_v15_vol(live_root, now=NOW)
    assert held["status"] == "hold" and held["reasons"] == ["constants_pin_mismatch"]
    report = SH.verify_shadow_v15_vol(live_root)
    assert not report["ok"] and any(e.startswith("armed_but_holding") for e in report["errors"])
    edit_contract(live_root, lambda c: c["parent_v13"].__setitem__("termination_acknowledged", "V13-T7-test"))
    report = SH.verify_shadow_v15_vol(live_root)
    assert report["ok"], report["errors"]
    assert any(n.startswith("v13_terminated_acknowledged") for n in report["notes"])


def test_main_ci_without_arming_row_fails_verify(tmp_path: Path, monkeypatch) -> None:
    root = make_root(tmp_path)
    arm(root)
    monkeypatch.setenv(C.ARMING_ENV, C.ARMING_ENV_VALUE)
    report = SH.verify_shadow_v15_vol(root)
    assert not report["ok"] and "arming_not_written" in report["errors"]


def test_code_pin_mismatch_holds_and_refuses_verdict(live_root: Path) -> None:
    target = live_root / "src/ai_fc/timeseries_v15_vol/verdict.py"
    target.write_bytes(target.read_bytes() + b" ")
    held = SH.publish_shadow_v15_vol(live_root, now=NOW)
    assert held["reasons"] == ["code_pin_mismatch:verdict.py"]
    report = SH.verify_shadow_v15_vol(live_root)
    assert not report["ok"] and any("code_pin_mismatch" in e for e in report["errors"])
    with pytest.raises(C.TimeSeriesV15VolError):
        V.shadow_verdict(live_root, rv_mechanics=False)


def test_recompute_detects_tampered_column(live_root: Path) -> None:
    rows = read_jsonl(live_root / V15_SHADOW)
    row = dict(rows[0])
    row["cells"] = json.loads(json.dumps(row["cells"]))
    row["cells"]["vix25_h5"]["p_r1"] = row["cells"]["vix25_h5"]["p_r1"] + 1e-6
    body = {k: v for k, v in row.items() if k != "content_hash"}
    row["content_hash"] = C.canonical_hash(body)
    write_jsonl(live_root / V15_SHADOW, [row] + rows[1:])
    report = SH.verify_shadow_v15_vol(live_root)
    assert not report["ok"] and any(e.startswith("recompute") for e in report["errors"])


def test_v13_refreeze_holds(live_root: Path) -> None:
    edit_contract(live_root, lambda c: c["parent_v13"].__setitem__("coefficients_sha256", "0" * 64))
    result = SH.publish_shadow_v15_vol(live_root, now=NOW)
    assert result["status"] == "hold" and result["reasons"] == ["v13_refrozen"]


def test_missing_cell_is_recorded(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    rows = read_jsonl(root / V13_LIVE)
    last = rows[-1]
    del last["cells"]["vix30_h63"]
    write_jsonl(root / V13_LIVE, rows)
    arm(root)
    write_arming(root, effective_from="2026-10-01")
    SH.publish_shadow_v15_vol(root, now=NOW)
    shadow = {r["v13_run_id"]: r for r in read_jsonl(root / V15_SHADOW)}
    row = shadow[last["run_id"]]
    assert row["cells_missing"] == ["vix30_h63"] and "vix30_h63" not in row["cells"]
    assert set(row["cells"]) == set(C.CELL_ORDER) - {"vix30_h63"}


def test_completeness_detects_deleted_row(live_root: Path) -> None:
    rows = read_jsonl(live_root / V15_SHADOW)
    write_jsonl(live_root / V15_SHADOW, rows[1:])
    report = SH.verify_shadow_v15_vol(live_root)
    assert not report["ok"] and f"shadow incomplete: {rows[0]['as_of']}" in report["errors"]


def test_late_capture_grade_is_copied(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    rows = read_jsonl(root / V13_LIVE)
    late = [r for r in rows if r.get("pit_grade") == "late_capture"]
    if not late:
        target = rows[-1]
        target["pit_grade"] = "late_capture"
        body = {k: v for k, v in target.items() if k != "content_hash"}
        target["content_hash"] = C.canonical_hash(body)
        write_jsonl(root / V13_LIVE, rows)
        late = [target]
    arm(root)
    write_arming(root, effective_from="2026-09-08")
    SH.publish_shadow_v15_vol(root, now=NOW)
    shadow = {r["v13_run_id"]: r for r in read_jsonl(root / V15_SHADOW)}
    for row in late:
        if row["run_id"] in shadow:
            assert shadow[row["run_id"]]["v13_pit_grade"] == "late_capture"
    assert any(row["run_id"] in shadow for row in late)


def test_as_of_oracle_2026_11_09(live_root: Path) -> None:
    row = next(r for r in read_jsonl(live_root / V15_SHADOW) if r["as_of"] == "2026-11-09")
    cell = row["cells"]["vix25_h5"]
    assert row["inputs"]["vix_close"] == 19.92 and cell["calm"] is True
    assert abs(cell["p_pb"] - 0.099152) < 1e-6
    assert abs(cell["p_r1"] - 0.062135) < 1e-6
    assert abs(cell["p_r2"] - 0.140998) < 1e-6        # 정확값 0.1409981597 (명세 0.140999 는 반올림 오기 — 리뷰 N7)
    assert abs(cell["p_r3"] - 0.054558) < 1e-6


def test_repository_local_run_is_hold(monkeypatch) -> None:
    """실저장소에서 로컬 실행 → not_armed(커밋 A) 또는 arming_pending_ci(커밋 B) — 쓰기 0 (autouse 가 해시 대조)."""
    from v15_vol_fixtures import ROOT

    if (ROOT / ARMING).exists():
        pytest.skip("머지 뒤 — 무장행이 이미 있다(실저장소 발행은 워크플로만 한다)")
    result = SH.publish_shadow_v15_vol(ROOT, now=NOW)
    assert result["status"] == "hold" and result["reasons"] in (["not_armed"], ["arming_pending_ci"])


# ── 리뷰 수정(w1-u5 fix) ────────────────────────────────────────────────────────
def test_disarm_after_arming_keeps_verify_green(live_root: Path) -> None:
    """B1: 철회(영수증 revocation — gates.armed false·track_open false) 뒤 V13 이 새 행을 내도 verify 는 초록."""
    _add_v13_origin(live_root, "2026-11-12")
    armed_report = SH.verify_shadow_v15_vol(live_root)
    assert "shadow incomplete: 2026-11-12" in armed_report["errors"]          # 무장 중에는 완전성 오류(대조군)

    def _disarm(c: dict) -> None:
        c["gates"]["armed"] = False
        c["development_protocol"]["track_open"] = False

    edit_contract(live_root, _disarm)
    held = SH.publish_shadow_v15_vol(live_root, now=NOW)
    assert held == {"status": "hold", "reasons": ["not_armed"], "appended": 0}
    report = SH.verify_shadow_v15_vol(live_root)
    assert report["ok"], report["errors"]
    assert "disarmed_after_arming" in report["notes"]
    assert report["completeness_upper"] == max(r["as_of"] for r in read_jsonl(live_root / V15_SHADOW))
    # 철회 뒤에도 이미 쓴 구간의 구멍·변조는 잡는다.
    rows = read_jsonl(live_root / V15_SHADOW)
    write_jsonl(live_root / V15_SHADOW, rows[:3] + rows[4:])
    report = SH.verify_shadow_v15_vol(live_root)
    assert not report["ok"] and f"shadow incomplete: {rows[3]['as_of']}" in report["errors"]
    rows[0]["cells"]["vix25_h5"]["p_r3"] += 1e-6
    write_jsonl(live_root / V15_SHADOW, [_rehash(rows[0])] + rows[1:])
    assert any(e.startswith("recompute:") for e in SH.verify_shadow_v15_vol(live_root)["errors"])


def test_termination_ack_exempts_later_v13_rows(live_root: Path) -> None:
    """B1: armed ∧ hold ∧ termination_acknowledged — V13 이 같은 sha 로 계속 발행해도 verify 초록."""
    constants = live_root / C.CONSTANTS_RELATIVE
    constants.write_bytes(constants.read_bytes() + b" ")
    edit_contract(live_root, lambda c: c["parent_v13"].__setitem__("termination_acknowledged", "V13-T7-test"))
    _add_v13_origin(live_root, "2026-11-12")
    assert SH.publish_shadow_v15_vol(live_root, now=NOW)["reasons"] == ["constants_pin_mismatch"]
    report = SH.verify_shadow_v15_vol(live_root)
    assert report["ok"], report["errors"]
    assert any(n.startswith("v13_terminated_acknowledged") for n in report["notes"])
    rows = read_jsonl(live_root / V15_SHADOW)
    write_jsonl(live_root / V15_SHADOW, rows[:2] + rows[3:])
    assert f"shadow incomplete: {rows[2]['as_of']}" in SH.verify_shadow_v15_vol(live_root)["errors"]


def test_recompute_detects_informational_field_tamper(live_root: Path) -> None:
    """N1: inputs·v13_pit_grade 등 정보 필드도 원천 V13 행에서 다시 만든 값과 대조한다."""
    rows = read_jsonl(live_root / V15_SHADOW)
    rows[0]["inputs"]["vix_close"] = 99.0
    rows[1]["v13_pit_grade"] = "late_capture" if rows[1]["v13_pit_grade"] != "late_capture" else "captured_forward"
    rows[2]["holdout_status"] = "holdout"
    write_jsonl(live_root / V15_SHADOW, [_rehash(r) for r in rows[:3]] + rows[3:])
    errors = SH.verify_shadow_v15_vol(live_root)["errors"]
    assert f"recompute field inputs: {rows[0]['run_id']}" in errors
    assert f"recompute field v13_pit_grade: {rows[1]['run_id']}" in errors
    assert f"recompute field holdout_status: {rows[2]['run_id']}" in errors


def test_informational_row_fields_are_not_recompute_errors(live_root: Path) -> None:
    """N1 경계: derived_at(늦은 계산 허용)·contract_sha256(row_contract_sha256: informational)은 대조 제외."""
    rows = read_jsonl(live_root / V15_SHADOW)
    rows[0]["derived_at"] = "2026-12-01T00:00:00+00:00"
    rows[0]["contract_sha256"] = "0" * 64
    write_jsonl(live_root / V15_SHADOW, [_rehash(rows[0])] + rows[1:])
    report = SH.verify_shadow_v15_vol(live_root)
    assert report["ok"], report["errors"]
    rows[0]["derived_at"] = "not-a-time"
    write_jsonl(live_root / V15_SHADOW, [_rehash(rows[0])] + rows[1:])
    assert f"derived_at unparseable: {rows[0]['run_id']}" in SH.verify_shadow_v15_vol(live_root)["errors"]


def test_arming_row_must_follow_commit_b(tmp_path: Path) -> None:
    """N2: 무장행 prereg_commit = 계약 prereg_commit, armed_observed_at >= 계약 armed_at(커밋 B 시각)."""
    root = make_root(tmp_path)
    arm(root, armed_at="2026-11-11T20:00:00+09:00")
    write_arming(root, effective_from="2026-10-01")                    # 커밋 B 이전 날짜의 위조·오작성 행
    report = SH.verify_shadow_v15_vol(root)
    assert not report["ok"]
    assert "arming armed_observed_at is earlier than contract live_shadow.armed_at" in report["errors"]
    held = SH.publish_shadow_v15_vol(root, now=NOW)                    # 소급 행 append 거부(append-only)
    assert held["status"] == "hold" and held["reasons"] == ["arming_row_invalid"] and held["appended"] == 0
    assert not (root / V15_SHADOW).exists()
    write_arming(root, effective_from="2026-11-16", armed_observed_at="2026-11-13T11:25:00+00:00",
                 prereg_commit="deadbeef")
    report = SH.verify_shadow_v15_vol(root)
    assert report["errors"] == ["arming prereg_commit differs from contract development_protocol.prereg_commit"]
    write_arming(root, effective_from="2026-11-16", armed_observed_at="2026-11-13T11:25:00+00:00")
    assert SH.verify_shadow_v15_vol(root)["ok"]
