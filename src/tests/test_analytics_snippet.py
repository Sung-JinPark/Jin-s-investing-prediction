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


def test_snippet_excludes_the_owner_browser_before_count_js_loads():
    """사용자 지시 2026-09-08: 소유자 방문은 통계에서 뺀다 — GoatCounter 공식 플래그(skipgc).

    관리자 토큰이 있는 브라우저는 기본 제외, 명시 토글(gc_owner_optout)이 우선한다.
    플래그는 count.js가 로드되기 전 인라인 스크립트에서 맞춰야 첫 페이지뷰부터 빠진다.
    """
    snippet = _analytics_snippet("jin-example")
    assert "localStorage.getItem('gc_owner_optout')" in snippet
    assert "localStorage.getItem('gc_api_token')" in snippet
    assert "localStorage.setItem('skipgc','t')" in snippet
    assert "localStorage.removeItem('skipgc')" in snippet  # 명시 포함('f')이면 제외 해제
    assert snippet.index("skipgc") < snippet.index("gc.zgo.at/count.js")
    # 토큰 값은 읽어 존재 여부만 쓴다 — 어디로도 보내지 않는다
    assert "gc_api_token')" in snippet and "fetch(" not in snippet


def test_pages_mode_injects_snippet_and_embed_stays_self_contained():
    pages = dashboard.render_html({}, mode="pages")
    assert "gc.zgo.at/count.js" in pages
    assert "jin-investing.goatcounter.com/count" in pages
    embed = dashboard.render_html({}, mode="embed")
    assert "gc.zgo.at" not in embed          # 감사 HTML 자기완결 원칙
    assert "<!--ANALYTICS-->" not in embed   # 마커 잔존 금지
    assert "<!--ANALYTICS-->" not in pages
