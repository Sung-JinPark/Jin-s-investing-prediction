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


def test_admin_entry_link_in_template():
    template = (Path(__file__).resolve().parents[1] / "ai_fc/dashboard_template.html").read_text(encoding="utf-8")
    assert 'class="admin-entry" href="#admin-stats"' in template
