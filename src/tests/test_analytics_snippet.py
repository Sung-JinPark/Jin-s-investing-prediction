from ai_fc.dashboard import _analytics_snippet


def test_snippet_absent_when_code_empty():
    assert _analytics_snippet("") == ""


def test_snippet_counts_hash_routes_when_code_set():
    snippet = _analytics_snippet("jin-example")
    assert 'data-goatcounter="https://jin-example.goatcounter.com/count"' in snippet
    assert "gc.zgo.at/count.js" in snippet
    # 해시 라우팅 대시보드: 초기·전환 모두 해시 포함 경로로 집계
    assert "location.hash" in snippet
    assert "hashchange" in snippet
