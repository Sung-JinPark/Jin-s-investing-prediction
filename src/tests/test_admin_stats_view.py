from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1] / "ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
TEMPLATE_HTML = None


def test_admin_route_is_hidden_and_registered():
    # 라우트는 존재하되 내비 등록(MID_CATEGORIES)에는 없다
    assert "parts[0]==='admin-stats'" in SCRIPT
    assert "adminstats:renderAdminStats" in SCRIPT
    mid = SCRIPT.split("const MID_CATEGORIES={", 1)[1].split("};", 1)[0]
    assert "admin-stats" not in mid


def test_token_gate_uses_local_storage_and_single_origin():
    # 토큰은 localStorage 게이트로만 다루고, 전송 대상은 GoatCounter API 단일 origin
    assert "gc_api_token" in SCRIPT
    assert "https://jin-investing.goatcounter.com/api/v0" in SCRIPT
    assert SCRIPT.count("Authorization:'Bearer '+gcToken()") == 1
    # 사이트 코드에 토큰 리터럴이 박혀 있지 않다 (Bearer 뒤는 항상 함수 호출)
    assert "Bearer '+'" not in SCRIPT


def test_gate_copy_discloses_storage_boundary():
    assert "localStorage에만" in SCRIPT
    assert "토큰 삭제" in SCRIPT


def test_owner_visits_can_be_excluded_and_the_toggle_is_disclosed():
    """사용자 지시 2026-09-08: 관리자(소유자) 브라우저는 기본 제외, 토글로 되돌릴 수 있고
    브라우저 단위·소급 불가라는 한계를 화면이 말한다."""
    assert "const GC_OWNER_KEY='gc_owner_optout'" in SCRIPT
    assert "function gcOwnerOptOut()" in SCRIPT and "function gcSetOwnerOptOut(on)" in SCRIPT
    assert "localStorage.setItem('skipgc','t')" in SCRIPT and "localStorage.removeItem('skipgc')" in SCRIPT
    # 토큰이 있으면 기본 제외 (명시 플래그 없을 때)
    assert "return Boolean(gcToken())" in SCRIPT
    # 토큰 저장 순간부터 제외 — 로그인 세션 자체가 집계되지 않는다
    assert "if(value&&gcOwnerOptOut())try{localStorage.setItem('skipgc','t');}" in SCRIPT
    assert 'data-gc-optout aria-pressed="${gcOwnerOptOut()}"' in SCRIPT
    assert "내 방문 제외 중" in SCRIPT and "내 방문 집계 중" in SCRIPT
    for disclosure in ("기기·브라우저마다 따로 적용", "소급 삭제되지 않습니다", "#toggle-goatcounter"):
        assert disclosure in SCRIPT, disclosure


def test_admin_entry_link_in_template():
    template = (Path(__file__).resolve().parents[1] / "ai_fc/dashboard_template.html").read_text(encoding="utf-8")
    assert 'class="admin-entry" href="#admin-stats"' in template
