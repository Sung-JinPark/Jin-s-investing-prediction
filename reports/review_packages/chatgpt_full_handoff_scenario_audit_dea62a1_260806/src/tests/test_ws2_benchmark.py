"""WS2: 벤치마크 3자 원장 — 채점 정확성 · 룩어헤드 차단 · NULL 정직성 · E7."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

from ai_fc import files as F
from ai_fc.db import ingest
from ai_fc.resolver import _ml_ref_before, resolve_question

REG = """\
    version: 1
    questions:
      - id: fixture-eps-beat
        title: "픽스처 EPS beat"
        question: "픽스처사 2099-06-10 실적 EPS 컨센 상회 확률은?"
        deadline: 2099-06-10
        resolution: "YES = 발표 EPS > 컨센 스냅샷"
        resolution_source: "픽스처 IR"
        domain: earnings
        cadence: "r1"
        schedule:
          - once: true
        status: active
        created: 2026-07-01
"""


def _root(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir(parents=True)
    (tmp_path / "questions" / "registry.yaml").write_text(
        textwrap.dedent(REG), encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        ",".join(F.LEDGER_HEADER) + "\n", encoding="utf-8")
    (tmp_path / "forecasts").mkdir()
    return tmp_path


def test_benchmark_roundtrip_null_honesty(tmp_path: Path) -> None:
    p = tmp_path / "benchmark_ledger.csv"
    F.append_benchmark_row(p, {
        "resolved_date": "2099-06-11", "question_id": "q", "forecast_id": "f_r1",
        "llm_prob": 0.4, "llm_brier": 0.16,
        "ml_prob": None, "ml_brier": None,          # 부재는 NULL — 0으로 위장 금지
        "market_prob": 0.2, "market_brier": 0.04,
        "ml_asof": "", "market_asof": "2099-06-01", "notes": "",
    })
    rows = F.parse_benchmark_ledger(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["ml_prob"] is None and r["ml_brier"] is None
    assert r["market_prob"] == 0.2 and r["llm_brier"] == 0.16
    assert r["line_hash"]


def test_ml_ref_lookahead_blocked(tmp_path: Path) -> None:
    """예측 시점 이후 ML 값은 절대 사용 금지 — 이전 최신만."""
    conn = ingest.connect(tmp_path / "db" / "index.db")
    for ts, prob in [("2099-06-01T00:00:00", 0.30), ("2099-06-12T00:00:00", 0.90)]:
        conn.execute(
            "INSERT INTO ml_forecasts (run_ts, question_id, model, kind, prob)"
            " VALUES (?,?,?,?,?)", (ts, "fixture-eps-beat", "ensemble", "terminal", prob))
    conn.commit()

    ref = _ml_ref_before(conn, "fixture-eps-beat", "2099-06-10T09:00:00")
    assert ref is not None and ref[0] == 0.30 and ref[1].startswith("2099-06-01")

    # 예측 시점 이전 기록이 전무하면 None (소급 조회 금지)
    assert _ml_ref_before(conn, "fixture-eps-beat", "2099-05-01T00:00:00") is None
    assert _ml_ref_before(conn, "fixture-eps-beat", "") is None


def test_resolve_writes_benchmark_scores(tmp_path: Path) -> None:
    """해소 시 3자 병행 채점 — Brier 수치 정확성 + NULL 정직성."""
    root = _root(tmp_path)
    conn = ingest.connect(root / "db" / "index.db")
    conn.execute(
        """INSERT INTO forecasts (forecast_id, question_id, round, forecast_ts,
             probability, market_implied, path, file_sha256)
           VALUES ('2099-06-05_fixture-eps-beat_r1', 'fixture-eps-beat', 1,
                   '2099-06-05T09:00:00', 40, 0.2, 'x.md', 'h')""")
    conn.execute(
        "INSERT INTO ml_forecasts (run_ts, question_id, model, kind, prob)"
        " VALUES ('2099-06-01T00:00:00', 'fixture-eps-beat', 'ensemble', 'terminal', 0.3)")
    conn.commit()

    resolve_question(conn, root, "fixture-eps-beat", outcome="no",
                     forecast_id=None, evidence="픽스처 발표", assume_yes=True)

    rows = F.parse_benchmark_ledger(root / "calibration" / "benchmark_ledger.csv")
    assert len(rows) == 1
    r = rows[0]
    assert r["llm_prob"] == 0.4 and r["llm_brier"] == 0.16       # (0.4-0)²
    assert r["ml_prob"] == 0.3 and r["ml_brier"] == 0.09         # 룩어헤드 이전값
    assert r["market_prob"] == 0.2 and r["market_brier"] == 0.04
    assert r["ml_asof"].startswith("2099-06-01")

    # DB 뷰 반영 (sync는 resolve 내부에서 수행됨)
    pair = {p["pair"]: p for p in conn.execute("SELECT * FROM v_benchmark_pairwise")}
    assert pair["llm_vs_ml"]["n"] == 1 and pair["all_three"]["n"] == 1


def test_sync_e7_append_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    conn = ingest.connect(root / "db" / "index.db")
    p = root / "calibration" / "benchmark_ledger.csv"
    for fid in ("f_r1", "f_r2"):
        F.append_benchmark_row(p, {
            "resolved_date": "2099-06-11", "question_id": "q", "forecast_id": fid,
            "llm_prob": 0.5, "llm_brier": 0.25, "ml_prob": None, "ml_brier": None,
            "market_prob": None, "market_brier": None,
            "ml_asof": "", "market_asof": "", "notes": "",
        })
    report = ingest.sync(conn, root)
    assert report.ok

    # 행 축소 → E7
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    report = ingest.sync(conn, root)
    assert any("E7" in e and "축소" in e for e in report.errors)
