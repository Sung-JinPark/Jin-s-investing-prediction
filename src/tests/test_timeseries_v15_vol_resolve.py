"""V15-VOL 해소 조인·XNAS 가드 (명세 U5 §8.4) — tmp_path 사본. 실저장소는 읽기만."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.timeseries_v15_vol import contracts as C
from ai_fc.timeseries_v15_vol import resolve as R
from ai_fc.timeseries_v15_vol import shadow as SH
from v15_vol_fixtures import (ROOT, V13_LIVE, V13_RES, V15_RES, V15_SHADOW, arm, make_root, protected_hashes,
                              read_jsonl, write_arming, write_jsonl)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(C.ARMING_ENV, raising=False)
    before = protected_hashes()
    yield
    assert protected_hashes() == before, "실저장소 V13/V15 파일이 바뀌었다"


def _rehash(row: dict) -> dict:
    body = {k: v for k, v in row.items() if k != "content_hash"}
    row["content_hash"] = C.canonical_hash(body)
    return row


def _live(tmp_path: Path, effective_from: str = "2026-10-01") -> Path:
    root = make_root(tmp_path)
    arm(root)
    write_arming(root, effective_from=effective_from)
    assert SH.publish_shadow_v15_vol(root, now=NOW)["status"] == "live"
    return root


def _add_v13_origin(root: Path, as_of: str) -> dict:
    rows = read_jsonl(root / V13_LIVE)
    new = copy.deepcopy(rows[-1])
    sha = new["coefficients_sha256"]
    new.update({"as_of": as_of, "run_id": f"v13vol-{as_of}-{sha[:8]}"})
    new.pop("pit_grade", None)
    write_jsonl(root / V13_LIVE, rows + [_rehash(new)])
    return new


def _add_v13_resolution(root: Path, run_id: str, cell: str, *, origin: str, resolved: str, label: float,
                        h: int) -> dict:
    rows = read_jsonl(root / V13_RES)
    row = _rehash({"schema_version": 1, "resolution_id": f"{run_id}-{cell}", "run_id": run_id, "cell": cell,
                   "origin": origin, "horizon_sessions": h, "resolved_session": resolved, "probability": 0.1,
                   "label": label, "knowledge_cutoff": "2026-12-01T00:00:00+00:00"})
    write_jsonl(root / V13_RES, rows + [row])
    return row


def test_join_scores_and_copies_v13_label(tmp_path: Path) -> None:
    root = _live(tmp_path)
    result = R.resolve_shadow_v15_vol(root, now=NOW)
    assert result["status"] == "live" and result["resolved"] > 0
    v13 = {r["resolution_id"]: r for r in read_jsonl(root / V13_RES)}
    rows = read_jsonl(root / V15_RES)
    for row in rows:
        source = v13[row["v13_resolution_id"]]
        assert row["label"] == source["label"] and row["resolved_session"] == source["resolved_session"]
        if row["scored"]:
            y = row["label"]
            for key, p in row["probabilities"].items():
                assert row["brier"][key] == pytest.approx((p - y) ** 2, abs=1e-15)
    report = R.verify_shadow_resolutions_v15_vol(root)
    assert report["ok"], report["errors"][:5]
    again = R.resolve_shadow_v15_vol(root, now=NOW)
    assert again["resolved"] == 0 and again["held"] == 0


def test_xnas_mismatch_is_held(tmp_path: Path) -> None:
    root = _live(tmp_path)
    shadow = read_jsonl(root / V15_SHADOW)
    first = shadow[0]
    key = f"{first['v13_run_id']}-vix25_h5"
    rows = read_jsonl(root / V13_RES)
    for row in rows:
        if row["resolution_id"] == key:
            shifted = date.fromisoformat(row["resolved_session"]) + timedelta(days=1)
            row["resolved_session"] = shifted.isoformat()
            _rehash(row)
    write_jsonl(root / V13_RES, rows)
    R.resolve_shadow_v15_vol(root, now=NOW)
    held = next(r for r in read_jsonl(root / V15_RES) if r["resolution_id"] == f"{first['run_id']}-vix25_h5")
    assert held["scored"] is False and held["hold_reason"] == "xnas_session_mismatch"
    assert held["brier"] is None and held["log_score"] is None and held["xnas_match"] is False
    assert R.verify_shadow_resolutions_v15_vol(root)["ok"]


def test_origin_not_xnas_session(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    added = _add_v13_origin(root, "2026-11-26")             # 추수감사절 휴장(합성)
    _add_v13_resolution(root, added["run_id"], "vix25_h5", origin="2026-11-26", resolved="2026-12-03",
                        label=0.0, h=5)
    arm(root)
    write_arming(root, effective_from="2026-10-01")
    SH.publish_shadow_v15_vol(root, now=NOW)
    R.resolve_shadow_v15_vol(root, now=NOW)
    row = next(r for r in read_jsonl(root / V15_RES) if r["origin"] == "2026-11-26")
    assert row["scored"] is False and row["hold_reason"] == "origin_not_xnas_session"


def test_absent_v13_resolution_pending_then_held_then_immutable(tmp_path: Path) -> None:
    root = _live(tmp_path)
    shadow = {r["as_of"]: r for r in read_jsonl(root / V15_SHADOW)}
    target_row = shadow["2026-11-09"]
    rid = f"{target_row['run_id']}-vix25_h5"
    R.resolve_shadow_v15_vol(root, now=NOW)
    assert rid not in {r["resolution_id"] for r in read_jsonl(root / V15_RES)}          # pending
    target = R._xnas_session_offset(date(2026, 11, 9), 5)
    assert target == date(2026, 11, 16)
    grace_day = R._xnas_session_offset(target, 10)
    before_grace = datetime.combine(grace_day - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    R.resolve_shadow_v15_vol(root, now=before_grace)
    assert rid not in {r["resolution_id"] for r in read_jsonl(root / V15_RES)}
    later = datetime.combine(grace_day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12)
    result = R.resolve_shadow_v15_vol(root, now=later)
    assert result["held_v13_absent"] > 0
    held = next(r for r in read_jsonl(root / V15_RES) if r["resolution_id"] == rid)
    assert held["scored"] is False and held["hold_reason"] == "v13_resolution_absent" and held["label"] is None
    snapshot = (root / V15_RES).read_bytes()
    _add_v13_resolution(root, target_row["v13_run_id"], "vix25_h5", origin="2026-11-09", resolved="2026-11-16",
                        label=1.0, h=5)
    R.resolve_shadow_v15_vol(root, now=later)
    after = next(r for r in read_jsonl(root / V15_RES) if r["resolution_id"] == rid)
    assert after == held
    assert (root / V15_RES).read_bytes().startswith(snapshot)
    report = R.verify_shadow_resolutions_v15_vol(root)
    assert report["ok"], report["errors"][:5]
    assert report["late_v13_resolutions"] >= 1


def test_verify_detects_label_tamper(tmp_path: Path) -> None:
    root = _live(tmp_path)
    R.resolve_shadow_v15_vol(root, now=NOW)
    rows = read_jsonl(root / V15_RES)
    victim = next(r for r in rows if r["scored"])
    victim["label"] = 1.0 - victim["label"]
    _rehash(victim)
    write_jsonl(root / V15_RES, rows)
    report = R.verify_shadow_resolutions_v15_vol(root)
    assert not report["ok"] and any("label differs" in e for e in report["errors"])


def test_verify_recomputes_xnas_guard_on_scored_rows(tmp_path: Path) -> None:
    """B2: 가드를 통과하지 못했어야 할 행이 scored 로 들어오거나, 통과행이 보류로 숨겨지면 verify 실패(해시를 다시 맞춰도)."""
    root = _live(tmp_path)
    R.resolve_shadow_v15_vol(root, now=NOW)
    rows = read_jsonl(root / V15_RES)
    assert R.verify_shadow_resolutions_v15_vol(root)["ok"]
    victim = next(r for r in rows if r["scored"] and r["cell"] == "vix25_h5")
    v13 = read_jsonl(root / V13_RES)
    source = next(r for r in v13 if r["resolution_id"] == victim["v13_resolution_id"])
    source["resolved_session"] = (date.fromisoformat(source["resolved_session"]) + timedelta(days=1)).isoformat()
    _rehash(source)
    write_jsonl(root / V13_RES, v13)
    victim["resolved_session"] = source["resolved_session"]
    victim["v13_resolution_content_hash"] = source["content_hash"]
    _rehash(victim)
    write_jsonl(root / V15_RES, rows)
    report = R.verify_shadow_resolutions_v15_vol(root)
    assert not report["ok"]
    assert f"xnas guard recompute mismatch: {victim['resolution_id']}" in report["errors"]
    assert f"hold_reason recompute mismatch: {victim['resolution_id']}" in report["errors"]

    root2 = _live(tmp_path / "hide")
    R.resolve_shadow_v15_vol(root2, now=NOW)
    rows = read_jsonl(root2 / V15_RES)
    hidden = next(r for r in rows if r["scored"])
    hidden.update({"scored": False, "xnas_match": False, "hold_reason": "xnas_session_mismatch",
                   "brier": None, "log_score": None})
    _rehash(hidden)
    write_jsonl(root2 / V15_RES, rows)
    report = R.verify_shadow_resolutions_v15_vol(root2)
    assert f"xnas guard recompute mismatch: {hidden['resolution_id']}" in report["errors"]
    assert f"hold_reason recompute mismatch: {hidden['resolution_id']}" in report["errors"]


def test_unarmed_resolve_writes_nothing(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    result = R.resolve_shadow_v15_vol(root, now=NOW)
    assert result["status"] == "hold" and not (root / V15_RES).exists()


def test_real_v13_resolutions_pass_xnas_guard_snapshot() -> None:
    """고정 스냅샷: resolved_session ≤ 2026-11-10 인 V13 해상행 189개 전부가 V15 래퍼 가드를 통과한다(읽기 전용)."""
    rows = [r for r in read_jsonl(ROOT / V13_RES) if r["resolved_session"] <= "2026-11-10"]
    assert len(rows) == 189
    for row in rows:
        target = R._xnas_session_offset(date.fromisoformat(row["origin"]), int(row["horizon_sessions"]))
        assert target.isoformat() == row["resolved_session"], row["resolution_id"]
        assert R._is_xnas_session(date.fromisoformat(row["origin"]))


def test_wrapper_matches_research_sessions() -> None:
    """2026 세션 원점 전수 × h5/21/63 — 연구 계층 달력(future_sessions 1회 + session_offset 표본 실호출)과 일치(리뷰 N6)."""
    from ai_fc.mts_research.sessions import future_sessions, session_offset

    sessions = R._xnas_sessions(2025, 2027)
    origins = [d for d in sessions if date(2026, 1, 2) <= d <= date(2026, 12, 31)]
    assert len(origins) > 240
    # session_offset(o, k) == future_sessions(o, k)[k-1] 정의 → 첫 원점 앞 세션에서 한 번 뽑은 연속 세션 목록의 위치 산술과 같다.
    anchor = R._xnas_session_offset(origins[0], -1)
    research = future_sessions(anchor, len(origins) + 63)
    position = {d: i for i, d in enumerate(research)}
    for origin in origins:                              # 전수(약 250 × 3)
        for h in (5, 21, 63):
            assert R._xnas_session_offset(origin, h) == research[position[origin] + h], (origin, h)
    for origin in origins[::50]:                        # 실제 session_offset 호출 표본(호출당 약 0.15s)
        for h in (5, 21, 63):
            assert R._xnas_session_offset(origin, h) == session_offset(origin, h), (origin, h)
    # 음수 offset — 이전 세션
    assert R._xnas_session_offset(date(2026, 11, 27), -1) == date(2026, 11, 25)
    back = R._xnas_session_offset(date(2026, 11, 9), -20)
    assert R._xnas_session_offset(back, 20) == date(2026, 11, 9)
    assert R._xnas_session_offset(date(2026, 11, 14), 1) == date(2026, 11, 16)   # 토 → 월
