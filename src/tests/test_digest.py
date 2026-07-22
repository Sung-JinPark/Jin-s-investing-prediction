"""P1.7-S4: base_rates 다이제스트 테스트 — 앵커링 방지 계약 포함."""

from __future__ import annotations

import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ai_fc import base_rates
from ai_fc.db import ingest
from ai_fc.ml.history import append_run
from ai_fc.models import EvidenceBrief, Question
from ai_fc.reasoning_core import build_user_prompt

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 사상 최고가를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        action_link: "테스트"
        status: active
        created: 2099-06-01
""")

LEDGER = "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    (tmp_path / "forecasts").mkdir()
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    return tmp_path


def _ml_payload(run_ts: str) -> dict:
    return {
        "run_ts": run_ts, "kind": "ml",
        "forecasts": [
            # 매핑 참조 확률 0.7317 — 다이제스트에 절대 나타나면 안 되는 값
            {"question_id": "fixture-coin-ath", "model": "ensemble", "kind": "terminal",
             "prob": 0.7317, "threshold": 27000.0, "horizon_weeks": 10, "detail": {}},
        ],
        "sentiment": [{"feed": "fx", "n_headlines": 10, "score": 0.05}],
        "series_bands": {
            "q_ixic": {"symbol": "^IXIC", "horizon_weeks": 10, "last_value": 26107.0,
                       "terminal": {"q10": 23477.0, "q25": 25264.0, "q50": 27125.0,
                                    "q75": 28942.0, "q90": 30683.0},
                       "median_pct": 0.039,
                       "gbm": {"mu_w": 0.001, "sigma_w": 0.025}},
        },
        "sentiment_overall": 0.05,
    }


def _context_payload(run_ts: str) -> dict:
    return {
        "run_ts": run_ts, "kind": "context", "source": "dualdb",
        "analog": {
            "closest_era": "dotcom", "distance": 0.23,
            "fwd_return_dist": {"m3": 0.0978, "m6": 0.2823, "m12": 0.4012, "n": 5},
            "correction_depth_median": -0.1292,
            "n_eras": 5, "pool_eras": ["dotcom", "biotech2015"],
            "selected_eras": ["dotcom", "biotech2015"], "asof": "2026-07-20",
        },
        "factor_tilt": {"value_z": 0.57, "momentum_z": 0.33, "size_z": 0.19,
                        "vintage": "2026-05-01"},
        "regime": {"yield_curve_10y2y": 0.37, "yield_curve_inverted": False,
                   "hy_spread_pct": 2.71, "hy_spread_pctile": 9.8, "hy_spread_n": 787,
                   "cape_latest": 30.8, "cape_pctile": 94.8, "cape_vintage": "2023-09-01"},
        "note": "과거 유사 시대 base rate — 질문 매핑 확률 아님(R-4, 준-앵커 주의)",
    }


def test_digest_injects_context_raw_material(repo: Path) -> None:
    """context run이 있으면 아날로그·팩터·레짐 원재료 라인이 주입된다 (Phase 1-D)."""
    conn = ingest.connect(repo / "db" / "index.db")
    now = datetime.now().isoformat(timespec="seconds")
    append_run(repo, _ml_payload(now))
    append_run(repo, _context_payload(now))
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath")
    assert d is not None
    assert "최근접 과거 사이클: dotcom" in d          # 아날로그 주입
    assert "+28.2%" in d                               # 6M 전방수익률 중앙값
    assert "가치(HML)" in d and "레짐" in d            # 팩터·레짐 주입
    assert "R-4" in d                                  # 준-앵커 주의 라벨 필수
    # 여전히 매핑 참조 확률은 미포함 (앵커링 방지 계약 — context도 동일)
    assert "0.7317" not in d and "73%" not in d


def test_digest_context_phase2_signals(repo: Path) -> None:
    """Phase 2 신호 — 실측 침체 플래그·폭 프록시·심층 역사·Perez 국면 렌더."""
    conn = ingest.connect(repo / "db" / "index.db")
    now = datetime.now().isoformat(timespec="seconds")
    p = _context_payload(now)
    p["regime"]["recession_flag"] = False
    p["regime"]["recession_date"] = "2026-06-01"
    p["breadth"] = {"pct_above_200dma": 62.5, "n": 24, "asof": "2026-07-20",
                    "note": "등가중 프록시"}
    p["deep_history"] = [{"era": "dow1929", "peak": "1929-09", "trough": "1932-06",
                          "depth": -0.871, "note": "월평균"}]
    p["perez_ai"] = "installation frenzy 후반 추정 — 미확정"
    append_run(repo, p)
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath")
    assert d is not None
    assert "NBER 침체(USREC 2026-06-01) 아님" in d
    assert "[폭] 추적 24종 중 200DMA 상회 62.5%" in d
    assert "[심층 역사] dow1929" in d and "-87.1%" in d
    assert "[Perez 국면]" in d and "추정" in d
    # 구형 payload(신규 키 없음)와의 호환은 기존 테스트들이 보증


def test_digest_context_only_without_ml(repo: Path) -> None:
    """ml run이 없어도(또는 stale) context 단독으로 주입된다."""
    conn = ingest.connect(repo / "db" / "index.db")
    now = datetime.now().isoformat(timespec="seconds")
    append_run(repo, _context_payload(now))            # ml 없음
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath")
    assert d is not None
    assert "아날로그·팩터·레짐 컨텍스트" in d           # context 단독 헤더
    assert "최근접 과거 사이클: dotcom" in d


def test_digest_stale_context_not_injected(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    old = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    append_run(repo, _context_payload(old))
    ingest.sync(conn, repo)
    assert base_rates.ml_digest(repo, conn, "fixture-coin-ath") is None


def test_digest_contains_bands_not_mapped_probs(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    append_run(repo, _ml_payload(datetime.now().isoformat(timespec="seconds")))
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath")
    assert d is not None
    assert "27,125" in d            # 분위수 밴드는 포함
    assert "0.7317" not in d        # 매핑 참조 확률은 미포함 (앵커링 방지 계약)
    assert "73%" not in d
    assert "매매 신호 아님" in d


def test_digest_stale_returns_none(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    old = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    append_run(repo, _ml_payload(old))
    ingest.sync(conn, repo)
    assert base_rates.ml_digest(repo, conn, "fixture-coin-ath") is None


def test_digest_absent_history_returns_none(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    assert base_rates.ml_digest(repo, conn, "fixture-coin-ath") is None


def test_digest_max_chars_cut(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    append_run(repo, _ml_payload(datetime.now().isoformat(timespec="seconds")))
    ingest.sync(conn, repo)
    d = base_rates.ml_digest(repo, conn, "fixture-coin-ath", max_chars=50)
    assert d is not None and len(d) <= 50


def test_prompt_unchanged_without_aux() -> None:
    q = Question(
        question_id="fixture-coin-ath", title="t", question="q?",
        deadline_kind="fixed", deadline=date(2099, 12, 31), rolling_days=None,
        resolution="YES", resolution_source="src", domain="fixture",
        cadence_raw="주 1회", schedule=[{"per_week": 1}], action_link="",
        status="active", created=date(2099, 6, 1), notes="",
        required_snapshots=[], src_hash="x")
    briefs = [EvidenceBrief("general", "본문", 3, 0.1, 100, 50)]
    base = build_user_prompt(q, briefs, date(2099, 6, 15), None)
    same = build_user_prompt(q, briefs, date(2099, 6, 15), None, aux_context=None)
    assert base == same
    with_aux = build_user_prompt(q, briefs, date(2099, 6, 15), None, aux_context="참조 A")
    assert "참조 A" in with_aux and "Outside view 보조" in with_aux
