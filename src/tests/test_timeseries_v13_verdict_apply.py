"""V13-D15 라이브 판정 적용 경로 — 영수증 정지점·체크포인트 절단 표본·영구 강등·T7·검증·표시/배선 연결.

쓰기는 tmp_path 사본만(실저장소 원장 쓰기 0). 산술은 live_verdict._evaluate_cell 그대로(draws 120 고정).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import resolve as R
from ai_fc.timeseries_v13 import verdict_apply as VA
from ai_fc.timeseries_v13 import verdict_ledger as VL
from ai_fc.timeseries_v13.contracts import TimeSeriesV13VolError

ROOT = Path(__file__).resolve().parents[2]
PINNED = "a" * 64
OLD = "b" * 64
RECEIPT = "v13-approval:V13-D15:2026-11-11:r1"
INSTRUCTION = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
NOW = datetime(2027, 1, 20, 3, tzinfo=timezone.utc)


def _origin(i: int) -> str:
    return (date(2026, 9, 4) + timedelta(days=i)).isoformat()


def _row(cell: str, i: int, *, p: float, label: float, base: float, sha: str = PINNED,
         cutoff: str = "2026-10-01T00:00:00+00:00") -> dict:
    origin = _origin(i)
    body = {"schema_version": 1, "resolution_id": f"v13vol-{origin}-{sha[:8]}-{cell}",
            "run_id": f"v13vol-{origin}-{sha[:8]}", "cell": cell, "origin": origin,
            "horizon_sessions": 5, "resolved_session": _origin(i + 7), "probability": p, "label": label,
            "brier_model": round((p - label) ** 2, 8), "brier_climatology": round((base - label) ** 2, 8),
            "climatology_base_rate": base, "coefficients_sha256": sha,
            "finalist_id": "V13VOL_champion_aec80c65038b", "holdout_status_at_forecast": "partial",
            "knowledge_cutoff": cutoff}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _anti(cell: str, idx) -> list[dict]:
    """모형이 기후보다 나쁘다 — 사건일에 0.1, 평온일에 0.8 → demotion_candidate."""
    return [_row(cell, i, p=0.1 if i % 4 == 0 else 0.8, label=1.0 if i % 4 == 0 else 0.0, base=0.25) for i in idx]


def _good(cell: str, idx) -> list[dict]:
    return [_row(cell, i, p=0.8 if i % 4 == 0 else 0.1, label=1.0 if i % 4 == 0 else 0.0, base=0.42) for i in idx]


def _quiet(cell: str, idx) -> list[dict]:
    return [_row(cell, i, p=0.05, label=0.0, base=0.55) for i in idx]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _tmp_repo(tmp_path: Path, rows: list[dict] | None = None, *, contract_edit=None) -> Path:
    root = tmp_path
    dst = root / C.CONTRACT_RELATIVE
    dst.parent.mkdir(parents=True, exist_ok=True)
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["frozen_coefficients"]["sha256"] = PINNED
    if contract_edit:
        contract_edit(contract)
    dst.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (root / C.APPROVALS_LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / C.APPROVALS_LEDGER_RELATIVE, root / C.APPROVALS_LEDGER_RELATIVE)
    if rows is not None:
        _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, rows)
    return root


def _apply(root: Path, **kwargs) -> dict:
    kwargs.setdefault("now", NOW)
    return VA.apply_live_verdicts(root, approval_receipt_id=kwargs.pop("receipt", RECEIPT), **kwargs)


def _ledger(root: Path) -> list[dict]:
    path = root / VL.APPLICATIONS_LEDGER_RELATIVE
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l] if path.is_file() else []


def _forged(cell: str, k: int = 60, outcome: str = "demotion_applied", **extra) -> dict:
    row = {"schema_version": 1, "application_id": f"v13-apply:{cell}:k{k}", "kind": "checkpoint_verdict",
           "cell": cell, "checkpoint": k, "outcome": outcome,
           "effect": "cell_display_hold" if outcome == "demotion_applied" else "none", **extra}
    row["content_hash"] = C.canonical_hash(row)
    return row


def _rehash(row: dict) -> dict:
    row = dict(row)
    row.pop("content_hash", None)
    row["content_hash"] = C.canonical_hash(row)
    return row


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)


# 1 ───────────────────────────────────────────────────────────────────────────
def test_refuses_without_receipt_before_reading_ledgers(tmp_path: Path, monkeypatch) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    calls = {"rows": 0, "apps": 0}

    def _boom_rows(*_a, **_k):
        calls["rows"] += 1
        raise AssertionError("resolution ledger read before the receipt check")

    def _boom_apps(*_a, **_k):
        calls["apps"] += 1
        raise AssertionError("application ledger read before the receipt check")

    monkeypatch.setattr(VA, "_file_order_rows", _boom_rows)
    monkeypatch.setattr(VL, "read_applications", _boom_apps)
    approvals = [json.loads(l) for l in (root / C.APPROVALS_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if l]
    base = next(r for r in approvals if r["receipt_id"] == RECEIPT)

    def _with(receipt: dict) -> None:
        _write_jsonl(root / C.APPROVALS_LEDGER_RELATIVE, approvals + [receipt])

    for receipt_id in ("", "   ", "v13-approval:missing"):
        with pytest.raises(TimeSeriesV13VolError):
            _apply(root, receipt=receipt_id)
    # 변형마다 **자기 사유**로 거부되는지 match 로 고정한다 — 계약 포인터 검사(마지막)가 모든 변형을 대신 거부하면
    # 앞선 검사가 빠져도 초록이 된다(리뷰 B1 과 같은 공허 단언 방지).
    scope = base["approval_scope"]
    variants = [
        ({**base, "receipt_id": "x1", "decision_id": "V13-D14"}, "not a V13-D15"),
        ({**base, "receipt_id": "x2", "approval_scope": {**scope, "cells": ["rv_h5"]}}, "cells do not cover"),
        ({**base, "receipt_id": "x3", "approval_scope": {**scope, "early_application": True}}, "early application"),
        ({**base, "receipt_id": "x4", "approved_at": "2099-01-01T00:00:00+09:00"}, "in the future"),
        ({**base, "receipt_id": "x5", "approved_at": "2026-11-11T18:03:44"}, "timezone"),
        ({**base, "receipt_id": "x6", "approval_text": " "}, "verbatim approval text"),
        ({**base, "receipt_id": "x7", "template_text": ""}, "template_text"),
        ({**base, "receipt_id": "x9", "approval_scope": {**scope, "automation": True}}, "automation"),
        ({**base, "receipt_id": "x10", "approval_scope": {k: v for k, v in scope.items() if k != "automation"}},
         "automation"),
        ({**base, "receipt_id": "x11", "approval_scope": {**scope, "checkpoints": {"first": 60, "step": 10}}},
         "checkpoints do not match"),
        ({**base, "receipt_id": "x12", "approval_scope": {**scope, "checkpoints": {"first": 40, "step": 20}}},
         "checkpoints do not match"),
        ({**base, "receipt_id": "x13", "approval_scope": {k: v for k, v in scope.items() if k != "checkpoints"}},
         "checkpoints do not match"),
    ]
    for variant, reason in variants:
        _with(variant)
        with pytest.raises(TimeSeriesV13VolError, match=reason):
            _apply(root, receipt=variant["receipt_id"])
    # 계약이 다른 영수증을 가리키면 거부(변형 영수증이 형식은 맞아도)
    _with({**base, "receipt_id": "x8"})
    with pytest.raises(TimeSeriesV13VolError, match="does not point"):
        _apply(root, receipt="x8")
    # supersedes 철회 행이 있으면 거부
    _with({**base, "receipt_id": "v13-approval:V13-D15:2026-11-11:r2", "supersedes": RECEIPT})
    with pytest.raises(TimeSeriesV13VolError, match="superseded"):
        _apply(root)
    assert calls == {"rows": 0, "apps": 0}


# 1a ──────────────────────────────────────────────────────────────────────────
def test_refuses_when_contract_schedule_drifts_from_receipt(tmp_path: Path, monkeypatch) -> None:
    """계약 checkpoints 를 영수증 뒤에 바꾸면(결과 후 규칙 변경) 같은 영수증으로도 원장을 읽기 전에 거부한다."""
    def _boom(*_a, **_k):
        raise AssertionError("ledger read before the receipt check")

    monkeypatch.setattr(VA, "_file_order_rows", _boom)
    for drift in ({"first": 60, "step": 10}, {"first": 60, "step": 40}):
        root = _tmp_repo(tmp_path / f"s{drift['step']}", _anti("vix25_h21", range(60)),
                         contract_edit=lambda c, d=drift: c["live_verdict_application"].__setitem__("checkpoints", dict(d)))
        with pytest.raises(TimeSeriesV13VolError, match="checkpoints do not match"):
            _apply(root)
        assert not (root / VL.APPLICATIONS_LEDGER_RELATIVE).exists()


# 2 ───────────────────────────────────────────────────────────────────────────
def test_no_row_below_first_checkpoint(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(59)))
    out = _apply(root)
    assert out["planned"] == [] and out["written"] == 0
    assert not (root / VL.APPLICATIONS_LEDGER_RELATIVE).exists()


# 3 ───────────────────────────────────────────────────────────────────────────
def test_demotion_at_60_writes_sticky_row_and_is_idempotent(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    out = _apply(root)
    assert out["written"] == 1 and out["demoted_cells"] == ["vix25_h21"]
    rows = _ledger(root)
    assert len(rows) == 1
    row = rows[0]
    assert row["application_id"] == "v13-apply:vix25_h21:k60" and row["outcome"] == "demotion_applied"
    assert row["verdict"]["status"] == "demotion_candidate" and row["effect"] == "cell_display_hold"
    assert len(row["origins"]) == 60 and len(row["resolution_ids"]) == 60 and row["sample_rule"] == "ledger_first_recorded_k"
    assert row["arithmetic"]["null_draws"] == 120 and row["approval_receipt"] == RECEIPT
    assert row["notice"] == "참고 의견, 매매 신호 아님"
    again = _apply(root, now=NOW + timedelta(days=3))
    assert again["written"] == 0 and again["planned"] == []
    assert len(_ledger(root)) == 1
    assert VL.read_applications(root)["demoted"] == ["vix25_h21"]


# 4 ───────────────────────────────────────────────────────────────────────────
def test_late_run_equals_on_time_run(tmp_path: Path) -> None:
    base = _anti("vix25_h21", range(60))
    a = _tmp_repo(tmp_path / "a", base)
    b = _tmp_repo(tmp_path / "b", base + _good("vix25_h21", range(60, 63)))
    _apply(a)
    _apply(b)
    ra, rb = _ledger(a)[0], _ledger(b)[0]
    for key in ("verdict", "origins", "resolution_ids", "resolution_ids_sha256"):
        assert json.dumps(ra[key], sort_keys=True) == json.dumps(rb[key], sort_keys=True), key


# 4a ──────────────────────────────────────────────────────────────────────────
def test_out_of_order_resolution_does_not_change_checkpoint_sample(tmp_path: Path) -> None:
    cell = "rv_h21"
    early = [r for r in _good(cell, range(61)) if r["origin"] != _origin(30)]   # 원점 30 이 늦게 해상
    late30 = _good(cell, [30])
    t1 = _tmp_repo(tmp_path / "t1", early)
    t2 = _tmp_repo(tmp_path / "t2", early + late30)
    s1 = VL.checkpoint_sample(VA._file_order_rows(t1)[cell], 60)
    s2 = VL.checkpoint_sample(VA._file_order_rows(t2)[cell], 60)
    ids1 = [r["resolution_id"] for r in s1]
    assert ids1 == [r["resolution_id"] for r in s2]
    assert _origin(30) not in {r["origin"] for r in s1}
    # r1 정의(origin 순 앞 60)였다면 T2 는 {0..59} 가 되어 달랐다
    by_origin = sorted(VA._file_order_rows(t2)[cell], key=lambda r: r["origin"])[:60]
    assert [r["resolution_id"] for r in by_origin] != ids1
    _apply(t1)
    _apply(t2)
    assert _ledger(t1)[0]["resolution_ids"] == _ledger(t2)[0]["resolution_ids"] == ids1
    assert _ledger(t1)[0]["verdict"] == _ledger(t2)[0]["verdict"]


# 4b ──────────────────────────────────────────────────────────────────────────
def test_duplicate_origin_keeps_first_position_and_pinned_value(tmp_path: Path) -> None:
    cell = "rv_h5"
    old_first = _row(cell, 0, p=0.5, label=0.0, base=0.42, sha=OLD, cutoff="2026-09-12T00:00:00+00:00")
    rest = _good(cell, range(1, 61))
    pinned_late = _good(cell, [0])[0]
    root = _tmp_repo(tmp_path, [old_first] + rest + [pinned_late])
    ordered = VA._file_order_rows(root)[cell]
    assert ordered[0]["origin"] == _origin(0)                      # 위치 = 첫 등장 자리
    assert ordered[0]["resolution_id"] == pinned_late["resolution_id"]  # 값 = 핀 sha 행
    sample = VL.checkpoint_sample(ordered, 60)
    assert pinned_late["resolution_id"] in {r["resolution_id"] for r in sample}
    assert _origin(60) not in {r["origin"] for r in sample}


# 5 ───────────────────────────────────────────────────────────────────────────
def test_void_and_pass_outcomes_record_without_effect(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _quiet("rv_h5", range(60)) + _good("rv_h21", range(60)))
    out = _apply(root)
    by_cell = {r["cell"]: r for r in _ledger(root)}
    assert by_cell["rv_h5"]["outcome"] == "verdict_void" and by_cell["rv_h5"]["effect"] == "none"
    assert by_cell["rv_h21"]["outcome"] == "no_demotion" and by_cell["rv_h21"]["effect"] == "none"
    assert out["demoted_cells"] == [] and VL.read_applications(root)["demoted"] == []
    from ai_fc import timeseries_v13_vol_display as display
    proj = display.build_projection(None, tier="t3_live_card", contract=C.load_contract_v13(root), freshness=None,
                                    pin_ok=False, pin_reason=None, applications=VL.read_applications(root))
    assert proj["cell_badges"]["rv_h21"]["live_verdict"]["outcome"] == "no_demotion"
    assert "live_demoted_cells" not in proj


# 6 ───────────────────────────────────────────────────────────────────────────
def test_later_checkpoint_after_demotion_never_rearms(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("rv_h5", range(60)) + _good("rv_h5", range(60, 80)))
    _apply(root)
    rows = {r["application_id"]: r for r in _ledger(root)}
    assert rows["v13-apply:rv_h5:k60"]["outcome"] == "demotion_applied"
    assert rows["v13-apply:rv_h5:k80"]["outcome"] == "recorded_after_demotion"
    assert rows["v13-apply:rv_h5:k80"]["effect"] == "none"
    assert VL.read_applications(root)["demoted"] == ["rv_h5"]


# 7 ───────────────────────────────────────────────────────────────────────────
def test_t7_waits_for_all_scope_cells_then_triggers(tmp_path: Path) -> None:
    from ai_fc import read_model_contract
    from ai_fc import timeseries_v13_vol_display as display

    rows = _anti("vix25_h21", range(60)) + _anti("rv_h5", range(60)) + _good("rv_h21", range(59))
    root = _tmp_repo(tmp_path, rows)
    first = _apply(root)
    assert first["t7_applied"] is False and sorted(first["demoted_cells"]) == ["rv_h5", "vix25_h21"]
    assert VL.read_applications(root)["t7"] is None
    _append_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, _good("rv_h21", [59]))
    second = _apply(root)
    assert second["t7_applied"] is True and second["followups"]
    t7 = VL.read_applications(root)["t7"]
    assert t7["kind"] == "t7_termination" and t7["effect"] == "card_hold"
    assert sorted(t7["demoted_cells"]) == ["rv_h5", "vix25_h21"]
    assert VA.verify_live_verdict_applications(root)["ok"] is True
    # T7 만으로 숨겨지는지 — 나머지 게이트는 전부 통과(live latest·핀·신선도·무장) 상태에서 본다(리뷰 비차단 9).
    applications = VL.read_applications(root)
    proj = display.build_projection(_live_latest(), tier="t3_live_card", contract=C.load_contract_v13(root),
                                    freshness={"status": "fresh"}, pin_ok=True, pin_reason=None, armed_now=True,
                                    applications=applications)
    assert proj["status"] == "hold" and proj["numbers_visible"] is False and "cells" not in proj
    assert any("t7_terminated" in r for r in proj["gate"]["reasons"])
    control = display.build_projection(_live_latest(), tier="t3_live_card", contract=C.load_contract_v13(root),
                                       freshness={"status": "fresh"}, pin_ok=True, pin_reason=None, armed_now=True,
                                       applications={**applications, "t7": None})
    assert control["status"] == "live"                                  # T7 행만 빼면 live — 숨김 원인은 T7
    errors = [e for e in read_model_contract.validate({"timeseries_v13_vol": proj}) if "timeseries_v13_vol" in e]
    assert errors == []


def test_t7_reason_and_demoted_cells_hide_numbers_on_live_projection() -> None:
    from ai_fc import read_model_contract
    from ai_fc import timeseries_v13_vol_display as display

    contract = C.load_contract_v13(ROOT)
    latest = _live_latest()
    demoted = {"status": "ok", "rows": [_forged("rv_h5")], "by_id": {}, "demoted": ["rv_h5"], "t7": None}
    proj = display.build_projection(latest, tier="t3_live_card", contract=contract,
                                    freshness={"status": "fresh"}, pin_ok=True, pin_reason=None,
                                    armed_now=True, applications=demoted)
    assert proj["status"] == "live" and "rv_h5" not in proj["cells"] and proj["live_demoted_cells"] == ["rv_h5"]
    assert proj["cell_badges"]["rv_h5"]["live_verdict"]["outcome"] == "demotion_applied"
    assert [e for e in read_model_contract.validate({"timeseries_v13_vol": proj}) if "timeseries_v13_vol" in e] == []
    t7 = {**demoted, "t7": {"kind": "t7_termination"}}
    held = display.build_projection(latest, tier="t3_live_card", contract=contract, freshness={"status": "fresh"},
                                    pin_ok=True, pin_reason=None, armed_now=True, applications=t7)
    assert held["status"] == "hold" and "cells" not in held
    assert any("t7_terminated" in r for r in held["gate"]["reasons"])
    # 검증기: 숫자가 보이는데 강등 셀이 있거나 T7 사유가 있으면 오류
    bad = dict(proj); bad["cells"] = {**proj["cells"], "rv_h5": dict(next(iter(proj["cells"].values())))}
    assert any("live-demoted" in e for e in read_model_contract.validate({"timeseries_v13_vol": bad}))
    bad2 = dict(proj); bad2["gate"] = {**proj["gate"], "reasons": ["t7_terminated — x"]}
    assert any("T7-terminated" in e for e in read_model_contract.validate({"timeseries_v13_vol": bad2}))
    # 심층 방어(리뷰 비차단 3): live_demoted_cells 를 만든 경로가 셀을 빠뜨려도 셀 배지 요약에서 다시 잡는다
    assert "rv_h21" in proj["cells"]
    badges = json.loads(json.dumps(proj["cell_badges"]))
    badges["rv_h21"]["live_verdict"] = {"checkpoint": 80, "outcome": "recorded_after_demotion"}
    bad3 = dict(proj); bad3["cell_badges"] = badges
    errors3 = read_model_contract.validate({"timeseries_v13_vol": bad3})
    assert any("badge-demoted" in e for e in errors3) and any("disagrees" in e for e in errors3)


def _live_latest() -> dict:
    cells = {}
    for name in C.CELL_ORDER:
        h = int(name.rsplit("h", 1)[1])
        cells[name] = {"model": "persistence_pb", "target": "vix_touch" if name.startswith("vix") else "rv_exceedance",
                       "h": h, "p": 0.42, "p_raw": 0.42, "se_raw": 0.03, "band80": [0.38, 0.46],
                       "derived_layer": "raw", "clim_base_rate": 0.31, "reliability": "good"}
    return {"status": "live", "as_of": "2026-11-10", "knowledge_cutoff": "2026-11-11T00:00:00+00:00",
            "gate": {"design_gate_pass": True, "armed": True, "coefficients_pinned": True, "freshness_pass": True,
                     "reasons": []},
            "inputs": {"vix_close": 18.0}, "cells": cells}


# 8 ───────────────────────────────────────────────────────────────────────────
def test_non_pass_cells_never_get_rows(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix30_h5", range(60)) + _anti("vix25_h63", range(60)))
    out = _apply(root)
    assert out["planned"] == [] and not (root / VL.APPLICATIONS_LEDGER_RELATIVE).exists()


# 9 ───────────────────────────────────────────────────────────────────────────
def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    out = _apply(root, dry_run=True)
    assert out["dry_run"] is True and out["written"] == 0 and len(out["planned"]) == 1
    assert out["planned"][0]["outcome"] == "demotion_applied"
    assert not (root / VL.APPLICATIONS_LEDGER_RELATIVE).exists()


# 10 ──────────────────────────────────────────────────────────────────────────
def test_verify_detects_tamper_and_recompute_mismatch(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    _apply(root)
    ledger = root / VL.APPLICATIONS_LEDGER_RELATIVE
    original = _ledger(root)[0]
    assert VA.verify_live_verdict_applications(root)["ok"] is True

    def _verify_with(row: dict | list[dict]) -> dict:
        _write_jsonl(ledger, row if isinstance(row, list) else [row])
        return VA.verify_live_verdict_applications(root)

    tampered = json.loads(json.dumps(original)); tampered["verdict"]["brier_model"] = 0.5
    out = _verify_with(tampered)
    assert out["ok"] is False and "unreadable" in out["errors"][0]
    forged = json.loads(json.dumps(original)); forged["verdict"]["paired_loss_vs_climatology"]["ci90"][0] += 1e-3
    out = _verify_with(_rehash(forged))
    assert out["ok"] is False and any("recompute numbers" in e for e in out["errors"])
    missing = json.loads(json.dumps(original)); missing["resolution_ids"][5] = "nope"
    missing["resolution_ids_sha256"] = hashlib.sha256("\n".join(missing["resolution_ids"]).encode()).hexdigest()
    out = _verify_with(_rehash(missing))
    assert any("not in the resolution ledger" in e for e in out["errors"])
    prefix = json.loads(json.dumps(original)); prefix["checkpoint"] = 80; prefix["application_id"] = "v13-apply:vix25_h21:k80"
    out = _verify_with(_rehash(prefix))
    assert any("prefix" in e for e in out["errors"]) and any("length" in e for e in out["errors"])
    t7 = {"schema_version": 1, "application_id": "v13-apply:T7", "kind": "t7_termination",
          "scope_cells": ["vix25_h21", "rv_h5", "rv_h21"], "demoted_cells": ["vix25_h21"],
          "basis_application_ids": [original["application_id"]], "effect": "card_hold", "followups": [],
          "approval_receipt": RECEIPT, "computed_at": NOW.isoformat(), "git_head": None, "notice": "x"}
    out = _verify_with([original, _rehash(t7)])
    assert any("t7_termination" in e for e in out["errors"])
    # pending 은 경고뿐 — 체크포인트 도달·행 없음
    ledger.unlink()
    out = VA.verify_live_verdict_applications(root)
    assert out["ok"] is True and any("checkpoint 60 reached" in w for w in out["warnings"])


# 10b ─────────────────────────────────────────────────────────────────────────
def test_verify_rejects_resolution_ids_of_another_cell(tmp_path: Path) -> None:
    """같은 원점·같은 수치의 다른 셀 해상 행으로 바꿔 해시를 다시 맞춘 위조(리뷰 비차단 6)."""
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)) + _anti("vix30_h5", range(60)))
    _apply(root)
    ledger = root / VL.APPLICATIONS_LEDGER_RELATIVE
    original = _ledger(root)[0]
    assert original["cell"] == "vix25_h21" and VA.verify_live_verdict_applications(root)["ok"] is True
    swapped = json.loads(json.dumps(original))
    swapped["resolution_ids"] = [i.replace("-vix25_h21", "-vix30_h5") for i in swapped["resolution_ids"]]
    swapped["resolution_ids_sha256"] = VA._sha_ids(swapped["resolution_ids"])
    _write_jsonl(ledger, [_rehash(swapped)])
    out = VA.verify_live_verdict_applications(root)
    assert out["ok"] is False and any("belong to another cell" in e for e in out["errors"])
    assert not any("not in the resolution ledger" in e for e in out["errors"])


# 10a ─────────────────────────────────────────────────────────────────────────
def test_recompute_tolerance_and_numpy_version_gate(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    _apply(root)
    ledger = root / VL.APPLICATIONS_LEDGER_RELATIVE
    original = _ledger(root)[0]
    tiny = json.loads(json.dumps(original)); tiny["verdict"]["paired_loss_vs_climatology"]["ci90"][0] += 5e-10
    _write_jsonl(ledger, [_rehash(tiny)])
    assert VA.verify_live_verdict_applications(root)["ok"] is True
    big = json.loads(json.dumps(original)); big["verdict"]["paired_loss_vs_climatology"]["ci90"][0] += 1e-6
    _write_jsonl(ledger, [_rehash(big)])
    assert VA.verify_live_verdict_applications(root)["ok"] is False
    old = json.loads(json.dumps(big)); old["numpy_version"] = "1.0.0"
    _write_jsonl(ledger, [_rehash(old)])
    out = VA.verify_live_verdict_applications(root)
    assert out["ok"] is True and out["recompute"]["skipped_numpy_version"] == 1
    assert any(w.startswith("recompute_skipped_numpy_version") for w in out["warnings"])
    old_bad = json.loads(json.dumps(old)); old_bad["resolution_ids_sha256"] = "0" * 64
    _write_jsonl(ledger, [_rehash(old_bad)])
    assert VA.verify_live_verdict_applications(root)["ok"] is False   # 해시·목록 검사는 버전과 무관하게 오류


# 11 ──────────────────────────────────────────────────────────────────────────
def test_apply_verb_is_never_in_any_workflow() -> None:
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        assert "timeseries-v13-vol-apply-verdict" not in workflow.read_text(encoding="utf-8"), workflow.name
    cli = (ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8")
    assert '@app.command("timeseries-v13-vol-apply-verdict")' in cli and '"--verify-only"' in cli
    assert '"--as-of"' in cli


# 11a ─────────────────────────────────────────────────────────────────────────
def test_apply_refuses_in_ci_env(tmp_path: Path, monkeypatch) -> None:
    root = _tmp_repo(tmp_path, _anti("vix25_h21", range(60)))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(TimeSeriesV13VolError, match="interactive"):
        _apply(root)
    assert not (root / VL.APPLICATIONS_LEDGER_RELATIVE).exists()
    assert _apply(root, dry_run=True)["written"] == 0
    assert VA.verify_live_verdict_applications(root)["ok"] is True


# 12 ──────────────────────────────────────────────────────────────────────────
def test_contract_and_receipts_register_v13_d15() -> None:
    contract = C.load_contract_v13(ROOT)
    block = contract["live_verdict_application"]
    assert block["checkpoints"]["first"] == contract["live_forward_gate"]["minimum_matured_origins_per_cell"]
    assert block["checkpoints"] == {"first": 60, "step": 20}
    assert "처음 기록된 순서" in block["checkpoint_sample"]
    assert block["t7"]["cumulative_interpretation"]
    assert block["registered_before_any_cell_reached_minimum"] is True
    rows = [json.loads(l) for l in (ROOT / C.APPROVALS_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if l]
    by_id = {r["receipt_id"]: r for r in rows}
    superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
    receipt = by_id[block["approval_receipt"]]
    assert block["approval_receipt"] not in superseded
    assert receipt["approval_scope"]["cells"] == contract["publication"]["holdout_pass_cells"]
    assert receipt["approval_scope"]["early_application"] is False and receipt["approval_scope"]["automation"] is False
    assert receipt["approval_scope"]["checkpoints"] == block["checkpoints"]
    assert any("예약 작업" in c for c in receipt["conditions"])
    upper = datetime(2026, 11, 11, 9, 3, 44, tzinfo=timezone.utc)
    for decision in ("V13-D14", "V13-D15", "V13-D16"):
        row = by_id[f"v13-approval:{decision}:2026-11-11:r1"]
        assert row["decision_id"] == decision and row["approval_text"] == INSTRUCTION
        assert row["approval_form"] == "delegated_bundle_instruction" and row["literal_template_match"] is False
        assert row["template_text"] and row["template_text"] != INSTRUCTION
        stamp = datetime.fromisoformat(row["approved_at"])
        assert stamp.tzinfo is not None and stamp == upper            # instant 비교(표기와 무관)
    assert contract["live_forward_verdict_report_extension"]["approval_receipt"] in by_id
    assert contract["live_display_caveats"]["approval_receipt"] in by_id


# 13 ──────────────────────────────────────────────────────────────────────────
def test_wiring_excludes_demoted_and_blocks_on_unreadable_ledger(tmp_path: Path, monkeypatch) -> None:
    from ai_fc import vol_base_rate_wiring as W

    def _wiring_root(sub: str) -> Path:
        root = tmp_path / sub
        root.mkdir()
        shutil.copytree(ROOT / "data/contracts", root / "data/contracts")
        (root / "data/timeseries_v13/ledgers").mkdir(parents=True)
        for name in ("vol_live.jsonl", "vol_live_resolutions.jsonl", "approvals.jsonl"):
            shutil.copyfile(ROOT / "data/timeseries_v13/ledgers" / name, root / "data/timeseries_v13/ledgers" / name)
        return root

    absent = _wiring_root("absent")
    info = W.eligibility(absent)
    real = W.eligibility(ROOT)
    assert info["blocked_by_live_demotion"] == [] and info["live_demotion_reasons"] == {}
    assert info["eligible_cells"] == real["eligible_cells"]

    demoted = _wiring_root("demoted")
    _write_jsonl(demoted / VL.APPLICATIONS_LEDGER_RELATIVE, [_forged("rv_h5")])
    info = W.eligibility(demoted)
    assert info["blocked_by_live_demotion"] == ["rv_h5"] and info["live_demotion_reasons"]["rv_h5"] == ["live_demoted"]
    assert "rv_h5" not in info["eligible_cells"]
    assert all(r != "live_demoted" for rs in info["claim_block_reasons"].values() for r in rs)

    broken = _wiring_root("broken")
    (broken / VL.APPLICATIONS_LEDGER_RELATIVE).write_text("{not json\n", encoding="utf-8")
    info = W.eligibility(broken)
    assert info["eligible_cells"] == []
    assert info["blocked_by_live_demotion"] == sorted(info["contract_eligible_cells"])
    assert all(r[0].startswith("verdict_applications_unreadable") for r in info["live_demotion_reasons"].values())
    status = W.wiring_status(broken)
    assert "V13-D15 적용 원장을 읽지 못해" in status["reason"]
    assert W.wiring_status(absent)["reason"] != status["reason"]
    # 강등 셀만 있을 때 문구는 라이브 강등을 언급한다(eligible 이 남아 있으면 '대응 질문 없음' 문구)
    demoted_status = W.wiring_status(demoted)
    if not demoted_status["eligible_cells"]:
        assert "라이브 강등" in demoted_status["reason"]


# 14 ──────────────────────────────────────────────────────────────────────────
def test_due_prints_pending_checkpoint(tmp_path: Path, monkeypatch) -> None:
    root = _tmp_repo(tmp_path, _good("rv_h5", range(60)))
    pending = VL.pending_from_root(root)
    assert pending == [{"cell": "rv_h5", "matured": 60, "checkpoint": 60, "receipt": RECEIPT}]
    (root / VL.APPLICATIONS_LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (root / VL.APPLICATIONS_LEDGER_RELATIVE).write_text("[]\n", encoding="utf-8")
    broken = VL.pending_from_root(root)
    assert len(broken) == 1 and broken[0]["cell"] == "*" and "verdict_applications_unreadable" in broken[0]["error"]

    # cmd_due --json: V13 줄은 stderr 로만 — stdout 은 json.loads 가능
    from typer.testing import CliRunner

    from ai_fc import base_rates, cli

    class _Q:
        def __getattr__(self, _name):
            return lambda *a, **k: {}

    monkeypatch.setattr(cli, "_conn", lambda _root: None)
    monkeypatch.setattr(cli, "_sync_or_exit", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "load_registry", lambda _p: [])
    monkeypatch.setattr(cli, "compute_due", lambda *a, **k: [])
    monkeypatch.setattr(cli, "queries", _Q())
    monkeypatch.setattr(base_rates, "scan_stale_base_rates", lambda *a, **k: [])
    monkeypatch.setattr(VL, "pending_from_root",
                        lambda _root: [{"cell": "rv_h5", "matured": 60, "checkpoint": 60, "receipt": RECEIPT}])
    response = CliRunner().invoke(cli.app, ["due", "--json"])
    assert response.exit_code == 0, response.output
    assert json.loads(response.stdout) == []
    assert "[V13 판정 도래]" in response.stderr and "[V13 판정 도래]" not in response.stdout
    # 실행 명령을 건네는 줄에는 예약 작업 금지 문언이 붙는다(데스크톱 예약 에이전트가 due 를 읽는 경우 — 리뷰 비차단 2)
    command_lines = [l for l in response.stderr.splitlines() if "timeseries-v13-vol-apply-verdict" in l]
    assert command_lines and all(l.endswith("(대화형 세션만 · 예약 작업 금지)") for l in command_lines)


# 14a ─────────────────────────────────────────────────────────────────────────
def test_notify_digest_includes_v13_lines(monkeypatch) -> None:
    from ai_fc import notify

    sent: list[str] = []
    monkeypatch.setattr(notify, "send_message", lambda text: sent.append(text) or True)
    notify.send_digest([], extra_lines=["[V13 판정 도래] rv_h5 성숙 60/60"])
    assert "due 없음" not in sent[-1] and "V13 판정 도래 (1)" in sent[-1] and "rv_h5" in sent[-1]
    notify.send_digest([])
    assert sent[-1] == "✅ ai-fc: due 없음 — 모든 질문이 cadence 내"


# 15 ──────────────────────────────────────────────────────────────────────────
def test_ledger_is_registered_planned() -> None:
    registry = yaml.safe_load((ROOT / "data/contracts/ledger_registry.yaml").read_text(encoding="utf-8"))
    entries = registry.get("ledgers") if isinstance(registry, dict) else registry
    entry = next((e for e in entries if e.get("id") == "timeseries_v13_live_verdict_applications"), None)
    assert entry is not None, "ledger_registry 에 V13-D15 적용 원장 미등록(W2 w2-reg 가 impl/registry_U6.yaml 을 넣는다)"
    assert entry["path"] == VL.APPLICATIONS_LEDGER_RELATIVE.as_posix()
    assert entry["expected_state"] == "planned" and entry["cadence"] == "event"


# 16 ──────────────────────────────────────────────────────────────────────────
def test_v13_verify_never_fails_on_application_ledger(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from ai_fc import cli, config

    root = _tmp_repo(tmp_path, _good("rv_h5", range(3)))
    monkeypatch.setattr(config, "ROOT", root)
    # 기준을 ok=True·exit 0 으로 고정한다(리뷰 B1). tmp 사본은 포인터가 없어 기본 verify 가 이미 ok=False 라
    # '기준과 같은지' 비교로는 적용 원장 오류가 ok/errors 로 새는 회귀를 잡지 못한다(False==False).
    # 명령이 호출 시점에 모듈에서 import 하므로 모듈 속성 패치가 먹는다.
    monkeypatch.setattr("ai_fc.timeseries_v13.pipeline.verify_timeseries_v13_vol",
                        lambda _root: {"ok": True, "errors": []})
    monkeypatch.setattr("ai_fc.timeseries_v13.resolve.verify_live_resolutions",
                        lambda _root: {"ok": True, "errors": []})
    runner = CliRunner()

    def _run() -> tuple[int, dict]:
        response = runner.invoke(cli.app, ["timeseries-v13-vol-verify"])
        return response.exit_code, json.loads(response.stdout)

    base_code, base = _run()
    assert base_code == 0 and base["ok"] is True and base["errors"] == []
    assert not any(w.startswith("verdict_applications") for w in base.get("warnings", []))
    ledger = root / VL.APPLICATIONS_LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    cases = []
    ledger.write_text("{broken\n", encoding="utf-8")
    cases.append(_run())
    bad = _forged("rv_h5"); bad["outcome"] = "no_demotion"            # 해시 위조
    _write_jsonl(ledger, [bad])
    cases.append(_run())
    ledger.unlink()

    def _boom(_root):
        raise RuntimeError("boom")

    monkeypatch.setattr(VA, "verify_live_verdict_applications", _boom)
    cases.append(_run())
    assert len(cases) == 3
    for code, result in cases:
        # 절대값 단언 — 적용 원장 문제는 종료코드·ok·errors 어디에도 들어가지 않는다(경고로만).
        assert code == 0 and result["ok"] is True
        assert not any("verdict_applications" in str(e) for e in result["errors"])
        assert any(w.startswith("verdict_applications:") for w in result["warnings"])


# 17 ──────────────────────────────────────────────────────────────────────────
def test_real_application_ledger_verifies_strictly() -> None:
    out = VA.verify_live_verdict_applications(ROOT)
    assert out["ok"] is True, out["errors"]


# 18 ──────────────────────────────────────────────────────────────────────────
def test_read_applications_schema(tmp_path: Path) -> None:
    absent = VL.read_applications(tmp_path)
    assert absent == {"status": "ok", "path": VL.APPLICATIONS_LEDGER_RELATIVE.as_posix(), "exists": False,
                      "rows": [], "by_id": {}, "demoted": [], "t7": None, "error": None}
    path = tmp_path / VL.APPLICATIONS_LEDGER_RELATIVE
    path.parent.mkdir(parents=True)
    good = _forged("rv_h21")
    no_key = {k: v for k, v in _forged("rv_h5").items() if k != "outcome"}
    no_key = _rehash(no_key)
    tampered = dict(_forged("rv_h5")); tampered["cell"] = "rv_h21"
    bad_kind = _rehash({**_forged("rv_h5"), "kind": "other"})
    # 해시까지 맞춘 타입 오류 행(리뷰 비차단 4) — 표시 int() 예외·강등 누락(fail-open) 대신 unreadable
    typed = [_rehash({**_forged("rv_h5"), "checkpoint": bad}) for bad in ("60", 60.0, True, None, 0)]
    typed += [_rehash({**_forged("rv_h5"), "outcome": "demotion_aplied"}),
              _rehash({**_forged("rv_h5"), "cell": "rv_h7"})]
    for lines in (["{not json"], ["[1,2]"], [json.dumps(no_key)], [json.dumps(good), json.dumps(good)],
                  [json.dumps(tampered)], [json.dumps(bad_kind)], ["\x00\x01"],
                  *([json.dumps(row)] for row in typed)):
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = VL.read_applications(tmp_path)
        assert out["status"] == "unreadable" and out["rows"] == [] and out["demoted"] == [] and out["error"]
    path.write_text(json.dumps(good) + "\n", encoding="utf-8")
    ok = VL.read_applications(tmp_path)
    assert ok["status"] == "ok" and ok["demoted"] == ["rv_h21"] and ok["exists"] is True
    # 리더의 outcome 집합 == verb 가 쓸 수 있는 outcome 전부
    writable = {o for o, _e in VA.OUTCOME_BY_STATUS.values()} | {VA.AFTER_DEMOTION[0]}
    assert set(VL.KNOWN_OUTCOMES) == writable


# 19 ──────────────────────────────────────────────────────────────────────────
def test_display_absent_live_corrupt_hold_exception_hold(tmp_path: Path, monkeypatch) -> None:
    from ai_fc import timeseries_v13_vol_display as display
    from ai_fc import vol_base_rate_wiring as W

    calendar = Path("data/contracts/nyse_holidays.yaml")
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / calendar, root / calendar)
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["frozen_coefficients"]["sha256"] = PINNED
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
                                            encoding="utf-8")
    (root / C.COEFFICIENTS_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (root / C.COEFFICIENTS_RELATIVE).write_bytes(b"frozen")
    monkeypatch.setattr(display, "sha256_file", lambda p: PINNED if p.read_bytes() == b"frozen" else "z" * 64)
    latest = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "status": "live",
              "as_of": "2026-09-04", "knowledge_cutoff": "2026-09-08T03:40:00+00:00",
              "probability_unit": "fraction", "probability_space": C.PROBABILITY_SPACE,
              "coefficients": {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": PINNED,
                               "content_hash": "c" * 64, "finalist_id": contract["frozen_coefficients"]["finalist_id"]},
              "gate": {"design_gate_pass": True, "armed": True, "coefficients_pinned": True, "freshness_pass": True,
                       "holdout_status": "partial", "reasons": []},
              "freshness": {"rule": "nyse_trading_calendar", "as_of": "2026-09-04", "missing_sessions": 0,
                            "max_missing_sessions": 1, "status": "fresh"},
              "publication": {"customer_numbers_visible": True, "reference_opinion_only": True,
                              "combined_with_official_forecasts": False, "combined_with_scenario_v5_2": False,
                              "combined_with_timeseries_v8": False, "trading_signal": False,
                              "holdout_status": "partial"},
              "inputs": {"vix_close": 18.2}, "cells": _live_latest()["cells"], "footnote": "참고 의견 — 매매 신호 아님"}
    latest["content_hash"] = C.canonical_hash(latest)
    (root / C.LATEST_RELATIVE).write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    now = datetime(2026, 9, 8, 5, 0, tzinfo=timezone.utc)

    absent = display.load_projection(root, now=now)
    assert absent["status"] == "live" and "rv_h5" in absent["cells"]
    assert absent["caveats"][0]["id"] == "jump_risk_unmodeled"

    (root / VL.APPLICATIONS_LEDGER_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (root / VL.APPLICATIONS_LEDGER_RELATIVE).write_text("{broken\n", encoding="utf-8")
    corrupt = display.load_projection(root, now=now)
    assert corrupt["status"] == "hold" and "cells" not in corrupt
    assert "verdict_applications_unreadable" in corrupt["gate"]["reasons"]
    assert W._live_demotion_reasons(root, ("rv_h5", "rv_h21")).keys() == {"rv_h5", "rv_h21"}
    (root / VL.APPLICATIONS_LEDGER_RELATIVE).unlink()

    def _raise(_root):
        raise OSError("disk gone")

    monkeypatch.setattr(display.verdict_ledger, "read_applications", _raise)
    failed = display.load_projection(root, now=now)
    assert failed["status"] == "hold" and "cells" not in failed
    assert "verdict_applications_unreadable" in failed["gate"]["reasons"]


# 20 ──────────────────────────────────────────────────────────────────────────
def test_scoreboard_verdict_blocked_reason_is_conditional(tmp_path: Path) -> None:
    from ai_fc.timeseries_v13.live_scoreboard import projection

    root = _tmp_repo(tmp_path, _good("rv_h5", range(30)))
    board = projection(root)
    assert board["verdict"] is None and "미만 — 계약이 판정을 막는다" in board["verdict_blocked_reason"]
    assert board["applications_status"] == "ok"
    _write_jsonl(root / R.RESOLUTION_LEDGER_RELATIVE, _good("rv_h5", range(60)))
    board = projection(root)
    assert board["verdict"] is None and "live_verdict_applications" in board["verdict_blocked_reason"]
    cell = next(c for c in board["cells"] if c["cell"] == "rv_h5")
    assert cell["verdict_pending_checkpoint"] == 60 and cell["live_verdict"] is None
    _write_jsonl(root / VL.APPLICATIONS_LEDGER_RELATIVE, [_forged("rv_h5", outcome="no_demotion")])
    cell = next(c for c in projection(root)["cells"] if c["cell"] == "rv_h5")
    assert cell["verdict_pending_checkpoint"] is None and cell["live_verdict"]["outcome"] == "no_demotion"


# 3.5 스모크 — 설계창 재생(합성 2에피소드)
def test_design_replay_smoke_on_synthetic_panel() -> None:
    from ai_fc.timeseries_v13 import verdict_replay as RP
    from ai_fc.timeseries_v13.live_verdict import verdict_parameters

    params = verdict_parameters(C.load_contract_v13(ROOT))
    rows = []
    for i in range(160):
        day = (date(2009, 1, 1) + timedelta(days=i)).isoformat()
        event = i % 4 == 0
        p = (0.1 if event else 0.8) if i < 80 else (0.8 if event else 0.1)
        rows.append({"origin": day, "probability": p, "label": 1.0 if event else 0.0, "climatology_base_rate": 0.25})
    out = RP.replay_rows({"rv_h5": rows}, params, episode=80, checkpoints=(60, 80))
    cell = out["rv_h5"]
    assert cell["n_episodes"] == 2 and cell["rate_any_checkpoint"] >= cell["rate_k60_only"]
    assert cell["last_origin"] <= RP.DESIGN_END and cell["wilson90_any"] is not None
    with pytest.raises(ValueError):
        RP.replay_rows({"rv_h5": rows + [{**rows[0], "origin": "2015-01-02"}]}, params, episode=80,
                       checkpoints=(60,))
