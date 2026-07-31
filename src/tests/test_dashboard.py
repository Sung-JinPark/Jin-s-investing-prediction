"""대시보드 — read-model 형상·자기완결성·읽기전용 서버 계약 (합성 픽스처)."""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

import pytest

from ai_fc import dashboard
from ai_fc.db import ingest

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
        drivers: [test-driver]
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


def test_read_model_shape(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    m = dashboard.build_read_model(conn, repo)
    for key in ("meta", "scenario", "questions", "forecast_history",
                "resolutions", "ml_runs", "market_runs", "calibration", "due"):
        assert key in m, f"read-model 키 누락: {key}"
    assert m["meta"]["n_questions"] == 1
    assert m["questions"][0]["drivers"] == ["test-driver"]
    # 시나리오 상수 3분할 (DECISIONS 8-1 정합)
    probs = {k: m["scenario"]["paths"][k]["prob"] for k in ("S1", "S2", "S3")}
    assert sum(probs.values()) == 100
    assert probs["S1"] <= 66  # 단조성: P(S1) ≤ P(F3)


def test_template_self_contained() -> None:
    """외부 리소스 로드 0 — report.py 자기완결 원칙 승계.

    SVG 네임스페이스(http://www.w3.org/2000/svg)는 브라우저가 fetch하지 않는
    상수라 예외 — 실제 리소스 로드(CDN 스크립트·스타일시트·폰트·이미지)만 검사.
    """
    import re

    html = dashboard.TEMPLATE.read_text(encoding="utf-8")
    assert "<!--DATA-->" in html
    assert "window.__DATA__" in html and "window.__DATA_URL__" in html
    assert "<link" not in html.lower(), "외부 스타일시트 링크 발견"
    # 리소스 로드 속성(src=/href=)이 외부 URL을 가리키지 않아야 함
    for attr in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html, re.I):
        if attr.startswith("#") or attr.startswith("/") or "www.w3.org" in attr:
            continue  # 앵커·내부 경로·SVG 네임스페이스는 허용
        assert not attr.startswith(("http:", "https:", "//")), f"외부 리소스: {attr}"
    # CDN 관용 호스트가 아예 없어야 함
    for host in ("cdn.", "unpkg", "jsdelivr", "googleapis", "cloudflare", "chart.js"):
        assert host not in html.lower(), f"CDN 흔적: {host}"


def test_ui_contract() -> None:
    """UI 현대화 계약 — 제품 rail·첫 화면 briefing·접근성·동적 전환."""
    html = dashboard.TEMPLATE.read_text(encoding="utf-8")
    assert "<h1" in html, "대형 H1 없음"
    # 6개 실제 hash link
    for v in ("overview", "flow", "ask", "questions", "asof", "track"):
        assert f'href="#{v}"' in html, f"nav 실제 링크 누락: {v}"
    assert 'aria-current' in html, "aria-current 처리 없음"
    assert "prefers-reduced-motion" in html
    assert "view-enter" in html, "화면 진입 전환 클래스 없음"
    assert "feature-grid" in html, "핵심 질문 카드 그리드 없음"
    assert "analysis-panel" in html, "분석 패널 없음"
    assert 'class="product-rail"' in html, "데스크톱 제품 rail 없음"
    assert 'class="mobile-drawer"' in html, "모바일 drawer 없음"
    assert 'class="overview-stage"' in html, "시장 브리핑 첫 화면 없음"
    assert 'aria-expanded="false"' in html and "setDrawer" in html
    assert 'class="site-header"' not in html, "구형 전체 너비 헤더가 남아 있음"
    assert "--blue:" not in html and "var(--blue)" not in html, "구형 파란 강조색이 남아 있음"
    # Mistral-inspired revision은 warm ivory와 흰 분석 surface를 사용한다.
    for light_surface in (
        "--paper:#fbfbf8",
        "--surface:#fff",
        "html{color-scheme:light",
        ".product-rail{padding:0;color:#11110f",
        ".overview-stage{min-height:calc(100dvh - 48px)",
        ".panel{color:#11110f;background:#fff",
        ".table-shell{background:#fff",
        ".round-sidebar,.reasoning-panel,.resolution-card{color:#11110f;background:#fff",
    ):
        assert light_surface in html, f"light intelligence UI 계약 누락: {light_surface}"
    assert "SCEN_DEEP" not in html
    assert "--violet:#a99bff" not in html, "구형 dark ambient violet이 남아 있음"
    assert "--orange:#ff4f17" in html and "--crimson:#c9002d" in html
    assert "--display:'Segoe UI Variable Display'" in html
    assert "--sans:'Segoe UI Variable Text'" in html
    assert "font-size:clamp(52px,4.7vw,72px)" in html
    assert "letter-spacing:-.055em" in html
    assert 'class="command-layer"' in html and 'role="dialog"' in html
    assert 'aria-modal="true"' in html and "setCommand" in html
    assert "<kbd>⌘ K</kbd>" in html
    assert "miniSparkline" in html and 'class="card-spark"' in html
    assert "signalMosaic" in html and 'class="signal-mosaic"' in html
    assert "bindDynamicMotion" in html and "requestAnimationFrame(paint)" in html
    assert "--tilt-x" in html and "pointermove" in html
    assert ".filter-bar{position:sticky" in html
    # 두 SVG 생성 함수 유지
    assert "function drawFlow" in html and "function drawOverlay" in html
    # 핵심 확률 대형 타이포 (72px+ clamp)
    assert "clamp(78px" in html, "핵심 확률 대형 크기 없음"
    # 시나리오 가중치를 질문 확률로 혼용하지 않음(하드코딩 금지) — FEATURE_QIDS로 데이터 참조
    assert "FEATURE_QIDS" in html


def test_workspace_utility_contract() -> None:
    """부가기능은 기존 read-model 위에서만 동작하고 로컬 상태로 닫혀 있어야 한다."""
    html = dashboard.TEMPLATE.read_text(encoding="utf-8")
    for element_id in (
        "utility-layer", "shortcut-layer", "toast-region", "focus-exit",
        "route-progress-bar", "view-map", "quick-peek", "briefing-layer",
        "briefing-content", "briefing-prev", "briefing-next",
    ):
        assert f'id="{element_id}"' in html, f"워크스페이스 UI 누락: {element_id}"
    for behavior in (
        "jin-investing-ui-v1",
        "localStorage",
        "sessionStorage",
        "navigator.share",
        "navigator.clipboard",
        "recordRecent",
        "toggleCurrentPin",
        "window.print()",
        "briefingScenes",
        "buildSectionNavigator",
        "bindQuickPeek",
        "quickPeekCopy",
        "quickPeekProbability",
        "deadlineWindow",
        "DRIVER_LABELS",
        "DOMAIN_LABELS",
        "IntersectionObserver",
        "workspace-note",
        "setMotion",
    ):
        assert behavior in html, f"워크스페이스 동작 누락: {behavior}"
    assert "body.focus-mode" in html
    assert "body.density-compact" in html
    assert "body.motion-reduced" in html
    assert "body.briefing-open" in html
    assert "3 STEP BRIEFING" in html
    assert "Shift B" in html and "Shift N" in html
    assert "maxlength=\"700\"" in html
    assert "@media print" in html
    assert "COMMAND_ROUTES" in html and "commandCatalog" in html
    assert "data-command-index" in html
    assert "WHY IT MATTERS" in html and "DECISION WINDOW" in html
    assert "한 줄 해석" in html and "관찰 변수" in html
    assert "probability==null||probability===''" in html
    assert "peek-title" not in html and "peek-metric" not in html


def test_render_embed_vs_fetch(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    model = dashboard.build_read_model(conn, repo)
    embed = dashboard.render_html(model, mode="embed")
    assert "window.__DATA__ = {" in embed
    assert "fixture-coin-ath" in embed  # 데이터가 실제로 임베드됨
    fetch = dashboard.render_html({}, mode="fetch")
    assert "/api/data" in fetch
    assert "window.__DATA__ = {" not in fetch  # fetch 모드는 임베드 없음


def test_server_is_read_only() -> None:
    """serve() 핸들러가 쓰기 메서드(POST)를 405로 차단하는지 소스 계약 검증."""
    src = inspect.getsource(dashboard.serve)
    assert "do_POST" in src and "405" in src
    assert "read-only" in src
    # /api/data는 새 연결로 조회만 (쓰기 함수 미호출)
    assert "build_read_model" in src and "conn.close()" in src


def test_write_dashboard(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    out = dashboard.write_dashboard(conn, repo)
    assert out.exists() and out.name == "dashboard.html"
    assert "window.__DATA__" in out.read_text(encoding="utf-8")


def test_write_pages(repo: Path) -> None:
    """GitHub Pages 빌드 — index.html(자기완결) + .nojekyll."""
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    out_dir = repo / "_site"
    index = dashboard.write_pages(conn, out_dir, repo)
    assert index.name == "index.html"
    assert (out_dir / ".nojekyll").exists()
    assert "window.__DATA__" in index.read_text(encoding="utf-8")
