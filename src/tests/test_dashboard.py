"""대시보드 — read-model 형상·자기완결성·읽기전용 서버 계약 (합성 픽스처)."""

from __future__ import annotations

import inspect
import json
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
    project_root = Path(__file__).parents[2]
    for relative in (
        Path("data/contracts/calendar_sources.yaml"),
        Path("data/calendar/events.csv"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((project_root / relative).read_bytes())
    return tmp_path


def test_read_model_shape(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    m = dashboard.build_read_model(conn, repo)
    for key in ("meta", "scenario", "scenario_history", "questions", "forecast_history",
                "resolutions", "ml_runs", "market_runs", "calibration", "due",
                "trust", "arena", "receipts", "asof_index", "clusters", "corrections",
                "probability_semantics", "changelog", "era_analog", "cross_asset",
                "source_monitoring"):
        assert key in m, f"read-model 키 누락: {key}"
    assert m["meta"]["n_questions"] == 1
    assert m["questions"][0]["drivers"] == ["test-driver"]
    assert m["questions"][0]["probability_space"] == "physical_event"
    # 시나리오 상수 3분할 (DECISIONS 8-1 정합)
    probs = {k: m["scenario"]["paths"][k]["prob"] for k in ("S1", "S2", "S3")}
    assert sum(probs.values()) == 100
    assert probs["S1"] <= 66  # 단조성: P(S1) ≤ P(F3)
    assert m["scenario_history"][-1]["asof"] == m["scenario"]["asof"]
    assert m["probability_semantics"]["canonical_unit"] == "fraction"
    assert m["calibration"]["gate_v2"]["display_only"] is True
    assert m["era_analog"]["probability_space"] == "reference_only"
    assert m["cross_asset"]["probability_space"] == "scenario_conditional"


def test_forecast_body_dictionary_round_trip() -> None:
    import re

    phrase = dashboard.FORECAST_BODY_DICTIONARY[0]
    body = phrase.replace(phrase, chr(0xE000))
    assert body == chr(0xE000)
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "decodeForecastBody" in script
    js_dictionary = re.search(r"const BODY_DICTIONARY=\[(.*?)\];", script, re.S)
    assert js_dictionary is not None
    assert tuple(re.findall(r"'([^']*)'", js_dictionary.group(1))) == dashboard.FORECAST_BODY_DICTIONARY


def test_template_self_contained() -> None:
    """외부 리소스 로드 0 — report.py 자기완결 원칙 승계.

    SVG 네임스페이스(http://www.w3.org/2000/svg)는 브라우저가 fetch하지 않는
    상수라 예외 — 실제 리소스 로드(CDN 스크립트·스타일시트·폰트·이미지)만 검사.
    """
    import re

    html = dashboard.load_template()
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


def test_template_parts_bundle_and_budget() -> None:
    """소스는 유지보수 가능한 파셜이며 최종 산출물은 자기완결·용량 예산 이내다."""
    shell = dashboard.TEMPLATE.read_text(encoding="utf-8")
    assert "<!--STYLES-->" in shell and "<!--APP_SCRIPT-->" in shell
    assert dashboard.DASHBOARD_STYLES.exists()
    assert dashboard.DASHBOARD_SCRIPT.exists()
    html = dashboard.load_template()
    assert "<!--STYLES-->" not in html and "<!--APP_SCRIPT-->" not in html
    assert len(dashboard.render_html({}, mode="embed").encode("utf-8")) <= dashboard.DASHBOARD_RAW_BUDGET_BYTES


def test_ui_contract() -> None:
    """UI 현대화 계약 — 제품 rail·첫 화면 briefing·접근성·동적 전환."""
    html = dashboard.load_template()
    assert "<h1" in html, "대형 H1 없음"
    # 5개 핵심 목적지. 보조 화면은 문맥 탭/빠른 이동에서 제공한다.
    for v in ("overview", "flow", "questions", "asof", "track"):
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
    assert "font-size:clamp(44px,3.65vw,52px)" in html
    assert "letter-spacing:-.055em" in html
    assert 'class="command-layer"' in html and 'role="dialog"' in html
    assert 'aria-modal="true"' in html and "setCommand" in html
    assert "<kbd>⌘ K</kbd>" in html
    assert "miniSparkline" in html and 'class="card-spark"' in html
    assert "signalMosaic" in html and 'class="signal-mosaic"' in html
    assert "bindDynamicMotion" in html and "requestAnimationFrame(paint)" in html
    assert "--tilt-x" in html and "pointermove" in html
    assert ".filter-bar{position:sticky" in html
    # 시장 지도 SVG 생성 함수 유지
    assert "function drawFlow" in html and "function drawOverlay" in html
    assert "function drawCrossAsset" in html and "function drawCrossAssetHistory" in html
    assert "사전 등록 가정" in html
    assert "조건 4개" in html
    assert "O 미래선은 가격 경로이며 배당 미포함" in html
    assert "rates_stay_high_support" in html
    # 핵심 확률 대형 타이포 (72px+ clamp)
    assert "clamp(78px" in html, "핵심 확률 대형 크기 없음"
    # 시나리오 가중치를 질문 확률로 혼용하지 않음(하드코딩 금지) — FEATURE_QIDS로 데이터 참조
    assert "FEATURE_QIDS" in html
    assert 'class="mobile-bottom-nav"' in html
    assert "decisionQueueCard" in html and "linkedSignalStrip" in html
    assert "bindHomeSignals" in html and "lastSeenGeneratedAt" in html
    assert 'class="skip-link"' in html and 'id="app" tabindex="-1"' in html
    assert "const hasNumeric=" in html and "const roundLabel=" in html
    assert "산출 전" in html
    assert '<div class="probability-row"><strong>${q.latest_prob}</strong><span>%</span></div>' not in html
    assert '<span>R${q.n_rounds}</span>' not in html


def test_workspace_utility_contract() -> None:
    """부가기능은 기존 read-model 위에서만 동작하고 로컬 상태로 닫혀 있어야 한다."""
    html = dashboard.load_template()
    for element_id in (
        "utility-layer", "shortcut-layer", "toast-region", "focus-exit",
        "route-progress-bar", "view-map", "quick-peek", "briefing-layer",
        "briefing-content", "briefing-prev", "briefing-next",
        "compare-tray", "compare-items", "compare-open", "compare-toggle",
        "compare-count", "question-mobile-list",
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
        "changeRadarData",
        "vintageReceipt",
        "humanDomain",
        "humanDriver",
        "myRadarPanel",
        "renderCompareTray",
        "toggleCompareQuestion",
        "renderCompare",
        "drawCompareHistory",
        "toggleCompareTray",
        "reviewQueueData",
        "reviewQueuePanel",
        "dismissReviewQuestion",
        "renderAsofTimeMachine",
        "downloadQuestionCalendar",
        "signal-lens-readout",
        "researchPriority",
        "questionMatchesPreset",
        "sortResearchQuestions",
        "data-question-preset",
        "research-sort",
        "flow-readout",
        "paintCursor",
        "evidenceDeltaMarkup",
        "reasoningText",
        "round-delta",
        "reasoning-compare",
        "data-question-layout",
        "research-display",
        "data-analog-focus",
        "SELECTED MONTH",
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
    assert "WHAT CHANGED" in html and "MY RADAR" in html
    assert "SCENARIO VINTAGE" in html and "As-of Time Machine" in html
    assert "businessDayDiff" in html and "is-stale" in html
    assert "askPresets" in html and "nearestWeekIndex" in html
    assert "answer(25)" not in html
    assert "확률은 예측 모델 앙상블 산출값" not in html
    assert "gbm-daily-252d" in html
    assert "조건부 구간 p10–p90" in html
    assert "scenarioChangePanel" in html and "scenarioHistoryRows" in html
    assert "SCENARIO CHANGE" in html and "MODEL RECEIPT" in html
    assert "저장된 시나리오 수치의 차이만 요약" in html
    assert 'class="filter-insights"' in html and 'class="flow-focus"' in html
    assert "data-calendar-all" in html and "data-calendar-selected" in html
    assert "legibility layer v3" in html
    for token in ("--type-micro", "--type-caption", "--type-control", "--type-data"):
        assert token in html, f"가독성 타이포 토큰 누락: {token}"
    assert ".question-action{min-width:44px;min-height:44px" in html
    assert "table{font-size:var(--type-data)}" in html
    assert 'class="table-shell question-table-shell"' in html
    assert 'class="mobile-question-card"' in html
    assert "className='compare-readout'" in html
    assert "REVIEW QUEUE" in html and "data-review-dismiss" in html
    assert "compareCollapsed" in html and "compareAutoExpanded" in html
    assert "questionView" in html and "검토 우선순위" in html
    assert "version:4" in html and "layout:'table'" in html
    assert "WHAT CHANGED · R${previous.round} → R${current.round}" in html
    assert "이전 회차와 근거 나란히 보기" in html
    assert "저장된 근거 원문이 없습니다" in html
    assert "집계 기준 상이" in html and "const maxIndex=focus==='ALL'?CAP" in html
    assert "research-layout-cards" in html and "analog-readout" in html
    assert "tip-series" in html and "--tip-series" in html
    assert "크립토 2019 시작" in html and "2021-11(M+34)" in html
    assert "crypto2021:['크립토 2019 시작','#1f6feb'" in html
    assert "biotech2015:['바이오 2013','#a43c82'" in html
    assert "dow1929:['다우 1925','#6b5845'" in html
    assert "SELECTED WEEK" in html and "pointerdown" in html
    assert "overlay.addEventListener('pointermove'" in html
    assert "event.key==='ArrowLeft'" in html
    assert "peek-title" not in html and "peek-metric" not in html
    assert 'role="tablist" aria-label="시장 지도 분석 공간"' in html
    assert "REFERENCE ONLY · 확률 아님" in html
    assert "DATA.era_analog" in html
    assert "drawOverlay(analogHost,overlay._overlay" in html
    assert "data-flow-focus=\"ANALOG\"" not in html
    assert "DATA.cross_asset" in html and "data-lab-tab=\"cross-asset\"" in html
    assert "BTC DATA GAP · 정상 결측" in html
    assert "동반 디레버리징" in html and "data-cross-scenario" in html
    assert "drawIndexedCompare" in html and "하락꼬리 BTC beta" in html
    assert 'class="cross-anchor-strip"' in html
    assert "가중치 미산출 — 충격 유형별 캘리브레이션 부족" in html
    assert "paths_band" in html and "resolveEndpointLabels" in html
    assert "aria-live','polite" in html and 'role="radiogroup"' in html
    assert "model.history.period" in html and "label.endsWith('-06')" in html
    assert 'data-lab-tab="ai-regime"' in html and 'data-lab-tab="liquidity"' in html
    assert "Scenario Tracker" in html and "가중 합산 없음" in html
    assert "이 체크리스트는 사전 등록된 방향 규칙이며 확률이 아닙니다" in html
    assert "데이터 커버리지 부족" in html and "MAP WITHHELD" in html
    assert "표본 축적 중 ${num(row.observations)}/${num(row.minimum_observations)}" in html
    assert "유동성 확장이 곧 상승을 뜻하지 않습니다" in html
    assert "function drawLiquidity" in html and "liquidity_zone" in html
    assert "monitor.consecutive_successful_days" in html
    assert "자동 활성화 안 함" in html


def test_forecast_lookup_ui_contract() -> None:
    html = dashboard.load_template()
    for required in (
        'type="date"', 'aria-live="polite"', "#lookup=", "10–90% 구간",
        "25–75% 구간", "중앙값", "모델 조건부 확률",
        "목표가·사건확률·투자자문이 아닙니다", "NO API · NO STORAGE",
        "8월 30일 · 3개월 뒤 · 연말", "정규식 규칙 파서 · LLM 호출 없음",
        "PHYSICAL EVENT · 별도 확률 공간", "시나리오 분포와 결합 금지",
        "현재 기준 미래 분포 조회", "미래 날짜에 새로 만든 전망이 아니라",
        'data-flow-horizon="126"', 'data-flow-horizon="252"',
        "2027년까지", "flowHorizonEndIndex", "flowAxisTickIndexes",
        "2027년까지 주요 일정", "확정·추정 분리 · 전망성 해석 제외",
        "flowEventLayout", "조회 · ",
        "PATH REALISM · SAME 20,000 PATHS", "실경로 오버레이",
        "연속 대표 실경로", "이 선은 충격 가정의 민감도 경로이며 실제 시장의 요동을 표현하지 않습니다",
        "2027년까지 AI 버블이 생존할 확률이나 붕괴 시점이 아닙니다", "flowDisplayPath", "flowPathStats",
        "선택일을 100으로 재기준", "현재 원점 유지", "buildRebasedFlowModel",
        "D = 100 · CURRENT MODEL PROPERTY", "#lookup=${mapped.requested}&mode=${lookupMode}",
        "D일에 실제로 도달했을 때의 새 정보", "D일이 오면 그날의 스냅샷이 새로 계산됩니다",
        "horizonCoverageForDay", "미검증 구간", "적중 기록 축적 중",
        "inside_p10_p90_rate_pct", "0일 · 0/60",
        "lookupEventSummary", "일정과 분포 확률을 연결하지 않습니다",
        "EVENT_KIND_META", "월 패턴 또는 연준의 공식 잠정 일정",
    ):
        assert required in html
    assert "lookup-metrics" in html and "lookup-primary" in html
    assert "mapped.index>=126" in html, "6개월 밖 조회는 전체 지평으로 확장해야 함"


def test_data_growth_explainer_is_plain_language_and_live() -> None:
    html = dashboard.load_template()
    for required in (
        "데이터는 이렇게 쌓입니다", "파일이 원본입니다",
        "화–토 새벽에 확정값을 확인합니다", "개 원장을 자동 감사합니다",
        "월 1회 연구팩을 고정합니다", "없는 데이터도 숨기지 않습니다",
        "ledgerSummary.accumulating", "ledgerSummary.stalled", "ledgerSummary.violation",
    ):
        assert required in html


def test_liquidity_return_legends_use_separate_lanes() -> None:
    html = dashboard.load_template()
    assert "NASDAQ · 26주 수익률" in html
    assert "BITCOIN · 26주 수익률" in html
    assert "labelX:ML+235" in html, "NASDAQ/BITCOIN 범례가 같은 SVG 좌표를 쓰면 안 됨"


def test_decision_journal_share_and_contrast_contract() -> None:
    html = dashboard.load_template()
    for required in (
        "예측 변경 일지", "그날로 돌아가기", "APPEND-ONLY PROVENANCE",
        'role="feed"', "change_note", "#asof=", "share-popover",
        "시장 기준 ${asof}", "조건부 시나리오이며 목표가·투자자문이 아닙니다",
        "blog.naver.com/openapi/share", "band.us/plugin/share",
        "social-plugins.line.me/lineit/share", "t.me/share/url", "QrCreator.render",
    ):
        assert required in html
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    assert '.cross-focus button[aria-checked="true"]' in css
    assert "color:#5b3514!important" in css
    assert "background:#fff0db!important" in css


def test_round2_cross_asset_explanations_and_method_event_contract() -> None:
    html = dashboard.load_template()
    for required in (
        "realtyContext.condition_summary", "M+3 O 기여", "BTC 경로 공유 · 설계상 동일",
        "gate 경계(n=156)", "DATA.method_changes", "public_repository_url",
    ):
        assert required in html
    changes = (dashboard.config.ROOT / "data/method_changes.jsonl").read_text(encoding="utf-8")
    assert "교차자산 경로 추적 원장 v2 전환" in changes


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


def test_repository_snapshot_stays_within_dashboard_budget(tmp_path: Path) -> None:
    """실제 누적 원장으로도 Pages 산출물의 고정 용량 계약을 지킨다."""
    conn = ingest.connect(tmp_path / "index.db")
    ingest.sync(conn, dashboard.config.ROOT)
    html = dashboard.render_html(
        dashboard.build_read_model(conn, dashboard.config.ROOT), mode="embed"
    )
    assert len(html.encode("utf-8")) <= dashboard.DASHBOARD_RAW_BUDGET_BYTES


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
    """GitHub Pages 빌드 — shell + cacheable local data JSON + .nojekyll."""
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    out_dir = repo / "_site"
    index = dashboard.write_pages(conn, out_dir, repo)
    assert index.name == "index.html"
    assert (out_dir / ".nojekyll").exists()
    assert "data.json" in index.read_text(encoding="utf-8")
    assert "<script>window.__DATA__ =" not in index.read_text(encoding="utf-8")
    html = index.read_text(encoding="utf-8")
    assert 'property="og:title"' in html and 'name="twitter:card"' in html
    from PIL import Image
    og = out_dir / "og" / "market-snapshot.png"
    assert og.exists()
    with Image.open(og) as image:
        assert image.size == (1200, 630)
    payload = json.loads((out_dir / "data.json").read_text(encoding="utf-8"))
    assert payload["meta"]["n_questions"] >= 1
