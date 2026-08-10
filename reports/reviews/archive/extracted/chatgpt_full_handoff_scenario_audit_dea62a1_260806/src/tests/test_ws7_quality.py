"""WS7: 출처 등급 · primary_ratio · ok_low_primary 태깅 (대표 뷰 불변 확인)."""

from __future__ import annotations

from pathlib import Path

from ai_fc.db import ingest
from ai_fc.models import EvidenceBrief
from ai_fc.quality import classify_url, refine_research_status, research_quality


def _brief(text: str) -> EvidenceBrief:
    return EvidenceBrief(profile="general", text=text, sources_count=1,
                         cost_usd=0.0, input_tokens=0, output_tokens=0)


def test_classify_url_tiers() -> None:
    assert classify_url("https://www.sec.gov/edgar/filing") == "t1"
    assert classify_url("https://investor.qualcomm.com/news") == "t1"
    assert classify_url("https://insight.factset.com/report") == "t2"
    assert classify_url("https://www.cnbc.com/2026/07/02/jobs.html") == "t3"
    assert classify_url("https://seekingalpha.com/article/x") == "t4"
    assert classify_url("https://totally-unknown-blog.xyz/post") == "unknown"


def test_research_quality_ratio_and_dedup() -> None:
    text = ("사실1 [source: https://www.bls.gov/news.release/empsit.nr0.htm, 2099-01-01] "
            "사실2 [source: https://www.cnbc.com/a.html, 2099-01-01] "
            "사실2 재인용 [source: https://www.cnbc.com/a.html, 2099-01-01] "
            "사실3 [source: https://unknown-site.io/x, 2099-01-01]")
    rq = research_quality([_brief(text)])
    assert rq["sources"]["t1"] == 1 and rq["sources"]["t3"] == 1
    assert rq["sources"]["unknown"] == 1
    assert rq["n_urls"] == 3                       # 중복 URL 1회 계수
    assert abs(rq["primary_ratio"] - 1 / 3) < 1e-3  # round(x, 3) 저장 관례


def test_refine_status_low_primary_only_from_ok() -> None:
    low = {"primary_ratio": 0.1}
    high = {"primary_ratio": 0.6}
    assert refine_research_status("ok", low) == "ok_low_primary"
    assert refine_research_status("ok", high) == "ok"
    assert refine_research_status("degraded", low) == "degraded"   # 더 심한 태그 우선
    assert refine_research_status("failed", low) == "failed"


def test_primary_view_unchanged_by_low_primary(tmp_path: Path) -> None:
    """게이트 조작 금지: ok_low_primary는 v_brier_primary에서 제외되지 않는다."""
    conn = ingest.connect(tmp_path / "db" / "index.db")
    conn.execute(
        """INSERT INTO forecasts (forecast_id, question_id, round, probability,
             path, file_sha256, research_status)
           VALUES ('f1', 'q', 1, 40, 'x.md', 'h', 'ok_low_primary')""")
    conn.execute(
        """INSERT INTO resolutions (forecast_id, resolved_date, question_id,
             probability, outcome, brier, domain)
           VALUES ('f1', '2099-01-02', 'q', 40, 0, 0.16, 'fixture')""")
    conn.commit()
    row = conn.execute("SELECT * FROM v_gate_status").fetchone()
    assert row["n_resolved"] == 1                  # 제외 안 됨 (failed만 제외)
