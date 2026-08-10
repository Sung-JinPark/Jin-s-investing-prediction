"""WS1: 등록 필터 · {from, once} 세그먼트 · resolve --draft 무기록 (합성 미래 질문만)."""

from __future__ import annotations

import textwrap
from datetime import date, datetime
from pathlib import Path

import pytest

from ai_fc.db import ingest
from ai_fc.registry import (active_interval_days, active_segment, compute_due,
                            factory_filter_violation, load_registry,
                            segment_activation_date)
from ai_fc.resolver import draft_verdicts, machine_check

NOW = datetime(2099, 6, 15, 9, 0)
TODAY = NOW.date()


def _registry(tmp_path: Path, yaml_text: str):
    d = tmp_path / "questions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "registry.yaml"
    p.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return load_registry(p)


FACTORY_Q = """\
    version: 1
    questions:
      - id: fixture-eps-beat
        title: "픽스처 EPS beat"
        question: "픽스처사가 2099-08-26 발표 실적에서 D-1 컨센 EPS를 상회할 확률은?"
        deadline: 2099-08-26
        resolution: "YES = 발표 EPS > D-1 컨센 스냅샷"
        resolution_source: "픽스처 IR"
        domain: earnings
        cadence: "r1 + D-3"
        schedule:
          - once: true
          - from: D-3
            once: true
        status: active
        created: 2099-06-01
        notes: "{notes}"
"""


def test_factory_filter_requires_marker(tmp_path: Path) -> None:
    q = _registry(tmp_path, FACTORY_Q.format(notes="근거 없음"))[0]
    v = factory_filter_violation(q)
    assert v is not None and "등록필터" in v

    q2 = _registry(tmp_path / "b",
                   FACTORY_Q.format(notes="등록필터: (a) beat율 ~78% — [35,65] 밖"))[0]
    assert factory_filter_violation(q2) is None


def test_factory_filter_grandfather(tmp_path: Path) -> None:
    """컷오프(2026-07-21) 이전 created는 필터 비대상."""
    y = FACTORY_Q.format(notes="근거 없음").replace("created: 2099-06-01",
                                                  "created: 2026-07-01")
    q = _registry(tmp_path, y)[0]
    assert factory_filter_violation(q) is None


def test_factory_filter_blocks_forecast_preflight(tmp_path: Path) -> None:
    from ai_fc.orchestrator import PreflightError, run_forecast

    _registry(tmp_path, FACTORY_Q.format(notes="근거 없음"))
    conn = ingest.connect(tmp_path / "db" / "index.db")
    with pytest.raises(PreflightError, match="등록필터"):
        run_forecast(conn, tmp_path, "fixture-eps-beat")


def test_once_from_segment_cadence(tmp_path: Path) -> None:
    """r1 1회 + D-3 재예측 1회 — 세그먼트 once 시맨틱 (D6)."""
    y = FACTORY_Q.format(notes="등록필터: (a) 근거").replace(
        "deadline: 2099-08-26", f"deadline: {TODAY.isoformat()}")
    # 기한 = 오늘 → D-3 세그먼트 활성 (컷오프 3일 전부터)
    qs = _registry(tmp_path, y)
    q = qs[0]
    seg = active_segment(q, TODAY)
    assert seg is not None and seg.get("once") and "from" in seg
    act = segment_activation_date(seg, q)
    assert act == TODAY.fromordinal(TODAY.toordinal() - 3)
    assert active_interval_days(q, TODAY) is None  # once → 간격 아님

    # 첫 예측 미실행 → forecast due
    due = compute_due(qs, {}, {}, set(), NOW)
    assert any(d.kind == "forecast" and "첫 예측" in d.reason for d in due)

    # 활성화(D-3) 이전 예측만 존재 → 세그먼트 재예측 due
    before = datetime(NOW.year, NOW.month, NOW.day - 5, 9, 0)
    due = compute_due(qs, {q.question_id: before}, {}, set(), NOW)
    assert any(d.kind == "forecast" and "세그먼트" in d.reason for d in due)

    # 활성화 이후 예측 존재 → forecast due 없음
    after = datetime(NOW.year, NOW.month, NOW.day - 1, 9, 0)
    due = compute_due(qs, {q.question_id: after}, {}, set(), NOW)
    assert not any(d.kind == "forecast" for d in due)


# ── machine_check / draft — 원장 무기록 계약 ─────────────────────

VIX_Q = """\
    version: 1
    questions:
      - id: vix-25-90d
        title: "90일 내 VIX 25 상회"
        question: "예측일로부터 90일 이내 VIX 종가 25 상회 확률은?"
        deadline: rolling-90d
        resolution: "YES = 윈도우 내 종가 > 25 존재"
        resolution_source: "CBOE 공식 종가"
        domain: volatility
        cadence: "주 2회"
        schedule:
          - per_week: 2
        status: active
        created: 2026-07-08
"""


def _fake_fetch(closes_by_symbol: dict):
    def fetch(symbol: str, start: date, end: date):
        dates_closes = closes_by_symbol.get(symbol, [])
        return ([d for d, _ in dates_closes], [c for _, c in dates_closes])
    return fetch


def test_machine_check_path_touch_and_no(tmp_path: Path) -> None:
    q = _registry(tmp_path, VIX_Q)[0]
    w0, w1 = date(2099, 3, 1), date(2099, 5, 30)

    touched = _fake_fetch({"^VIX": [(date(2099, 4, 1), 18.0), (date(2099, 4, 2), 26.5)]})
    v = machine_check(q, window_start=w0, window_end=w1, today=date(2099, 6, 1),
                      fetch=touched)
    assert v.outcome == "yes" and v.confidence == "high" and "26.5" in v.evidence_value

    calm = _fake_fetch({"^VIX": [(date(2099, 4, 1), 18.0), (date(2099, 5, 29), 19.2)]})
    v = machine_check(q, window_start=w0, window_end=w1, today=date(2099, 6, 1),
                      fetch=calm)
    assert v.outcome == "no" and v.confidence == "high"

    # 윈도우 진행 중 + 미터치 → 판정 불가 (outcome None)
    v = machine_check(q, window_start=w0, window_end=w1, today=date(2099, 5, 1),
                      fetch=calm)
    assert v.outcome is None and "진행 중" in v.note


def test_draft_writes_nothing(tmp_path: Path) -> None:
    """--draft 계약: 원장·벤치마크 파일 무기록 (확정 없이는 흔적 0)."""
    _registry(tmp_path, VIX_Q)
    conn = ingest.connect(tmp_path / "db" / "index.db")
    conn.execute(
        """INSERT INTO forecasts (forecast_id, question_id, round, forecast_ts,
             probability, window_end, path, file_sha256)
           VALUES ('2099-03-01_vix-25-90d_r1', 'vix-25-90d', 1,
                   '2099-03-01T09:00:00', 40, '2099-05-30', 'x.md', 'h')""")
    conn.commit()

    fetch = _fake_fetch({"^VIX": [(date(2099, 4, 1), 30.0)]})
    verdicts = draft_verdicts(conn, tmp_path, fetch=fetch, today=date(2099, 6, 1))
    assert len(verdicts) == 1
    assert verdicts[0].outcome == "yes"
    assert verdicts[0].forecast_id == "2099-03-01_vix-25-90d_r1"

    cal = tmp_path / "calibration"
    assert not (cal / "ledger.csv").exists()
    assert not (cal / "benchmark_ledger.csv").exists()
