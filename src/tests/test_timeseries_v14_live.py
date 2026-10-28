"""V14 조건부 전이 라이브 경로 — 발행(hold/live)·조건 충족 p·멱등 원장·백필·채점·CLI·워크플로.

합성 아카이브·임시 저장소만 쓴다. 실저장소 루트로는 발행·채점·동결을 돌리지 않는다(champion 은 rung-2 뒤에 정해진다).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import features as F
from ai_fc.timeseries_v14 import contracts as C
from ai_fc.timeseries_v14 import pipeline as P
from ai_fc.timeseries_v14 import resolve as R
from timeseries_v14_fixtures import (CHAMPION, D0, D1, D2, D3, EFFECTIVE_FROM, RECEIPT, ROOT, SUPERSEDED_RECEIPT, Obs,
                                     install, install_frozen, make_repo, now_after, observations, quiet_paths,
                                     read_jsonl, reader, replace, roles_for, sessions, stamp_after, upto,
                                     write_contract, write_jsonl, write_superseded_receipts)


def _archive(last_day: str, n: int = 160, *, last_vix: float | None = None, rv_jump_back: int | None = None):
    days = sessions(last_day, n)
    vix, ndx = quiet_paths(n)
    if last_vix is not None:
        vix[-1] = last_vix
    if rv_jump_back is not None:                 # 마지막 날에서 rv_jump_back 세션 전에 6% 로그수익 1회 — RV21 > θ 창을 만든다
        returns = np.diff(np.log(ndx), prepend=np.log(ndx[0]))
        returns[n - 1 - rv_jump_back] = 0.06
        ndx = 10000.0 * np.exp(np.cumsum(returns))
    return observations(days, vix, ndx)


def _pointer(root: Path) -> dict:
    return json.loads((root / C.LATEST_RELATIVE).read_text(encoding="utf-8"))


def _rows(root: Path) -> list[dict]:
    return read_jsonl(root / C.LIVE_LEDGER_RELATIVE)


# ── 계약 상수 · 분할 ──────────────────────────────────────────────────────────
def test_constants_match_the_registered_contract_targets_and_coordinates() -> None:
    contract = C.load_contract_v14(ROOT)          # 실계약 읽기만 — 표적·좌표가 코드 상수와 다르면 raise
    assert contract["gate"]["uncertainty"]["seed"] == C.SEED == 20261021
    assert [s["name"] for s in C.cell_specs()] == list(C.CELL_ORDER)
    assert C.THETA == contract["targets"]["rv_conditional_transition"]["theta"]
    # 포인터는 vol/ 밖 — 레지스트리의 data/timeseries_v14/vol/*.json(immutable_files) 감시에 걸리지 않는다
    assert not C.LATEST_RELATIVE.as_posix().startswith("data/timeseries_v14/vol/")
    assert C.COEFFICIENTS_RELATIVE.as_posix().startswith("data/timeseries_v14/vol/")


@pytest.mark.parametrize("champion", [[], ["crv_h5"], ["crv_h5", "cvix25_h21"], list(C.CELL_ORDER)])
def test_live_pointer_partition_is_data(tmp_path: Path, champion: list[str]) -> None:
    root = make_repo(tmp_path, champion=champion)
    cfg = C.live_pointer_config(C.load_contract_v14(root))
    assert cfg["champion_cells"] == [c for c in C.CELL_ORDER if c in champion]
    assert set(cfg["champion_cells"]) | set(cfg["shadow_cells"]) == set(C.CELL_ORDER)


@pytest.mark.parametrize("mutation,needle", [
    (lambda c: c["live_pointer"]["shadow_cells"].append("crv_h5"), "overlap"),
    (lambda c: c["live_pointer"]["shadow_cells"].remove("crv_h63"), "exactly the six"),
    (lambda c: c["live_pointer"].update(pointer="data/timeseries_v14/vol/v14_latest.json"), "live_pointer.pointer"),
    (lambda c: c.pop("live_pointer"), "no live_pointer"),
    # 계약 live_panel_start ↔ 코드 상수(build_live_panel 이 실제로 쓰는 창)
    (lambda c: c["live_pointer"].update(live_panel_start="2025-06-01"), "live_panel_start"),
    (lambda c: c["live_pointer"].pop("live_panel_start"), "live_panel_start"),
    # 포인터 블록의 tier ↔ publication.display_tier (정본) — 어느 쪽이 혼자 바뀌어도 거부
    (lambda c: c["live_pointer"].update(display_tier="t2_hidden_panel"), "differs from publication.display_tier"),
    (lambda c: c["publication"].update(display_tier="t3_live_card"), "differs from publication.display_tier"),
    (lambda c: c["live_pointer"].pop("display_tier"), "display_tier invalid"),
])
def test_live_pointer_config_fails_closed(tmp_path: Path, mutation, needle: str) -> None:
    root = make_repo(tmp_path)
    write_contract(root, champion=CHAMPION, sha="x", content_hash="y", mutate=mutation)
    with pytest.raises(C.TimeSeriesV14Error, match=needle):
        C.live_pointer_config(C.load_contract_v14(root))


def test_real_contract_live_pointer_matches_the_coded_panel_start_and_tier() -> None:
    cfg = C.live_pointer_config(C.load_contract_v14(ROOT))          # 실계약 읽기만
    contract = C.load_contract_v14(ROOT)
    assert str(contract["live_pointer"]["live_panel_start"]) == C.LIVE_PANEL_START
    assert cfg["display_tier"] == contract["publication"]["display_tier"] == "t0_internal"
    assert cfg["approval_receipt"] == RECEIPT


# ── 발행: hold 경로 ──────────────────────────────────────────────────────────
def _assert_hold(root: Path, result: dict, reason: str) -> None:
    assert result["status"] == "hold" and result["ledger_appended"] is False
    assert any(reason in r for r in result["reasons"]), result["reasons"]
    pointer = _pointer(root)
    P.validate_latest(pointer)
    assert pointer["status"] == "hold" and "cells" not in pointer and "inputs" not in pointer
    assert not _rows(root), "hold 는 원장에 쓰지 않는다"


def test_publish_holds_when_the_contract_pin_is_null(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path, pin=False)
    install(monkeypatch, P, _archive(D0))
    _assert_hold(root, P.publish_latest_timeseries_v14(root, now=now_after(D0)), "not pinned")


def test_publish_holds_when_the_pinned_sha_does_not_match_the_artifact(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    write_contract(root, champion=CHAMPION, sha="0" * 64, content_hash="1" * 64)
    install(monkeypatch, P, _archive(D0))
    _assert_hold(root, P.publish_latest_timeseries_v14(root, now=now_after(D0)), "sha256 mismatch")


def test_publish_holds_when_the_archive_is_stale(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0))
    result = P.publish_latest_timeseries_v14(root, now=now_after(D3))       # 10-23·10-26·10-27 누락 3 > 1
    _assert_hold(root, result, "stale")
    assert _pointer(root)["freshness"]["missing_sessions"] == 3


def test_publish_holds_without_the_d10_receipt(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path, receipt=False)
    install(monkeypatch, P, _archive(D0))
    _assert_hold(root, P.publish_latest_timeseries_v14(root, now=now_after(D0)), "approval_receipt_missing")


def test_superseded_d10_receipt_holds_and_the_governing_r2_goes_live(tmp_path: Path, monkeypatch) -> None:
    """정본 D10 영수증은 r2 다 — 원장에 r1 행이 남아 있어도 r2 가 supersedes 로 대체했으므로 r1 을 가리키는 계약은 hold."""
    install(monkeypatch, P, _archive(D0))
    stale = make_repo(tmp_path, receipt=False, name="points-at-r1")
    write_superseded_receipts(stale)
    sha, content_hash = (C.load_contract_v14(stale)["frozen_coefficients"][k] for k in ("sha256", "content_hash"))
    write_contract(stale, champion=CHAMPION, sha=sha, content_hash=content_hash,
                   mutate=lambda c: c["live_pointer"].update(approval_receipt=SUPERSEDED_RECEIPT))
    assert C.approval_receipt_present(stale, SUPERSEDED_RECEIPT) is False
    _assert_hold(stale, P.publish_latest_timeseries_v14(stale, now=now_after(D0)),
                 f"approval_receipt_missing: {SUPERSEDED_RECEIPT} not in approvals ledger")
    # 핀이 있는데 영수증 hold — 시간이 풀어 주는 hold 가 아니므로 verify 는 실패한다
    verify = P.verify_timeseries_v14(stale)
    assert verify["ok"] is False
    assert any("approval receipt missing or superseded" in e for e in verify["errors"]), verify["errors"]
    assert any("structural gate" in e and "approval_receipt_present" in e for e in verify["errors"]), verify["errors"]

    governing = make_repo(tmp_path, receipt=False, name="points-at-r2")
    write_superseded_receipts(governing)
    assert C.approval_receipt_present(governing, RECEIPT) is True
    result = P.publish_latest_timeseries_v14(governing, now=now_after(D0))
    assert result["status"] == "live" and result["reasons"] == []
    assert _pointer(governing)["scope"]["approval_receipt"] == RECEIPT
    assert P.verify_timeseries_v14(governing)["ok"] is True


def test_publish_holds_when_frozen_roles_differ_from_the_contract_partition(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path, champion=["crv_h5"], artifact_roles=roles_for(["crv_h5", "crv_h21"]))
    install(monkeypatch, P, _archive(D0))
    _assert_hold(root, P.publish_latest_timeseries_v14(root, now=now_after(D0)), "role_partition_mismatch")
    # 핀 뒤의 역할 불일치는 구성 오류 — hold 포인터 뒤에 숨어 verify 가 초록이 되면 안 된다
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is False
    assert "coefficients: frozen coefficient roles differ from live_pointer champion/shadow cells" in verify["errors"]


# ── verify 엄격성 — 핀이 있으면 언제나 계수를 싣고 대조한다 ─────────────────────
def test_verify_fails_when_the_pinned_artifact_is_missing_even_behind_a_hold(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0))
    P.publish_latest_timeseries_v14(root, now=now_after(D3))          # stale hold — 원장 0행
    assert _pointer(root)["status"] == "hold" and not _rows(root)
    assert P.verify_timeseries_v14(root)["ok"] is True, "신선도 hold 는 초록이어도 된다(시간이 푼다)"
    (root / C.COEFFICIENTS_RELATIVE).unlink()
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is False
    assert "coefficients: frozen coefficients artifact is missing" in verify["errors"]


def test_verify_passes_a_panel_too_short_hold_and_a_null_pin_hold(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0, n=15))                       # RV21 정의에 22 종가 필요
    result = P.publish_latest_timeseries_v14(root, now=now_after(D0))
    assert result["status"] == "hold" and any("panel_too_short_for_rv21" in r for r in result["reasons"])
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]
    # 핀 null(동결 전) — hold 가 정상 상태이며 계수를 요구하지 않는다
    unpinned = make_repo(tmp_path, pin=False, name="unpinned")
    install(monkeypatch, P, _archive(D0))
    assert P.publish_latest_timeseries_v14(unpinned, now=now_after(D0))["status"] == "hold"
    verify = P.verify_timeseries_v14(unpinned)
    assert verify["ok"] is True, verify["errors"]


# ── 발행: live 경로 ──────────────────────────────────────────────────────────
def test_live_pointer_records_p_only_for_condition_met_cells(tmp_path: Path, monkeypatch) -> None:
    # VIX_t = 22 (>= 20) → cvix 3셀 조건 불충족 · RV 평온 → crv 3셀 충족
    root = make_repo(tmp_path, name="vix-high")
    install(monkeypatch, P, _archive(D0, last_vix=22.0))
    result = P.publish_latest_timeseries_v14(root, now=now_after(D0))
    assert result["status"] == "live" and result["ledger_appended"] is True and result["as_of"] == D0
    pointer = _pointer(root)
    P.validate_latest(pointer, roles=roles_for(CHAMPION))
    assert pointer["inputs"]["vix_close"] == 22.0 and pointer["inputs"]["rv21_ann"] <= C.THETA
    for name, cell in pointer["cells"].items():
        assert cell["role"] == ("champion" if name in CHAMPION else "shadow")
        if name.startswith("cvix25"):
            assert cell["condition_met"] is False and cell["p"] is None and cell["level"] == 22.0
        else:
            assert cell["condition_met"] is True and 0.0 < cell["p"] < 1.0
    assert pointer["scope"] == {"champion_cells": CHAMPION, "shadow_cells": [c for c in C.CELL_ORDER if c not in CHAMPION],
                                "verdict_scope": "champion_cells", "shadow_in_verdict_scope": False,
                                "approval_receipt": "v14-approval:V14-D10:2026-10-28:r2"}
    assert pointer["publication"]["customer_numbers_visible"] is False
    assert pointer["publication"]["shadow_cells_displayable"] is False
    assert "band80" not in json.dumps(pointer)
    row = _rows(root)[0]
    assert {k: (v["condition_met"], v["p"], v["role"]) for k, v in row["cells"].items()} == \
        {k: (v["condition_met"], v["p"], v["role"]) for k, v in pointer["cells"].items()}
    # p 는 공유 logit_predict(동결 β·μ·σ) 그대로 — 재적합 없음
    frozen = json.loads((root / C.COEFFICIENTS_RELATIVE).read_text(encoding="utf-8"))["cells"]["crv_h5"]
    expected = F.logit_predict(np.array(frozen["beta"]), np.array(frozen["mu"]), np.array(frozen["sd"]),
                               np.array([[pointer["inputs"]["rv21_ann"]]]))[0]
    assert pointer["cells"]["crv_h5"]["p"] == round(float(expected), 6)
    assert P.verify_timeseries_v14(root)["ok"] is True

    # RV21_t > θ (마지막 날 5세션 전 6% 점프) · VIX 평온 → crv 3셀 불충족, cvix 3셀 충족
    root2 = make_repo(tmp_path, name="rv-high")
    install(monkeypatch, P, _archive(D0, rv_jump_back=5))
    assert P.publish_latest_timeseries_v14(root2, now=now_after(D0))["status"] == "live"
    cells = _pointer(root2)["cells"]
    assert _pointer(root2)["inputs"]["rv21_ann"] > C.THETA
    assert all(cells[c]["condition_met"] is False and cells[c]["p"] is None for c in ("crv_h5", "crv_h21", "crv_h63"))
    assert all(cells[c]["condition_met"] is True and cells[c]["p"] is not None for c in ("cvix25_h5", "cvix25_h21", "cvix25_h63"))
    assert P.verify_timeseries_v14(root2)["ok"] is True


def test_ledger_row_is_idempotent_per_as_of_and_coefficients_sha(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0))
    first = P.publish_latest_timeseries_v14(root, now=now_after(D0))
    again = P.publish_latest_timeseries_v14(root, now=now_after(D0) + timedelta(hours=1))
    assert first["ledger_appended"] is True and again["ledger_appended"] is False
    rows = _rows(root)
    assert len(rows) == 1 and rows[0]["run_id"] == f"v14cond-{D0}-{rows[0]['coefficients_sha256'][:8]}"
    assert P.verify_timeseries_v14(root)["ok"] is True
    # 재동결(새 sha) → 같은 as_of 라도 새 행 (이력 보존)
    sha, content_hash = install_frozen(root, roles_for(CHAMPION), tweak=0.25)
    write_contract(root, champion=CHAMPION, sha=sha, content_hash=content_hash)
    third = P.publish_latest_timeseries_v14(root, now=now_after(D0) + timedelta(hours=2))
    assert third["status"] == "live" and third["ledger_appended"] is True
    rows = _rows(root)
    assert len(rows) == 2 and len({r["run_id"] for r in rows}) == 2
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]


def test_verify_detects_ledger_tampering_and_pin_break(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0))
    P.publish_latest_timeseries_v14(root, now=now_after(D0))
    rows = _rows(root)
    rows[0]["cells"]["crv_h5"]["p"] = 0.999
    write_jsonl(root / C.LIVE_LEDGER_RELATIVE, rows)
    errors = P.verify_timeseries_v14(root)["errors"]
    assert any("hash mismatch" in e for e in errors) and any("ledger/pointer cell mismatch: crv_h5" in e for e in errors)
    (root / C.COEFFICIENTS_RELATIVE).write_bytes(b"{}")
    assert any(e.startswith("coefficients:") for e in P.verify_timeseries_v14(root)["errors"])


# ── 원점 백필 (V13-D12 기계 승계) ───────────────────────────────────────────
def test_backfill_writes_a_late_capture_row_with_a_rolled_back_cutoff(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    full = _archive(D2)
    install(monkeypatch, P, upto(full, D0))
    first = P.publish_latest_timeseries_v14(root, now=now_after(D0))
    assert first["status"] == "live" and first["backfilled"] == [] and first["unfillable"] == []
    assert _pointer(root)["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    # D1 발행이 빠졌다 — D2 자료까지 한꺼번에 들어온 뒤의 발행이 D1 을 late_capture 로 채운다
    install(monkeypatch, P, full)
    second = P.publish_latest_timeseries_v14(root, now=now_after(D2))
    assert second["status"] == "live" and second["as_of"] == D2 and second["backfilled"] == [D1]
    assert second["late_capture_rows_total"] == 1
    normal_d0, late, normal_d2 = _rows(root)
    assert [normal_d0["as_of"], late["as_of"], normal_d2["as_of"]] == [D0, D1, D2]
    assert "pit_grade" not in normal_d0 and "pit_grade" not in normal_d2
    assert late["pit_grade"] == "late_capture" and late["backfill_cutoff_used"] == stamp_after(D1)
    assert late["late_capture_sessions"] == 1 and late["captured_by_run"] == normal_d2["run_id"]
    assert late["backfill_cutoff_used"] <= late["knowledge_cutoff"] == normal_d2["knowledge_cutoff"]
    assert late["pointer_content_hash"] == _pointer(root)["content_hash"]
    assert {k: v["role"] for k, v in late["cells"].items()} == roles_for(CHAMPION)
    assert C.canonical_hash({k: v for k, v in late.items() if k != "content_hash"}) == late["content_hash"]
    # 포인터는 현재 as_of 하나만 · backfill 블록은 재유도 가능한 것만
    assert _pointer(root)["as_of"] == D2
    assert _pointer(root)["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    # 되감은 cutoff 의 p == 제때 발행했을 때의 p
    timely_root = make_repo(tmp_path, name="timely")
    install(monkeypatch, P, upto(full, D1))
    assert P.publish_latest_timeseries_v14(timely_root, now=now_after(D1))["status"] == "live"
    timely = _rows(timely_root)[-1]
    assert {k: v["p"] for k, v in late["cells"].items()} == {k: v["p"] for k, v in timely["cells"].items()}
    assert late["inputs"] == timely["inputs"]
    # 멱등 · verify
    install(monkeypatch, P, full)
    again = P.publish_latest_timeseries_v14(root, now=now_after(D2) + timedelta(hours=1))
    assert again["backfilled"] == [] and again["ledger_appended"] is False and len(_rows(root)) == 3
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]
    # 행을 지우면 완전성 규칙에 걸린다(선택 백필 차단)
    write_jsonl(root / C.LIVE_LEDGER_RELATIVE, [normal_d0, normal_d2])
    assert P.verify_timeseries_v14(root)["errors"] == [f"backfill incomplete: {D1}"]


def test_backfill_gap_is_an_origin_with_no_row_under_any_sha(tmp_path: Path, monkeypatch) -> None:
    """재동결 전 sha 의 행이 있는 원점은 결손이 아니다(forward_only) — 새 계수로 다시 채점하지 않는다."""
    root = make_repo(tmp_path)
    full = _archive(D2)
    install(monkeypatch, P, upto(full, D1))
    P.publish_latest_timeseries_v14(root, now=now_after(D1))         # D0 백필 + D1 정상 (옛 sha)
    assert [r["as_of"] for r in _rows(root)] == [D0, D1]
    sha, content_hash = install_frozen(root, roles_for(CHAMPION), tweak=0.5)
    write_contract(root, champion=CHAMPION, sha=sha, content_hash=content_hash)
    install(monkeypatch, P, full)
    result = P.publish_latest_timeseries_v14(root, now=now_after(D2))
    assert result["backfilled"] == [] and [r["as_of"] for r in _rows(root)] == [D0, D1, D2]
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]


# ── PIT (V13 백필·라이브 PIT 테스트 이식) — 픽스처 reader 는 available_at <= cutoff · max revision dedupe ─────
def _p_map(row: dict) -> dict:
    return {name: cell["p"] for name, cell in row["cells"].items()}


def _timely(tmp_path: Path, monkeypatch, archive: list, day: str, *, tag: str = "") -> dict:
    """같은 아카이브를 제때(다음날 05:00Z) 발행했을 때의 정상 행 — 백필·지연 행의 대조군."""
    root = make_repo(tmp_path, name=f"timely-{day}{tag}")
    install(monkeypatch, P, upto(archive, day))
    assert P.publish_latest_timeseries_v14(root, now=now_after(day))["status"] == "live"
    return _rows(root)[-1]


def test_nasdaqcom_revision_after_first_capture_does_not_change_the_late_capture_p(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    full = _archive(D2)
    install(monkeypatch, P, upto(full, D0))
    assert P.publish_latest_timeseries_v14(root, now=now_after(D0))["status"] == "live"
    # D1 NASDAQCOM 개정: 첫 수집(D1 다음날 01:50Z) 뒤 10-25T12:00Z 에 +3% 값(revision_seq=2)
    original = next(o for o in full if o.series_id == "NASDAQCOM" and o.observation_time == D1)
    revised = Obs("NASDAQCOM", D1, original.value * 1.03, available_at="2026-10-25T12:00:00+00:00", revision_seq=2)
    install(monkeypatch, P, full + [revised])
    result = P.publish_latest_timeseries_v14(root, now=now_after(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1]
    late = _rows(root)[1]
    assert late["as_of"] == D1 and late["pit_grade"] == "late_capture"
    assert late["backfill_cutoff_used"] == stamp_after(D1), "cutoff 는 첫 vintage 의 available_at — 개정의 것이 아니다"
    timely = _timely(tmp_path, monkeypatch, full, D1)
    assert _p_map(late) == _p_map(timely) and late["inputs"] == timely["inputs"]
    # 개정을 포함한 패널이었다면 RV 입력·crv p 가 달라진다 — 되감기가 실제로 개정을 배제했음을 보인다
    revised_panel = F.build_panel(reader(full + [revised])(root, knowledge_cutoff=late["knowledge_cutoff"]),
                                  start=C.LIVE_PANEL_START, end=D1)
    assert str(revised_panel["dates"][-1]) == D1
    frozen = json.loads((root / C.COEFFICIENTS_RELATIVE).read_text(encoding="utf-8"))
    revised_cells, revised_inputs = P.compute_cells(frozen, revised_panel, roles_for(CHAMPION))
    assert revised_inputs["rv21_ann"] != late["inputs"]["rv21_ann"]
    assert revised_cells["crv_h5"]["p"] is not None and revised_cells["crv_h5"]["p"] != late["cells"]["crv_h5"]["p"]
    install(monkeypatch, P, full + [revised])
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]


def test_batch_captured_origin_is_backfilled_with_the_panel_truncated_at_the_origin(tmp_path: Path, monkeypatch) -> None:
    """D1·D2 가 한 영수증(같은 available_at)으로 들어와도 D1 은 end=origin 절단으로 채운다 — as_of_drift 가 아니다."""
    root = make_repo(tmp_path)
    full = _archive(D2)
    install(monkeypatch, P, upto(full, D0))
    assert P.publish_latest_timeseries_v14(root, now=now_after(D0))["status"] == "live"
    one_receipt = replace(replace(full, "VIX", D1, available_at=stamp_after(D2)),
                          "NASDAQCOM", D1, available_at=stamp_after(D2))
    install(monkeypatch, P, one_receipt)
    result = P.publish_latest_timeseries_v14(root, now=now_after(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1] and result["unfillable"] == []
    late = _rows(root)[1]
    assert late["as_of"] == D1 and late["pit_grade"] == "late_capture"
    assert late["backfill_cutoff_used"] == stamp_after(D2), "cutoff 는 영수증 시각 — D2 세션도 그 안에 있다"
    # 되감은 cutoff 의 절단 전 패널은 D2 에서 끝난다 — 절단이 없었다면 as_of_drift 로 영구 결손이었다
    untruncated = F.build_panel(reader(one_receipt)(root, knowledge_cutoff=late["backfill_cutoff_used"]),
                                start=C.LIVE_PANEL_START)
    assert str(untruncated["dates"][-1]) == D2
    timely = _timely(tmp_path, monkeypatch, full, D1)
    assert _p_map(late) == _p_map(timely) and late["inputs"] == timely["inputs"]
    install(monkeypatch, P, one_receipt)
    verify = P.verify_timeseries_v14(root)
    assert verify["ok"] is True, verify["errors"]
    assert verify["unfillable_disclosed"] == []


def test_a_session_stamped_after_now_is_invisible_to_the_publish(tmp_path: Path, monkeypatch) -> None:
    """D1 관측이 발행 시각 뒤에 스탬프돼 있으면 as_of 는 D0 에 머문다(available_at <= now)."""
    root = make_repo(tmp_path)
    full = _archive(D1)
    stamp = datetime.fromisoformat(stamp_after(D1))
    install(monkeypatch, P, full)
    early = P.publish_latest_timeseries_v14(root, now=stamp - timedelta(minutes=1))
    assert early["status"] == "live" and early["as_of"] == D0
    assert _pointer(root)["as_of"] == D0 and [r["as_of"] for r in _rows(root)] == [D0]
    timely = _timely(tmp_path, monkeypatch, full, D0)
    assert _p_map(_rows(root)[0]) == _p_map(timely) and _rows(root)[0]["inputs"] == timely["inputs"]
    install(monkeypatch, P, full)
    assert P.verify_timeseries_v14(root)["ok"] is True
    # 스탬프 시각이 되면 D1 이 보인다
    on_time = P.publish_latest_timeseries_v14(root, now=stamp)
    assert on_time["as_of"] == D1 and [r["as_of"] for r in _rows(root)] == [D0, D1]


def test_resolve_keeps_a_label_session_stamped_after_now_pending(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    last = "2026-10-29"                          # D0 + 5 세션(10-23·10-26·10-27·10-28·10-29) — h5 성숙 세션
    days = sessions(last, 160)
    assert days.index(D0) + 5 == len(days) - 1
    vix, ndx = quiet_paths(160)
    vix[-1] = 27.0                               # h5 창의 마지막 세션이 25 를 터치 → cvix25_h5 라벨 1
    full = observations(days, vix, ndx)
    install(monkeypatch, P, upto(full, D0))
    assert P.publish_latest_timeseries_v14(root, now=now_after(D0))["status"] == "live"
    install(monkeypatch, P, full)
    stamp = datetime.fromisoformat(stamp_after(last))
    early = R.resolve_live_timeseries_v14(root, now=stamp - timedelta(minutes=1))
    assert early["resolved"] == 0 and early["pending"] == 6, "스탬프 전에는 성숙 세션을 모른다"
    assert not read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    on_time = R.resolve_live_timeseries_v14(root, now=stamp)
    rows = read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    assert on_time["resolved"] == 2 and {r["cell"]: r["label"] for r in rows} == {"cvix25_h5": 1.0, "crv_h5": 0.0}
    assert all(r["resolved_session"] == last and r["knowledge_cutoff"] == stamp.isoformat(timespec="seconds")
               for r in rows)
    verify = R.verify_live_resolutions(root)
    assert verify["ok"] is True, verify["errors"]


def test_pointer_changed_ignores_a_clock_only_rewrite(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    install(monkeypatch, P, _archive(D0))
    P.publish_latest_timeseries_v14(root, now=now_after(D0))
    head = (root / C.LATEST_RELATIVE).read_bytes()
    P.publish_latest_timeseries_v14(root, now=now_after(D0) + timedelta(hours=3))
    assert (root / C.LATEST_RELATIVE).read_bytes() != head, "시계는 움직였다"

    def fake_git(args, **kwargs):                    # HEAD 포인터 흉내 — 실제 git 은 부르지 않는다
        assert args[:2] == ["git", "show"] and args[2] == "HEAD:" + C.LATEST_RELATIVE.as_posix()
        return subprocess.CompletedProcess(args, 0, stdout=head, stderr=b"")

    monkeypatch.setattr(P.subprocess, "run", fake_git)
    assert P.v14_pointer_changed(root) is False
    install(monkeypatch, P, _archive(D0, last_vix=21.0))
    P.publish_latest_timeseries_v14(root, now=now_after(D0) + timedelta(hours=4))
    assert P.v14_pointer_changed(root) is True       # 입력·조건 충족이 바뀌면 커밋 대상


# ── 채점 ────────────────────────────────────────────────────────────────────
def _resolve_world(tmp_path: Path):
    """N=120 세션 아카이브. o1=N-40 · o2=N-30 · o3=N-8.

    VIX: 평온(<20), N-37 하루 27 → cvix: o1 h5·h21 = 1 · o2 h5·h21 = 0 · o3 h5 = 0.
    RV : N-28 에 6% 로그수익 → RV21 > θ 가 N-28..N-8 → crv: o1 h5 = 0·h21 = 1 · o2 h5·h21 = 1 · o3 는 조건 불충족(RV21_t > θ).
    """
    n = 120
    days = sessions(D3, n)
    vix, ndx = quiet_paths(n, seed=3)
    vix[n - 37] = 27.0
    returns = np.diff(np.log(ndx), prepend=np.log(ndx[0]))
    returns[n - 28] = 0.06
    ndx = 10000.0 * np.exp(np.cumsum(returns))
    root = make_repo(tmp_path)
    sha = C.load_contract_v14(root)["frozen_coefficients"]["sha256"]
    roles = roles_for(CHAMPION)
    panel = F.build_panel(observations(days, vix, ndx), start=days[0])
    assert panel["rv21"][n - 30] <= C.THETA < panel["rv21"][n - 8], "합성 경로가 의도한 조건을 만든다"
    live = []
    for k, idx in enumerate((n - 40, n - 30, n - 8)):
        cells = {}
        for spec in C.cell_specs():
            met = bool(P.condition_mask(spec, panel["vix"][idx:idx + 1], panel["rv21"][idx:idx + 1])[0])
            cells[spec["name"]] = {"condition_met": met, "p": 0.3 if met else None, "level": 1.0,
                                   "role": roles[spec["name"]], "clim_base_rate": 0.2}
        body = {"schema_version": 1, "run_id": f"v14cond-{days[idx]}-{sha[:8]}", "as_of": days[idx],
                "knowledge_cutoff": now_after(days[idx]).isoformat(), "coefficients_sha256": sha, "cells": cells}
        body["content_hash"] = C.canonical_hash(body)
        live.append(body)
    write_jsonl(root / C.LIVE_LEDGER_RELATIVE, live)
    return root, observations(days, vix, ndx), days


def test_resolve_scores_only_matured_condition_met_origins_with_correct_labels(tmp_path: Path, monkeypatch) -> None:
    root, archive, days = _resolve_world(tmp_path)
    install(monkeypatch, P, archive)
    result = R.resolve_live_timeseries_v14(root, now=now_after(D3))
    n = 120
    o1, o2, o3 = days[n - 40], days[n - 30], days[n - 8]
    got = {(r["origin"], r["cell"]): r["label"] for r in read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)}
    assert got == {
        (o1, "cvix25_h5"): 1.0, (o1, "cvix25_h21"): 1.0, (o1, "crv_h5"): 0.0, (o1, "crv_h21"): 1.0,
        (o2, "cvix25_h5"): 0.0, (o2, "cvix25_h21"): 0.0, (o2, "crv_h5"): 1.0, (o2, "crv_h21"): 1.0,
        (o3, "cvix25_h5"): 0.0,
    }
    # h63 4건 + o3 cvix h21·h63 2건 = 미성숙 6 · o3 crv 3셀 = 조건 불충족(표본 아님)
    assert result["resolved"] == 9 and result["pending"] == 6 and result["not_condition_met"] == 3
    assert result["matured_by_cell"]["crv_h5"] == 2 and result["matured_by_cell"]["crv_h63"] == 0
    rows = read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    for row in rows:
        assert row["role"] == ("champion" if row["cell"] in CHAMPION else "shadow")
        assert row["resolution_id"] == f"{row['run_id']}-{row['cell']}"
        assert row["climatology_base_rate"] == 0.2 and row["probability"] == 0.3
        assert row["brier_model"] == round((0.3 - row["label"]) ** 2, 8)
        assert row["brier_climatology"] == round((0.2 - row["label"]) ** 2, 8)
        assert row["resolved_session"] == days[days.index(row["origin"]) + row["horizon_sessions"]]
    assert R.verify_live_resolutions(root)["ok"] is True
    # 멱등 — 재실행은 0행
    again = R.resolve_live_timeseries_v14(root, now=now_after(D3) + timedelta(hours=1))
    assert again["resolved"] == 0 and len(read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)) == 9


def test_verify_rejects_a_resolution_of_a_condition_not_met_origin(tmp_path: Path, monkeypatch) -> None:
    root, archive, days = _resolve_world(tmp_path)
    install(monkeypatch, P, archive)
    R.resolve_live_timeseries_v14(root, now=now_after(D3))
    rows = read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    live = read_jsonl(root / C.LIVE_LEDGER_RELATIVE)
    o3_run = live[2]["run_id"]
    forged = {"schema_version": 1, "resolution_id": f"{o3_run}-crv_h5", "run_id": o3_run, "cell": "crv_h5",
              "origin": live[2]["as_of"], "role": "champion", "target": "rv_conditional", "horizon_sessions": 5,
              "resolved_session": days[-3], "probability": 0.3, "label": 1.0, "climatology_base_rate": 0.2,
              "brier_model": 0.49, "brier_climatology": 0.64, "coefficients_sha256": live[2]["coefficients_sha256"],
              "knowledge_cutoff": "2026-10-28T05:00:00+00:00"}
    forged["content_hash"] = C.canonical_hash(forged)
    write_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE, rows + [forged])
    verify = R.verify_live_resolutions(root)
    key = f"{o3_run}-crv_h5"
    assert f"resolution scored a condition-not-met origin: {key}" in verify["errors"]
    # 위조 행만 걸린다(아카이브 재계산 라벨이 1.0 과 다르면 그 오류도 같은 키로 함께 공시된다) — 정상 9행은 무오류
    assert verify["ok"] is False and all(e.endswith(key) for e in verify["errors"]), verify["errors"]


def _retouch(row: dict, **changes) -> dict:
    """해상 행 변조 흉내 — content_hash 를 다시 맞춰 해시 검사는 통과시키고 재계산 규칙만 시험한다."""
    body = {k: v for k, v in row.items() if k != "content_hash"}
    body.update(changes)
    body["content_hash"] = C.canonical_hash(body)
    return body


@pytest.mark.parametrize("tamper", ["label", "early_resolved_session", "coefficients_sha256", "brier_climatology",
                                    "horizon"])
def test_verify_recomputes_resolutions_from_the_archive(tmp_path: Path, monkeypatch, tamper: str) -> None:
    root, archive, days = _resolve_world(tmp_path)
    install(monkeypatch, P, archive)
    R.resolve_live_timeseries_v14(root, now=now_after(D3))
    rows = read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    assert R.verify_live_resolutions(root)["ok"] is True
    n = 120
    target = next(i for i, r in enumerate(rows) if r["origin"] == days[n - 40] and r["cell"] == "cvix25_h5")
    row = rows[target]
    key = row["resolution_id"]
    assert row["label"] == 1.0 and row["resolved_session"] == days[n - 40 + 5]
    if tamper == "label":                        # 라벨을 뒤집고 Brier 두 값을 그 라벨에 맞춘다 — 남는 단서는 아카이브뿐
        flipped = 0.0
        rows[target] = _retouch(row, label=flipped, brier_model=round((0.3 - flipped) ** 2, 8),
                                brier_climatology=round((0.2 - flipped) ** 2, 8))
        expected = f"label differs from the archive recompute (1.0): {key}"
    elif tamper == "early_resolved_session":     # 원점 + h − 1 세션에 해소했다고 적는다
        rows[target] = _retouch(row, resolved_session=days[n - 40 + 4])
        expected = f"resolved_session differs from dates[idx(origin)+h] = {days[n - 40 + 5]}: {key}"
    elif tamper == "coefficients_sha256":
        rows[target] = _retouch(row, coefficients_sha256="f" * 64)
        expected = f"resolution coefficients_sha256 differs from its live ledger row: {key}"
    elif tamper == "brier_climatology":
        rows[target] = _retouch(row, brier_climatology=round(row["brier_climatology"] + 0.01, 8))
        expected = f"brier_climatology inconsistent: {key}"
    else:
        rows[target] = _retouch(row, horizon_sessions=21)
        expected = f"resolution horizon/target differ from the cell spec: {key}"
    write_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE, rows)
    verify = R.verify_live_resolutions(root)
    assert verify["errors"] == [expected]


def test_publish_then_resolve_end_to_end(tmp_path: Path, monkeypatch) -> None:
    root = make_repo(tmp_path)
    later = "2026-11-03"                          # D0 뒤 8 세션 — h5 만 성숙
    days = sessions(later, 175)
    vix, ndx = quiet_paths(175)
    full = observations(days, vix, ndx)
    install(monkeypatch, P, upto(full, D0))
    assert P.publish_latest_timeseries_v14(root, now=now_after(D0))["status"] == "live"
    install(monkeypatch, P, upto(full, D3))       # D0 뒤 세 세션뿐 — h5 도 아직 미성숙
    early = R.resolve_live_timeseries_v14(root, now=now_after(D3))
    assert early["resolved"] == 0 and early["pending"] == 6 and early["not_condition_met"] == 0
    install(monkeypatch, P, full)
    result = R.resolve_live_timeseries_v14(root, now=now_after(later))
    rows = read_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE)
    # 원점 D0 의 h5 2셀만 성숙(조건 충족 6셀 중) — 평온 경로라 라벨 0
    assert result["resolved"] == 2 and {r["cell"] for r in rows} == {"cvix25_h5", "crv_h5"}
    assert all(r["label"] == 0.0 and r["origin"] == D0 for r in rows)
    assert R.verify_live_resolutions(root)["ok"] is True


# ── CLI · 워크플로 ───────────────────────────────────────────────────────────
def test_cli_registers_the_four_v14_verbs() -> None:
    from ai_fc.cli import app

    names = {command.name for command in app.registered_commands}
    assert {"timeseries-v14-cond-latest", "timeseries-v14-cond-resolve", "timeseries-v14-cond-verify",
            "timeseries-v14-cond-live-verdict"} <= names


WORKFLOW_V14 = ROOT / ".github/workflows/timeseries-v14-cond-live.yml"
WORKFLOW_V13 = ROOT / ".github/workflows/timeseries-v13-vol-live.yml"


def _job_if(expression: str, event: str, *, conclusion: str = "success", branch: str = "main") -> bool:
    """잡 `if` 식을 test_timeseries_inputs_workflow._concurrency_group 과 같은 방식(같은 문맥 객체)으로 평가한다."""
    from test_timeseries_inputs_workflow import _ExpressionContext

    body = expression.strip().removeprefix("${{").removesuffix("}}").strip()
    body = body.replace("&&", " and ").replace("||", " or ")
    context = _ExpressionContext(event_name=event, event={"workflow_run": {"head_branch": branch,
                                                                         "conclusion": conclusion}})
    return bool(eval(body, {"__builtins__": {}}, {"github": context}))


def test_v14_is_its_own_workflow_and_v13_no_longer_carries_it() -> None:
    """V14 실패가 timeseries-v13-vol-live 를 빨갛게 만들면 pages·verify(conclusion == 'success')가 V13 배포·검증을 건너뛴다."""
    v13 = WORKFLOW_V13.read_text(encoding="utf-8")
    assert "timeseries-v14" not in v13 and "v14" not in v13
    assert list(yaml.safe_load(v13)["jobs"]) == ["live"]
    doc = yaml.safe_load(WORKFLOW_V14.read_text(encoding="utf-8"))
    assert doc["name"] == "timeseries-v14-cond-live"
    on = doc.get(True) or doc.get("on")
    assert on["workflow_run"] == {"workflows": ["timeseries-v13-vol-live"], "types": ["completed"]}
    assert "workflow_dispatch" in on and len(on["schedule"]) == 2
    assert doc["permissions"] == {"contents": "write"}, "배포 디스패치가 없으므로 actions 권한이 없다"
    assert list(doc["jobs"]) == ["live"]
    # 감시는 ops-failure-alert 가 V14 이름으로 · 배포는 없다(t0 내부)
    alert = yaml.safe_load((ROOT / ".github/workflows/ops-failure-alert.yml").read_text(encoding="utf-8"))
    assert "timeseries-v14-cond-live" in (alert.get(True) or alert.get("on"))["workflow_run"]["workflows"]
    for name in ("pages.yml", "verify.yml"):
        assert "timeseries-v14" not in (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def test_v14_workflow_runs_after_a_failed_v13_but_not_after_cancel_or_off_main() -> None:
    from test_timeseries_inputs_workflow import _concurrency_group

    doc = yaml.safe_load(WORKFLOW_V14.read_text(encoding="utf-8"))
    guard = doc["jobs"]["live"]["if"]
    assert "always()" not in guard
    assert _job_if(guard, "workflow_run", conclusion="success") is True
    assert _job_if(guard, "workflow_run", conclusion="failure") is True, "V13 장애가 V14 축적을 막지 않는다"
    assert _job_if(guard, "workflow_run", conclusion="cancelled") is False
    assert _job_if(guard, "workflow_run", branch="feature") is False
    assert _job_if(guard, "schedule") is True and _job_if(guard, "workflow_dispatch") is True
    name = WORKFLOW_V14.name
    assert doc["concurrency"]["cancel-in-progress"] is False
    for event in ("schedule", "workflow_dispatch"):
        assert _concurrency_group(name, event) == "investing-data-writer-v14"
    assert _concurrency_group(name, "workflow_run", conclusion="failure") == "investing-data-writer-v14"
    assert _concurrency_group(name, "workflow_run", conclusion="cancelled") == "v14-skipped-42"
    assert _concurrency_group(name, "workflow_run", branch="feature") == "v14-skipped-42"


def test_workflow_publishes_resolves_verifies_and_commits_only_v14_live_paths() -> None:
    doc = yaml.safe_load(WORKFLOW_V14.read_text(encoding="utf-8"))
    job = doc["jobs"]["live"]
    assert job["steps"][0]["with"] == {"ref": "main", "fetch-depth": 0}
    runs = [step.get("run", "") for step in job["steps"]]
    joined = "\n".join(runs)
    order = [next(i for i, r in enumerate(runs) if needle in r) for needle in (
        'pip install -e ".[pit,timeseries]" pytest', "timeseries-v14-cond-latest", "timeseries-v14-cond-resolve",
        "timeseries-v14-cond-verify", "git commit")]
    assert order == sorted(order)
    assert "test_timeseries_v14_live.py" in joined and "test_timeseries_v14_live_verdict.py" in joined
    assert "live-verdict" not in joined, "판정 산술은 사람이 돌린다 — 자동화 밖"
    assert "pages.yml" not in joined, "t0 내부 — 배포 없음"
    assert "timeseries-v13" not in joined, "V13 verb 는 V13 워크플로만 돌린다"
    commit = next(step for step in job["steps"] if step.get("id") == "commit")
    allow = next(line for line in commit["run"].splitlines() if line.strip().startswith("allow="))
    paths = allow.split("=", 1)[1].strip().strip('"').split()
    assert paths == [C.LATEST_RELATIVE.as_posix(), C.LIVE_LEDGER_RELATIVE.as_posix(),
                     C.RESOLUTION_LEDGER_RELATIVE.as_posix(), "docs/generated/inventory.generated.md"]
    guard = ("grep -Ev '^(data/timeseries_v14/(live/v14_latest\\.json|ledgers/v14_live(_resolutions)?\\.jsonl)"
             "|docs/generated/inventory\\.generated\\.md)$'")
    assert guard in commit["run"]
    assert "timeseries_v13" not in commit["run"] and "champion_coefficients" not in commit["run"]
    assert "data/contracts" not in commit["run"]
    assert 'if [ -f "$f" ]; then git add "$f"; fi' in commit["run"] and '"$pointer_changed" = false' in commit["run"]
    assert commit["run"].index("pull --rebase") < commit["run"].index("git push")
    # 푸시 경합 재시도 — 매 시도 전에 새 끝으로 재생, 3회 실패면 잡 실패(조용히 버리지 않는다)
    assert "for attempt in 1 2 3; do" in commit["run"]
    loop = commit["run"][commit["run"].index("for attempt in 1 2 3; do"):]
    assert loop.index("git pull --rebase origin main") < loop.index("if git push; then pushed=true; break; fi")
    assert 'test "$pushed" = true || { echo "push failed after 3 attempts"; exit 1; }' in commit["run"]
    assert commit["run"].index('test "$pushed" = true') < commit["run"].index('echo "committed=true"')


def test_v14_commit_step_shell_runs_end_to_end_with_a_push_race(tmp_path: Path) -> None:
    """커밋 단계 셸을 그대로 실행한다(가짜 git·python — 네트워크·실저장소 없음): 허용 경로만 add, 첫 푸시 거절 뒤 재생·재시도."""
    import shutil

    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    doc = yaml.safe_load(WORKFLOW_V14.read_text(encoding="utf-8"))
    run = next(step for step in doc["jobs"]["live"]["steps"] if step.get("id") == "commit")["run"]
    for rel in (C.LATEST_RELATIVE, C.LIVE_LEDGER_RELATIVE, Path("docs/generated/inventory.generated.md")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x\n", encoding="utf-8")     # 해상 원장은 없다 — [ -f ] 가드가 건너뛰어야 한다
    stub = (
        'calls="$PWD/calls"\n'
        'python(){ echo "python $*" >> "$calls"; case "$*" in *v14_pointer_changed*) echo true;; esac; }\n'
        'sleep(){ :; }\n'
        'git(){ echo "git $*" >> "$calls"\n'
        '  case "$1" in\n'
        '    diff) if [ "$2" = "--cached" ] && [ "$3" = "--name-only" ]; then cat staged 2>/dev/null; return 0; fi\n'
        '          [ -s staged ] && return 1; return 0;;\n'
        '    add) echo "$2" >> staged;;\n'
        '    push) n=$(cat pushes 2>/dev/null || echo 0); n=$((n+1)); echo $n > pushes; [ $n -ge 2 ];;\n'
        '  esac; }\n'
    )
    script = tmp_path / "commit.sh"
    script.write_text("set -eo pipefail\nGITHUB_OUTPUT=\"$PWD/out\"\n" + stub + run, encoding="utf-8", newline="\n")
    result = subprocess.run([bash, str(script)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    added = [c.split(" ", 2)[2] for c in calls if c.startswith("git add ")]
    assert added == [C.LATEST_RELATIVE.as_posix(), C.LIVE_LEDGER_RELATIVE.as_posix(),
                     "docs/generated/inventory.generated.md"]
    assert [c for c in calls if c.startswith(("git pull", "git push"))] == [
        "git pull --rebase origin main", "git push", "git pull --rebase origin main", "git push"]
    assert (tmp_path / "out").read_text(encoding="utf-8").splitlines() == ["committed=false", "committed=true"]
