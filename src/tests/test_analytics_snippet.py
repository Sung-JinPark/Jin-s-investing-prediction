from ai_fc import dashboard
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


def test_pages_mode_injects_snippet_and_embed_stays_self_contained():
    pages = dashboard.render_html({}, mode="pages")
    assert "gc.zgo.at/count.js" in pages
    assert "jin-investing.goatcounter.com/count" in pages
    embed = dashboard.render_html({}, mode="embed")
    assert "gc.zgo.at" not in embed          # 감사 HTML 자기완결 원칙
    assert "<!--ANALYTICS-->" not in embed   # 마커 잔존 금지
    assert "<!--ANALYTICS-->" not in pages
