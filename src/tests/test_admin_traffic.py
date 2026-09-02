import json
from datetime import datetime, timezone
from pathlib import Path

from ai_fc.admin_traffic import (
    DASHBOARD_RELATIVE, HISTORY_RELATIVE, merge_daily, read_history,
    render_dashboard, take_snapshot,
)


def _fake_fetcher(day_counts):
    def fetch(endpoint):
        if endpoint.endswith("/traffic/views"):
            return {"count": sum(c for c, _ in day_counts), "uniques": 2, "views": [
                {"timestamp": f"2026-09-{i + 1:02d}T00:00:00Z", "count": c, "uniques": u}
                for i, (c, u) in enumerate(day_counts)
            ]}
        if endpoint.endswith("/traffic/clones"):
            return {"count": 3, "uniques": 2, "clones": [
                {"timestamp": "2026-09-01T00:00:00Z", "count": 3, "uniques": 2}
            ]}
        if endpoint.endswith("/popular/referrers"):
            return [{"referrer": "github.com", "count": 5, "uniques": 2}]
        if endpoint.endswith("/popular/paths"):
            return [{"path": "/Jin-s-investing-prediction/", "title": "dash", "count": 7, "uniques": 2}]
        raise AssertionError(endpoint)
    return fetch


def test_snapshot_appends_and_daily_merge_takes_max(tmp_path: Path):
    take_snapshot(tmp_path, fetcher=_fake_fetcher([(4, 1), (2, 2)]),
                  now=datetime(2026, 9, 2, tzinfo=timezone.utc))
    take_snapshot(tmp_path, fetcher=_fake_fetcher([(6, 1), (1, 1)]),
                  now=datetime(2026, 9, 3, tzinfo=timezone.utc))
    history = read_history(tmp_path)
    assert len(history) == 2
    merged = merge_daily(history, "views")
    # 같은 날짜는 스냅샷 간 최댓값으로 병합된다 (당일 수치는 자라다 멈춘다)
    assert merged == [
        {"date": "2026-09-01", "count": 6, "uniques": 1},
        {"date": "2026-09-02", "count": 2, "uniques": 2},
    ]
    # append-only: 파일 줄 수 == 스냅샷 수
    lines = (tmp_path / HISTORY_RELATIVE).read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines if l.strip()]) == 2
    assert all(json.loads(l)["fetched_at"] for l in lines)


def test_dashboard_renders_disclosures_and_no_pii_claims(tmp_path: Path):
    take_snapshot(tmp_path, fetcher=_fake_fetcher([(4, 1)]),
                  now=datetime(2026, 9, 2, tzinfo=timezone.utc))
    out = render_dashboard(tmp_path)
    assert out == tmp_path / DASHBOARD_RELATIVE
    page = out.read_text(encoding="utf-8")
    assert "저장소 방문 통계 (관리자 전용)" in page
    assert "Pages 사이트" in page  # 측정 대상 공시: 사이트 방문이 아니라 저장소 방문
    assert "개인 식별" in page and "제공하지 않" in page   # 한계 공시
    assert "롤링 14일" in page
    assert "github.com" in page and "/Jin-s-investing-prediction/" in page
