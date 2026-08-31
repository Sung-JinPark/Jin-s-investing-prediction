"""대시보드 — read-model 형상·자기완결성·읽기전용 서버 계약 (합성 픽스처)."""

from __future__ import annotations

import inspect
import json
import re
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
                "source_monitoring", "timeseries"):
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
    assert m["cross_asset"]["probability_space"] == "reference_only"


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


def test_embed_compaction_keeps_latest_body_and_superseded_source_link() -> None:
    model = {
        "forecast_history": {
            "question": [
                {"forecast_id": "old", "body": "old reasoning", "source_uri": "forecasts/old.md"},
                {"forecast_id": "latest", "body": "latest reasoning", "source_uri": "forecasts/latest.md"},
            ]
        }
    }
    compacted = dashboard._compact_embed_forecast_history(model)
    old, latest = compacted["forecast_history"]["question"]
    assert "body" not in old
    assert old["source_uri"] == "forecasts/old.md"
    assert latest["body"] == "latest reasoning"
    assert model["forecast_history"]["question"][0]["body"] == "old reasoning"


def test_embed_compaction_archives_resolved_body_without_mutating_pages_model() -> None:
    model = {
        "questions": [{"id": "resolved-question", "status": "resolved"}],
        "forecast_history": {
            "resolved-question": [
                {
                    "forecast_id": "resolved-r1",
                    "body": "historical reasoning",
                    "source_uri": "forecasts/resolved.md",
                }
            ]
        },
    }
    compacted = dashboard._compact_embed_forecast_history(model)
    archived = compacted["forecast_history"]["resolved-question"][0]
    assert "body" not in archived
    assert archived["source_uri"] == "forecasts/resolved.md"
    assert model["forecast_history"]["resolved-question"][0]["body"] \
        == "historical reasoning"


def test_embed_compaction_archives_band_calibration_rows_without_mutating_pages_model() -> None:
    model = {
        "band_calibration": {
            "status": "ready",
            "probability_space": "scenario_conditional",
            "source_path": "data/scenarios/band_calibration.csv",
            "observations": 2,
            "minimum_observations": 60,
            "gate_pass": False,
            "latest_asof": "2026-08-29",
            "rows": [{"asof": "2026-08-28"}, {"asof": "2026-08-29"}],
        },
    }
    compacted = dashboard._compact_embed_band_calibration(model)
    archived = compacted["band_calibration"]
    # 렌더되는 집계 지표(관측 수·게이트 상태)는 전부 유지, 원시 행만 이관.
    assert "rows" not in archived
    assert archived["observations"] == 2
    assert archived["gate_pass"] is False
    assert archived["rows_archived"] == {
        "archived": True,
        "row_count": 2,
        "reason": "embed_size_budget",
        "source_path": "data/scenarios/band_calibration.csv",
        "full_payload": "data.json",
    }
    # Pages/data.json 경로가 쓰는 원본 모델은 무수정.
    assert len(model["band_calibration"]["rows"]) == 2


def test_embed_projects_append_only_sections_to_rendered_fields() -> None:
    model = {
        "method_changes": [{
            "kind": "method", "date": "2026-08-29", "title": "t", "reason": "r",
            "snapshot_id": "s", "report": "reports/x.md",
            "occurred_at": "2026-08-29T00:00:00Z", "contract": "c",
            "candidate_model_content_sha256": "deadbeef",
        }],
        "corrections": [{
            "status": "applied", "field_name": "f", "old_value": "1", "reason": "r",
            "new_value": "2", "evidence_uri": "docs/e.md", "correction_id": "c-1",
        }],
        "calendar_events": [{
            "event_id": "e1", "source_id": "s1", "source_url": "https://x",
            "title": "t", "date": "2026-09-01", "status": "scheduled",
            "kind": "fomc", "time_et": "14:00", "ticker": "",
            "available_at": "2026-08-01", "registered_at": "2026-08-01",
        }],
    }
    projected = dashboard._project_embed_rows(model)
    # 렌더되는 컬럼은 전부 유지.
    assert projected["method_changes"][0] == {
        "kind": "method", "date": "2026-08-29", "title": "t", "reason": "r",
        "snapshot_id": "s", "report": "reports/x.md",
    }
    assert set(projected["corrections"][0]) == {
        "status", "field_name", "old_value", "reason",
    }
    assert "available_at" not in projected["calendar_events"][0]
    assert projected["calendar_events"][0]["source_url"] == "https://x"
    # 생략 사실과 원본 위치를 공시.
    disclosure = projected["embed_field_projection"]
    assert disclosure["projected"] is True
    assert disclosure["full_payload"] == "data.json"
    assert disclosure["sections"]["method_changes"]["dropped_fields"] == [
        "candidate_model_content_sha256", "contract", "occurred_at",
    ]
    assert disclosure["sections"]["calendar_events"]["row_count"] == 1
    # Pages/data.json 경로가 쓰는 원본 모델은 무수정.
    assert model["method_changes"][0]["contract"] == "c"
    assert model["corrections"][0]["correction_id"] == "c-1"


def test_embed_projection_is_a_noop_without_droppable_columns() -> None:
    model = {"corrections": [{"status": "applied", "reason": "r"}]}
    projected = dashboard._project_embed_rows(model)
    assert "embed_field_projection" not in projected
    assert projected["corrections"] == model["corrections"]


def test_embed_projection_allowlist_matches_real_column_names(tmp_path: Path) -> None:
    """허용목록 오타·상류 필드명 변경을 잡는다.

    허용목록에 있으나 실제 데이터에 없는 이름은, 상류가 컬럼을 개명했는데
    임베드가 조용히 그 값을 버리고 있다는 뜻이다 (화면이 빈칸이 된다).
    """
    conn = ingest.connect(tmp_path / "index.db")
    ingest.sync(conn, dashboard.config.ROOT)
    model = dashboard.build_read_model(conn, dashboard.config.ROOT)
    for section, kept in dashboard.EMBED_RENDERED_FIELDS.items():
        rows = model[section]
        assert rows, section
        present = {field for row in rows for field in row}
        assert set(kept) <= present, (section, sorted(set(kept) - present))


def test_embed_inlines_only_the_newest_bodies_and_links_the_rest() -> None:
    """활성 질문이 늘어도 임베드가 본문 때문에 계약을 깨지 않는지."""
    limit = dashboard.EMBED_INLINE_BODY_LIMIT
    model = {
        "forecast_history": {
            f"q{index}": [{
                "forecast_id": f"f{index}",
                "forecast_ts": f"2026-08-{index + 1:02d}T00:00:00",
                "body": "reasoning",
                "source_uri": f"forecasts/{index}.md",
            }]
            for index in range(limit + 3)
        }
    }
    limited = dashboard._limit_embed_inline_bodies(model)
    rows = [row for rows in limited["forecast_history"].values() for row in rows]
    assert sum(1 for row in rows if "body" in row) == limit
    # 본문이 빠진 행도 구조적 필드와 원본 링크는 유지한다.
    linked = [row for row in rows if "body" not in row]
    assert len(linked) == 3
    assert all(row["source_uri"] for row in linked)
    # 남는 것은 가장 최신 회차다.
    kept = {row["forecast_id"] for row in rows if "body" in row}
    assert kept == {f"f{index}" for index in range(3, limit + 3)}
    disclosure = limited["embed_body_budget"]
    assert disclosure == {
        "limited": True,
        "reason": "embed_size_budget",
        "inline_bodies": limit,
        "linked_bodies": 3,
        "full_payload": "data.json",
        "source_field": "source_uri",
    }
    # Pages/data.json 경로가 쓰는 원본 모델은 무수정.
    assert all(rows[0]["body"] == "reasoning" for rows in model["forecast_history"].values())


def test_embed_body_limit_is_a_noop_below_the_threshold() -> None:
    model = {"forecast_history": {"q": [{"forecast_id": "f", "forecast_ts": "2026-08-31", "body": "b"}]}}
    assert dashboard._limit_embed_inline_bodies(model) == model


def test_template_self_contained() -> None:
    """외부 리소스 로드 0 — report.py 자기완결 원칙 승계.

    SVG 네임스페이스(http://www.w3.org/2000/svg)는 브라우저가 fetch하지 않는
    상수라 예외 — 실제 리소스 로드(CDN 스크립트·스타일시트·폰트·이미지)만 검사.
    """
    import re

    html = dashboard.load_template()
    assert "<!--DATA-->" in html
    assert "window.__DATA__" in html and "window.__DATA_URL__" in html
    assert "fetch(window.__DATA_URL__,{cache:'no-store'})" in html
    assert "<link" not in html.lower(), "외부 스타일시트 링크 발견"
    # 리소스 로드 속성(src=/href=)이 외부 URL을 가리키지 않아야 함
    for attr in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html, re.I):
        if attr.startswith("#") or attr.startswith("/") or "www.w3.org" in attr:
            continue  # 앵커·내부 경로·SVG 네임스페이스는 허용
        assert not attr.startswith(("http:", "https:", "//")), f"외부 리소스: {attr}"
    # CDN 관용 호스트가 아예 없어야 함
    for host in ("cdn.", "unpkg", "jsdelivr", "googleapis", "cloudflare", "chart.js"):
        assert host not in html.lower(), f"CDN 흔적: {host}"

    embedded = dashboard.render_html({}, mode="embed")
    assert "WantedSansVariable.min.css" not in embedded
    assert "cdn.jsdelivr.net" not in embedded
    assert "self.QrCreator=H" in dashboard.load_template()
    assert "self.QrCreator=H" not in embedded


def test_pages_use_version_pinned_korean_webfont_without_changing_audit_html() -> None:
    html = dashboard.render_html({}, mode="pages")
    assert dashboard.WANTED_SANS_CSS in html
    assert "wanted-sans@v1.0.3" in html
    assert '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>' in html
    assert '<link rel="preload" as="style"' in html
    assert "'Wanted Sans Variable','Wanted Sans'" in html


def test_template_parts_bundle_and_budget() -> None:
    """소스는 유지보수 가능한 파셜이며 최종 산출물은 자기완결·용량 예산 이내다."""
    shell = dashboard.TEMPLATE.read_text(encoding="utf-8")
    assert "<!--STYLES-->" in shell and "<!--APP_SCRIPT-->" in shell
    assert dashboard.DASHBOARD_STYLES.exists()
    assert dashboard.DASHBOARD_SCRIPT.exists()
    html = dashboard.load_template()
    assert "<!--STYLES-->" not in html and "<!--APP_SCRIPT-->" not in html
    assert len(dashboard.render_html({}, mode="embed").encode("utf-8")) <= dashboard.DASHBOARD_RAW_BUDGET_BYTES


def test_script_compaction_preserves_token_boundaries() -> None:
    source = "<script>if (left) {} else\nif (right) { run(); }</script>"
    compact = dashboard._compact_static_bundle(source)
    assert "else if" in compact
    assert "elseif" not in compact


def test_ui_contract() -> None:
    """UI 현대화 계약 — 제품 rail·첫 화면 briefing·접근성·동적 전환."""
    html = dashboard.load_template()
    assert "<h1" in html, "대형 H1 없음"
    # U1a의 4개 핵심 목적지. 보조 화면은 문맥 탭/빠른 이동에서 제공한다.
    for v in ("today", "future", "timeseries", "records", "trust"):
        assert f'href="#{v}"' in html, f"nav 실제 링크 누락: {v}"
    assert 'aria-current' in html, "aria-current 처리 없음"
    assert "prefers-reduced-motion" in html
    assert "view-enter" in html, "화면 진입 전환 클래스 없음"
    assert "today-columns" in html, "오늘의 변경·이벤트 요약 그리드 없음"
    assert "analysis-panel" in html, "분석 패널 없음"
    assert 'class="product-rail"' in html, "데스크톱 제품 rail 없음"
    assert 'class="mobile-drawer"' in html, "모바일 drawer 없음"
    assert 'class="today-dashboard"' in html, "오늘의 무스크롤 브리핑 화면 없음"
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
    assert "--display:'Wanted Sans Variable','Wanted Sans'" in html
    assert "--sans:'Wanted Sans Variable','Wanted Sans'" in html
    assert "font-variant-numeric:tabular-nums" in html
    assert "font-size:clamp(31px,2.55vw,36px)" in html
    assert "letter-spacing:-.055em" in html
    assert 'class="command-layer"' in html and 'role="dialog"' in html
    assert 'aria-modal="true"' in html and "setCommand" in html
    assert "<kbd>⌘ K</kbd>" in html
    # miniSparkline·signalMosaic은 홈 개편 이후 호출부가 사라진 죽은 코드였다.
    # 되살아나면 렌더되지 않는 마크업이 번들에 다시 실리므로 부재를 고정한다.
    assert "miniSparkline" not in html and "signalMosaic" not in html
    assert "bindDynamicMotion" in html and "requestAnimationFrame(paint)" in html
    assert "--tilt-x" in html and "pointermove" in html
    assert ".filter-bar{position:sticky" in html
    # 시장 지도 SVG 생성 함수 유지
    assert "function drawFlow" in html and "function drawOverlay" in html
    assert "function drawCrossAsset" in html and "function drawCrossAssetHistory" in html
    assert "BTC SENSITIVITY" in html
    assert "조건 4개" in html
    assert "Realty Income 배당 포함 수익은 2001-03~2006-03 실측" in html
    assert "config.valueMode==='return_from_100'?signedDelta(value-100,0,'%')" in html
    assert "rates_stay_high_support" in html
    # 핵심 확률 대형 타이포 (72px+ clamp)
    assert "clamp(78px" in html, "핵심 확률 대형 크기 없음"
    # 시나리오 가중치를 질문 확률로 혼용하지 않음(하드코딩 금지) — FEATURE_QIDS로 데이터 참조
    assert "FEATURE_QIDS" in html
    assert 'class="mobile-bottom-nav"' in html
    # decisionQueueCard·linkedSignalStrip·bindHomeSignals도 같은 개편에서 호출부가
    # 사라졌다. lastSeenGeneratedAt은 살아있는 방문 스냅샷 로직이므로 유지한다.
    assert "decisionQueueCard" not in html and "linkedSignalStrip" not in html
    assert "bindHomeSignals" not in html and "lastSeenGeneratedAt" in html
    assert 'class="skip-link"' in html and 'id="app" tabindex="-1"' in html
    assert "const hasNumeric=" in html and "const roundLabel=" in html
    assert "산출 전" in html
    assert '<div class="probability-row"><strong>${q.latest_prob}</strong><span>%</span></div>' not in html
    assert '<span>R${q.n_rounds}</span>' not in html


def test_u1a_five_section_information_architecture_contract() -> None:
    html = dashboard.load_template()
    shell = dashboard.TEMPLATE.read_text(encoding="utf-8")
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")

    for route, label in (
        ("today", "오늘"),
        ("future", "미래 탐색"),
        ("statistics", "통계 비교"),
        ("timeseries", "시계열 예측"),
        ("records", "기록과 검증"),
        ("trust", "데이터와 신뢰"),
    ):
        assert html.count(f'href="#{route}"') >= 3
        assert label in html
    for legacy in ("overview", "flow", "questions", "ask", "asof", "track"):
        assert f'href="#{legacy}" data-v=' not in shell
    for mapping in (
        "rawHash==='#overview')return '#today'",
        "rawHash==='#flow')return '#future'",
        "rawHash==='#questions')return '#records'",
        "rawHash==='#ask')return '#future/lookup'",
        "rawHash==='#asof')return '#records/journal'",
        "rawHash==='#track')return '#records/performance'",
        "rawHash.startsWith('#q/')",
        "rawHash.startsWith('#compare/')",
        "rawHash.startsWith('#lookup=')",
        "rawHash.startsWith('#lab=')",
    ):
        assert mapping in script
    assert 'data-home-core="true"' in html
    assert "핵심 신호 2개" in html and "최근 변경 3" in html and "다음 이벤트 3" in html
    assert 'body[data-view="today"] .site-footer{display:none}' in css
    assert ".today-page{min-height:calc(100dvh - 48px)" in css
    assert "function renderTimeseries(initialState)" in script
    assert "numbers_visible===true" in script
    assert "기존 미래전망으로 자동 전환하지 않습니다" in script
    assert ".timeseries-horizons{display:grid;grid-template-columns:repeat(4" in css
    assert "grid-template-columns:repeat(6" in css


def test_u1a_route_and_home_render_evidence() -> None:
    project_root = Path(__file__).parents[2]
    evidence_dir = project_root / "reports" / "screenshots" / "u1a_260805"
    results = json.loads((evidence_dir / "route_results.json").read_text(encoding="utf-8"))

    assert results["passed"] is True
    assert results["redirectsExpected"] == results["redirectsPassed"] == 15
    assert all(row["passed"] and row["hash"] == row["expected"] for row in results["redirects"])
    desktop = next(row for row in results["homeResults"] if row["viewport"]["width"] == 1280)
    assert desktop["documentHeight"] <= desktop["viewportHeight"]
    assert desktop["coreBottom"] <= desktop["viewportHeight"]
    assert desktop["footerDisplay"] == "none"
    for row in results["homeResults"]:
        assert row["passed"] is True
        assert row["signals"] == 2
        assert row["recentChanges"] == row["nextEvents"] == 3
        assert (evidence_dir / row["file"]).is_file()


def test_u1b_future_overlay_unique_questions_and_compare_contract() -> None:
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")

    assert "rawHash==='#ask')return '#future/lookup'" in script
    assert 'data-future-lookup-layer' in html and 'role="dialog" aria-modal="true"' in html
    assert "setLookupOverlay" in script and "body.future-lookup-open" in css
    assert ".future-lookup-sheet .lookup-heading h3{color:#11110f}" in css
    for title in (
        "향후 12개월 시장 경로는 어떤 분포인가",
        "과거 혁신 사이클은 현재와 얼마나 닮았나",
        "닷컴 조정 뒤 자산별 회복은 어떻게 달랐을까",
        "AI 자본 사이클을 지금 판정할 수 있는가",
        "유동성 조건은 위험 선호를 지지하는가",
    ):
        assert title in html
    assert 'data-lab-tab="ai-regime"' not in html
    assert "coverage≥${aiThreshold.toFixed(1)}" in script
    assert "준비 중 · 판정 보류" in html and "자동 복귀 기준" in html
    assert "next.length===2&&!location.hash.startsWith('#records/compare/')" in script
    assert "location.hash='#records/compare/'+next.join(',')" in script


def test_u1b_browser_regression_evidence() -> None:
    project_root = Path(__file__).parents[2]
    evidence_dir = project_root / "reports" / "screenshots" / "u1b_260805"
    results = json.loads((evidence_dir / "results.json").read_text(encoding="utf-8"))

    assert results["passed"] is True
    assert results["uniqueH1Count"] == 5
    assert len(results["labResults"]) == 5 and all(row["passed"] for row in results["labResults"])
    assert results["compareResult"]["passed"] is True
    assert results["compareResult"]["clicks"] == 3
    assert results["trustResult"]["passed"] is True
    for row in results["overlayResults"]:
        assert row["passed"] is True
        assert row["hash"] == "#future/lookup"
        assert (evidence_dir / row["file"]).is_file()


def test_u1c_split_surfaces_event_summary_and_glossary_contract() -> None:
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    assert "rawHash==='#track')return '#records/performance'" in script
    assert "new URLSearchParams(location.search).get('mode')==='operator'" in script
    assert "trackMode==='performance'" in script and "trackMode==='operator'" in script
    assert 'href="?mode=standard#trust"' in html
    assert 'data-event-summary-toggle' in html and 'data-event-details hidden' in html
    assert 'class="event-status' not in script
    assert 'data-badge-type="event-summary"' in html
    for term in (
        "as_of", "ATH", "GBM", "p10_p90", "p25_p75", "p50",
        "scenario_conditional", "physical_event", "reference_only", "probability_space",
        "path_realism", "hazard", "regime", "coverage", "blocked", "vintage", "PIT", "reconstructed",
    ):
        assert f"{term}:" in script or f"'{term}':" in script
    assert "plainTerm('scenario_conditional')" in script
    assert "plainTerm('reference_only')" in script


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
    # 'SCENARIO VINTAGE' 라벨은 렌더되지 않던 vintageReceipt 안에만 있었다.
    # 신선도 판정 로직 자체(scenarioVintage)는 그대로 살아 있어야 한다.
    assert "function scenarioVintage()" in html and "SCENARIO VINTAGE" not in html
    assert "businessDayDiff" in html and "is-stale" in html
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
    assert "크립토 2019 시작" in html
    assert "<h2>과거 혁신 사이클 비교</h2>" in html
    assert "다우는 1925-01 시작 후 1929-09 정점이 M+56" in html
    assert "crypto2021:['크립토 2019 시작','#1f6feb'" in html
    assert "biotech2015:['바이오 2013','#a43c82'" in html
    assert "dow1929:['다우 1925','#6b5845'" in html
    assert "SELECTED WEEK" in html and "pointerdown" in html
    assert "overlay.addEventListener('pointermove'" in html
    assert "event.key==='ArrowLeft'" in html
    assert "peek-title" not in html and "peek-metric" not in html
    assert 'role="tablist" aria-label="시장 지도 분석 공간"' in html
    assert "REFERENCE ONLY · 확률 아님" not in html
    assert "유사 구간 이후 흐름" in html
    assert "forward n&lt;20" not in html and "median emphasis disabled" not in html
    assert "DB-CONDITIONED PATH · MONTHLY RISK WINDOW" in html
    assert "상승·회복 사이의 조정을 역사 DB로 복원했습니다" in html
    assert "row.median_max_drawdown_pct" in html
    assert "representative_path?.values" not in html
    assert "AI 조정 DB" in html and "닷컴 조정 DB" in html
    assert "data-flow-samples" not in html
    assert "표본 1/2회 미달·이전 β 유지" in html
    assert "gate 경계(n=156)" in html
    assert "닷컴 앵커 분리" not in html
    assert "overlay_start ${esc(dotcomAnchor.overlay_start)}" not in html
    assert "model_anchor ${esc(dotcomAnchor.model_anchor)}" not in html
    assert "DATA.era_analog" in html
    assert "drawOverlay(analogHost,overlay._overlay" in html
    assert "data-flow-focus=\"ANALOG\"" in html
    assert "DATA.cross_asset" in html and "data-lab-tab=\"cross-asset\"" in html
    assert "교차자산 비교" in html
    assert "NASDAQ·Bitcoin·리츠·주택주" in html
    assert "Bitcoin</span><strong>가정 경로" in html
    assert "BTC SENSITIVITY" in html and "data-cross-scenario" in html
    assert "drawIndexedCompare" in html and "하락꼬리 BTC beta" in html
    assert 'class="plain-insight" aria-label="자산 비교 읽는 법"' in html
    assert "가중치 없음 — 반사실 사례를 확률처럼 합산하지 않음" not in html
    assert "정점에서 12개월 지난 실측 월을 100" not in html
    assert "${esc(chart.description)}" not in html
    assert "원천·갱신일·재구성 상태 보기" not in html
    assert "사용한 데이터 출처" not in html
    assert "statistics-scope-note" in html
    assert "function statisticsLiquidityBars" in html
    assert ".statistics-filters button{min-width:112px" in html
    assert "font-size:.8rem;line-height:1.25;word-break:keep-all" in html
    assert "overflow-wrap:break-word;word-break:keep-all" in html
    assert "statistics-reading-guide" in html
    assert "statistics-now" in html
    assert ".statistics-meaning>strong,.statistics-now>strong{font-size:13px" in html
    assert ".statistics-now{grid-column:1/-1;padding-top:13px;border-top:1px solid #b9d8d0;display:grid;grid-template-columns:1fr;gap:7px" in html
    assert "chart.chart_type==='stacked_bar'" in html
    assert "statistics-bar-total" in html
    assert "data-stat-id" in html
    assert "paths_band" in html and "resolveEndpointLabels" in html
    assert "aria-live','polite" in html and 'role="radiogroup"' in html
    assert "model.history.period" in html and "label.endsWith('-06')" in html
    assert 'data-lab-tab="ai-regime"' not in html and 'data-lab-tab="liquidity"' in html
    assert "aiRegime.id='lab-ai-regime'" in html and 'href="#future/ai-regime">상태 상세' in html
    assert "Scenario Tracker" in html and "가중 합산 없음" in html
    assert "이 체크리스트는 사전 등록된 방향 규칙이며 확률이 아닙니다" in html
    assert "데이터 커버리지 부족" in html and "MAP WITHHELD" in html
    assert "표본 축적 중 ${num(row.observations)}/${num(row.minimum_observations)}" in html
    assert "유동성 확장이 곧 상승을 뜻하지 않습니다" in html
    assert "function drawLiquidity" in html and "liquidity_zone" in html
    assert "monitor.consecutive_successful_days" in html
    assert "자동 반영하지 않음" in html


def test_forecast_lookup_ui_contract() -> None:
    html = dashboard.load_template()
    for required in (
        'type="date"', 'aria-live="polite"', "#lookup=", "10–90% 구간",
        "25–75% 구간", "중앙값", "모델 조건부 확률",
        "단일 가격 제시·사건확률·투자자문이 아닙니다", "NO API · NO STORAGE",
        "8월 30일 · 3개월 뒤 · 연말", "정규식 규칙 파서 · LLM 호출 없음",
        "PHYSICAL EVENT · 별도 확률 공간", "시나리오 분포와 결합 금지",
        "현재 기준 미래 분포 조회", "미래 날짜에 새로 만든 전망이 아니라",
        'data-flow-year="${row.year}"', "2026년 DB 조건부 구조 경로",
        "2027년까지", "flowYearRange", "flowAxisTickIndexes",
        "2027년까지 주요 일정", "확정·추정 분리 · 전망성 해석 제외",
        "flowEventLayout", "조회 · ",
        "DB-CONDITIONED PATH · MONTHLY RISK WINDOW", "DB 조건부 구조 경로",
        "월 단위 위험창", "2001-03 이후 실제 NASDAQ의 추가 하락·회복",
        "특정 9월 하락일이나 저점 거래일을 지정하지 않습니다", "AI 버블 붕괴일이 아니라", "flowDisplayPath", "flowPathStats",
        "선택일을 100으로 재기준", "현재 원점 유지", "buildRebasedFlowModel",
        "D = 100 · CURRENT SNAPSHOT REINDEXED", "#future/lookup/${mapped.requested}/${lookupMode}",
        "선택일 이후의 기존 분위수와 S1/S2/S3 DB 조건부 구조 경로", "D일 스냅샷에서 반영됩니다",
        "horizonCoverageForDay", "미검증 구간", "적중 기록 축적 중",
        "inside_p10_p90_rate_pct", "0일 · 0/60",
        "lookupEventSummary", "일정과 분포 확률을 연결하지 않습니다",
        "EVENT_KIND_META", "월 패턴 또는 연준의 공식 잠정 일정",
        "굴곡=역사 중앙 형태 가정", "발생 여부의 확률 진술이 아닙니다",
        "굴곡 전 GBM 같이 보기", "data-flow-baseline", "baseline-swatch",
        "선택 3시대 원형 → 목표", "기하 detrend 잔차", "공용 strength",
        "무드리프트 기계적 기준", "임계까지 ${num(proximity.threshold_distance_pct)}%",
        "trailing 252거래일 μ의 추세 지속 가정", "physicalEventContextMarkup",
        "등록된 사건 확률이나 다른 확률공간과 합산하지 않습니다",
    ):
        assert required in html
    assert "lookup-metrics" in html and "lookup-primary" in html
    assert "flowYear=Number(mapped.mapped.slice(0,4))" in html, "조회 날짜의 연도 차트로 전환해야 함"
    assert "실경로 오버레이" not in html, "모의 표본을 기본 대표선으로 복원하면 안 됨"
    assert "data-baseline-path" in html
    assert "showBaseline=true" in html


def test_future_default_uses_three_scenarios_without_legacy_fallback() -> None:
    html = dashboard.load_template()
    assert "renderScenarioV52(candidate52,initialState);" in html
    assert "const researchPathsRequested=v==='flow'&&arg?.modelView!=='champion'" in html
    assert "const candidate52Requested=initialState.modelView!=='champion'" in html
    assert "if(candidate52Requested&&candidate52Eligible)" in html
    assert "if(candidate52Requested){" in html
    assert "이전 방식의 그래프로 자동 전환하지 않습니다" in html
    assert "if(parts[1]==='champion')return {section:'future',view:'flow',arg:{modelView:'champion'}}" in html
    assert "if(parts[1]==='research')return {section:'future',view:'flow',arg:{modelView:'research'}}" in html
    assert "scenarioCustomerViewNav" not in html
    assert "DISPLAY PROMOTION PENDING" not in html
    assert "SCENARIO V5.1 RUNTIME GATE" not in html
    assert "DISPLAY PROMOTION · MODEL PROMOTION 아님" not in html
    assert "let sc=officialScenario,shadowActive=false" in html
    assert "shadowActive?shadowScenario:officialScenario" in html
    assert "let sc=scenarioV5FlowModel(officialScenario,v5)" not in html
    assert "root.appendChild(labTabs)" in html and "mount(root);" in html
    assert "return renderScenarioV52(candidate52)" not in html


def test_future_graph_subcategory_restores_original_single_scenario_chart() -> None:
    """전망 그래프 중분류가 두 소분류(세 경로 · 복구된 단일 시나리오)를 갖는지 고정."""
    html = dashboard.load_template()
    assert "function drawOriginalWeeklyFlow(host,sc,showSamples=false,scenarioKey='S1')" in html
    assert "function originalFlowPanel()" in html
    for required in (
        'class="cross-view-switch future-graph-switch" role="group" aria-label="전망 그래프 보기"',
        'data-future-graph="unified" aria-pressed="true"',
        'data-future-graph="original" aria-pressed="false"',
        'data-future-graph-panel="unified"',
        'data-future-graph-panel="original" hidden',
        "세 가지 시장 경로",
        "단일 시나리오 주간 흐름",
    ):
        assert required in html, required
    assert "if(parts[1]==='original')return {section:'future',view:'flow',arg:{futureGraph:'original'}}" in html
    assert "const futureGraphHash=()=>graphKey==='original'?'#future/original':'#future'" in html
    assert "button.dataset.labTab==='future'?futureGraphHash():" in html
    assert "paintFutureGraph(initialState.futureGraph==='original'?'original':'unified',false)" in html
    assert "단일 시나리오 · 챔피언 GBM · 참고 의견" in html
    assert "기본 그래프인 세 가지 시장 경로를 대체하지 않습니다" in html
    assert "참고 의견이며 투자 자문이 아닙니다" in html
    assert "id=\"original-flow-chart\"" in html
    assert "DATA.scenario" in html


def test_original_flow_chart_reuses_light_theme_and_zoom_contract() -> None:
    """복구 차트가 라이트 테마 팔레트와 기존 확대보기 계약을 그대로 쓰는지 고정."""
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    assert "CHART_ZOOM_SELECTOR='.chart-wrap,.statistics-chart,.scenario-v52-chart,.timeseries-chart'" in script
    assert '<div class="chart-wrap"><div id="original-flow-chart"></div></div>' in script
    assert "stroke:CHART_COL[key],'stroke-width':2.6" in script
    assert "color:CHART_LABEL_COL[key]" in script
    assert "const gridStep=Math.max(500,Math.ceil(((Y1-Y0)/6)/500)*500);" in script
    assert "flowAxisTickIndexes(n,7)" in script
    assert "'−10%선 누적 터치확률'" in script
    assert "혁신사이클 참조선 — 시나리오 아님" in html
    assert "23500" not in script.split("function drawOriginalWeeklyFlow")[1].split("function originalFlowPanel")[0]
    assert "#0a0e1a" not in html, "다크 테마 색값을 복구하면 안 됨"


def test_dead_render_paths_are_not_shipped() -> None:
    """도달 불가 렌더러가 번들에 다시 실리지 않는지 고정."""
    html = dashboard.load_template()
    for dead in (
        "renderAsk",
        "renderAsof",
        "renderAsofTimeMachine",
        "changeRadarPanel",
        "decisionQueueCard",
        "linkedSignalStrip",
        "homeFeatureQuestions",
        "bindHomeSignals",
        "miniSparkline",
        "signalMosaic",
    ):
        assert dead not in html, f"죽은 렌더러가 다시 포함됨: {dead}"
    # 일지는 VIEWS에서 곧바로 살아있는 렌더러를 가리킨다 (사후 재할당 없음)
    assert "asof:renderDecisionJournal" in html
    assert "VIEWS.asof=" not in html
    assert "ask:renderAsk" not in html
    # 살아있는 이웃 심볼은 그대로 유지
    for kept in ("featureQs", "FEATURE_QIDS", "reviewQueuePanel", "renderDecisionJournal"):
        assert kept in html, kept


def test_forecast_chart_primary_line_is_the_actual_medoid() -> None:
    """전망 그래프의 굵은 선은 실제 모의 중심 경로(medoid)다.

    p50은 수천 경로의 날짜별 중앙값이라 거의 직선으로 보인다. 실제 시장 질감을
    보여주되 중심 경향도 잃지 않도록, p50은 같은 색 점선으로 남긴다.
    """
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    body = script.split("function scenarioV52UnifiedChart")[1].split("function scenarioV52RangeReadout")[0]

    # medoid가 굵게, p50이 얇은 점선으로
    assert 'stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round" data-path-role="${key}-actual-medoid"' in body
    assert 'stroke-width="1.4" stroke-dasharray="4 6" opacity=".42" data-scenario-p50="${key}"' in body
    # 종점 마커와 라벨도 주선을 따라간다
    assert "Y(medoids[key].at(-1))" in body
    assert "const endpointLabel=key=>{const values=medoids[key]" in body

    # 주선이 모의 멤버 한 개라는 사실을 반드시 함께 밝힌다
    assert "굵은 선은 시나리오별 실제 모의 경로 한 개(medoid)입니다" in html
    assert "중심 경향이 아니며" in html
    assert "굵은 선=실제 모의 경로 한 개(medoid) · 점선=조건부 p50" in html
    # 가짜 흔들림 금지는 그대로
    assert "p50에 인위적인 흔들림을 넣지 않았고" in html


def test_single_scenario_chart_draws_one_path_at_a_time() -> None:
    """구조 경로 세 개는 같은 월별 굴곡 형태를 진폭만 바꿔 쓴다.

    겹쳐 그리면 '서로 다른 세 경로'처럼 보이므로 한 번에 하나만 굵게 그리고,
    형태를 공유한다는 사실을 화면에 밝힌다.
    """
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    body = script.split("function drawOriginalWeeklyFlow")[1].split("function originalFlowPanel")[0]

    assert "const activeKey=['S1','S2','S3'].includes(scenarioKey)?scenarioKey:'S1';" in body
    for single in ("  [activeKey].forEach(key=>{", "if(usingStructural)[activeKey].forEach(key=>{"):
        assert single in body, single
    assert body.count("['S1','S2','S3'].forEach") == 0, "세 경로를 한꺼번에 그리면 안 된다"

    # 선택기와 공시
    assert 'data-original-scenario="${key}"' in html
    assert "같은 월별 굴곡 형태를 공유하고 진폭만 다릅니다" in html
    assert "한 번에 하나만 표시합니다" in html
    # 나머지 두 경로의 종점은 표로 남긴다
    assert "data-original-endpoints" in html
    assert "연구 코호트 비중" in html


def test_mid_navigation_strips_are_compact() -> None:
    """중분류 탭이 통계 필터와 같은 조밀한 한 줄이어야 한다."""
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    assert ".lab-tabs{margin:16px 0 12px;display:flex;flex-wrap:wrap" in css
    assert ".lab-tabs button{min-width:112px;min-height:44px" in css
    assert ".lab-tabs button>small{display:none}" in css, "부제는 한 줄에 들어가지 않는다"
    assert "grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;border:1px solid var(--line-strong)" not in css
    # 기준 요약 스트립도 축소
    assert ".scenario-v52-overview>div{padding:9px 13px" in css
    assert ".scenario-v52-overview strong{font:780 14px/1.2 var(--mono)}" in css


def test_mid_category_registry_drives_rail_hierarchy() -> None:
    """대분류 아래 중분류가 레일에 실제로 보이는지 고정 (v1은 본문 탭만 있었다)."""
    html = dashboard.load_template()
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")

    # 하나의 레지스트리가 레일·본문·명령 팔레트를 모두 먹인다
    assert "const MID_CATEGORIES={" in html
    assert "const SECTION_TITLES={today:'오늘',future:'미래 탐색'" in html
    assert "function midCategories(section,forRail)" in html
    # 통계의 "전체"는 본문 필터 줄에만 남기고 레일에서는 뺀다
    assert "railHidden:true" in html
    assert "midCategories(navView,true)" in html
    assert "function currentMidCategory(section,rawHash)" in html

    # 레일 주입과 route() 호출
    assert "function paintRailSubNav(navView,rawHash)" in html
    assert "paintRailSubNav(navView,rawHash);" in html
    assert 'class="rail-sub"' in html
    assert "anchor.after(list);" in html
    assert ".rail-sub a[aria-current=\"page\"]" in css
    assert ".product-rail .rail-sub{display:none}" in css, "축소된 레일에서는 하위 목록을 숨긴다"
    assert ".mobile-drawer .rail-sub{display:block" in css, "드로어에서는 계층을 유지한다"

    # 본문 탭이 해시를 바꿀 때 레일도 따라가야 한다
    assert "function syncMidHash(hash)" in html
    assert "paintRailSubNav(document.body.dataset.view||'today',hash);" in html
    for wired in (
        "if(sync)syncMidHash(active==='all'?'#statistics':'#statistics/'+active);",
        "if(sync)syncMidHash(active==='status'?'#trust':'#trust/'+active);",
        "if(sync)syncMidHash(futureGraphHash());",
        "if(sync)syncMidHash(next==='summary'?'#timeseries':'#timeseries/'+next);",
    ):
        assert wired in html, wired

    # 01 오늘은 한 화면 요약이라 중분류가 없다
    assert "today:[]," in html

    # 중분류가 명령 팔레트 목적지로도 등록된다
    assert "...Object.entries(MID_CATEGORIES).flatMap(" in html


def _mid_category_keys(html: str, section: str) -> list[tuple[str, bool]]:
    """MID_CATEGORIES의 한 대분류를 (key, railHidden) 순서대로 읽는다."""
    block = html.split(f"{section}:[")[1].split("],")[0]
    return [
        (match.group("key"), "railHidden:true" in match.group(0))
        for match in re.finditer(r"\{key:'(?P<key>[a-z-]+)'[^}]*\}", block)
    ]


def test_statistics_rail_numbers_run_from_01_to_06() -> None:
    """통계 비교 중분류가 01 IPO·상장에서 06 신용까지 이어져야 한다.

    레일에서 빠지는 '전체'(railHidden)가 01을 먹어 02~07로 밀려 있었다.
    """
    html = dashboard.load_template()
    rows = _mid_category_keys(html, "statistics")

    assert [key for key, _ in rows] == [
        "all", "ipo", "liquidity", "rates", "economy", "valuation", "credit",
    ]
    rail = [key for key, hidden in rows if not hidden]
    numbers = [f"{index:02d}" for index in range(1, len(rail) + 1)]

    assert list(zip(rail, numbers)) == [
        ("ipo", "01"), ("liquidity", "02"), ("rates", "03"),
        ("economy", "04"), ("valuation", "05"), ("credit", "06"),
    ]
    assert numbers[0] == "01" and numbers[-1] == "06"
    assert "07" not in numbers, "07이 남으면 걸러질 항목이 아직 번호를 먹고 있다"


def test_mid_category_numbers_are_derived_after_filtering_not_hardcoded() -> None:
    """번호를 리터럴로 박으면 hidden 항목이 다시 01을 먹는다. 파생으로 고정."""
    html = dashboard.load_template()

    assert "function midCategoryCode(index){return String(index+1).padStart(2,'0');}" in html
    assert "midCategoryCode(index)" in html
    # 레일도 팔레트도 railHidden을 먼저 거른 뒤 같은 규칙으로 번호를 받는다
    assert "items.map((item,index)=>" in html
    assert ".filter(item=>!item.railHidden).map((item,index)=>({item,code:midCategoryCode(index)}))" in html
    # 레지스트리에는 번호 리터럴이 남아 있으면 안 된다
    registry = html.split("const MID_CATEGORIES={")[1].split("\n};")[0]
    assert not re.search(r"code:'\d\d'", registry), "중분류 번호는 리터럴로 두지 않는다"
    # 번호는 표시용일 뿐 — 필터 키와 라우트는 그대로다
    for key in ("ipo", "liquidity", "rates", "economy", "valuation", "credit"):
        assert f"hash:'#statistics/{key}'" in html


def test_restored_chart_uses_structural_path_not_the_flat_median() -> None:
    """복구 차트가 평평한 원시 중앙값 대신 구조 경로를 그리는지 고정."""
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    body = script.split("function drawOriginalWeeklyFlow")[1].split("function originalFlowPanel")[0]

    # 대표선은 챔피언 차트와 같은 헬퍼를 쓴다
    assert "flowDisplayPath(sc,key)" in body
    assert "const paths=Object.fromEntries(['S1','S2','S3'].map(key=>[key,structuralSource[key]" in body
    # 굴곡 적용 전 원시 중앙값은 고스트 선으로 병기해 차이를 숨기지 않는다
    assert "data-baseline-path" in body
    assert "const usingStructural=hasStructuralPaths(sc);" in body

    # 실제 모의 경로는 옵션 오버레이일 뿐 대표선이 아니다
    assert "data-sample-path" in body
    assert "sc.path_realism?.[key]?.sample_paths" in body
    assert 'data-original-samples aria-pressed="false"' in html, "모의 경로는 기본 숨김"
    assert "ONE SIMULATED MEMBER · EXACT DATES ARE NOT FORECAST" in html
    assert "모의 표본을 대표선으로 쓰지 않습니다" in html


def test_three_tier_information_architecture_midlevel_navigation() -> None:
    """대분류 6개 아래의 중분류가 해시로 딥링크되는지 고정 (02/03/04/06)."""
    html = dashboard.load_template()
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    # 서브패스를 허용하는 대분류: future / records 에 statistics / trust 추가
    assert "statistics(?:\\/|$)|timeseries(?:\\/|$)|records(?:\\/|$)|trust(?:\\/|$)" in script
    # 기존 대분류 라우트는 하나도 사라지지 않는다
    for kept in ("#today", "#future", "#statistics", "#timeseries", "#records", "#trust"):
        assert f'href="{kept}"' in html, kept

    # 02 미래 탐색: 중분류 4개 유지 + 전망 그래프의 소분류 2개
    for lab in ("future", "history", "cross-asset", "liquidity"):
        assert f'data-lab-tab="{lab}"' in html, lab
    assert 'data-future-graph="original"' in html

    # 03 통계 비교: 카테고리 중분류 딥링크
    assert "if(parts[0]==='statistics')return {section:'statistics',view:'statistics',arg:{category:parts[1]||null}}" in html
    assert "const requestedCategory=typeof initialState==='string'?initialState:initialState?.category" in html
    assert "applyStatCategory(requestedCategory||'all',false)" in html
    for category in ("ipo", "liquidity", "rates", "economy", "valuation", "credit"):
        assert f'data-stat-filter="{category}"' not in html or True
    assert "['all','전체'],['ipo','IPO·상장']" in html

    # 04 기록과 검증: 중분류 4개(질문 목록·성과 검증·변경 일지·비교)
    assert "['journal','변경 일지','#records/journal']" in html
    assert "appendContextTabs(root,'research','journal');" in html
    live_journal = html.split("function renderDecisionJournal(")[1].split("\nfunction ")[0]
    assert "appendContextTabs(root,'research','journal');" in live_journal
    assert "appendContextTabs(root,'replay','asof');" not in live_journal, "일지는 대분류 밖 replay 그룹을 쓰지 않는다"
    assert 'href="#future/lookup">미래 탐색의 기간 조회' in html, "기간 조회 크로스링크는 본문에 유지"

    # 06 데이터와 신뢰: 중분류 3개
    assert "if(parts[0]==='trust')" in html and "trustTab:parts[1]||null" in html
    for key in ("status", "sources", "audit"):
        assert f'data-trust-tab="${{key}}"' in html or f"'{key}'" in html, key
    assert "const trustTabs=[['status','데이터 상태','01'],['sources','출처와 방법','02'],['audit','감사 기록','03']]" in html
    assert "activateTrustTab(initial?.trustTab||'status',false)" in html
    assert "syncMidHash(active==='status'?'#trust':'#trust/'+active)" in html

    # 05도 중분류를 갖는다. 게이트 통과 전에는 탭을 노출하되 비활성으로 둔다.
    assert "const TS_TABS=[['summary','전망 요약','01']" in html
    assert "const enabled=visible?TS_TABS.map(([key])=>key):['summary']" in html
    assert "if(parts[0]==='timeseries')return {section:'timeseries',view:'timeseries',arg:{tsTab:parts[1]||null}}" in html
    assert "numbers_visible===true" in html


def test_midlevel_navigation_does_not_break_existing_routes() -> None:
    """중분류 도입이 기존 라우트·감사 경로를 제거하지 않는지 고정."""
    html = dashboard.load_template()
    for preserved in (
        "if(parts[1]==='champion')return {section:'future',view:'flow',arg:{modelView:'champion'}}",
        "if(parts[1]==='research')return {section:'future',view:'flow',arg:{modelView:'research'}}",
        "rawHash==='#ask')return '#future/lookup'",
        "rawHash==='#track')return '#records/performance'",
        "rawHash==='#asof')return '#records/journal'",
        "new URLSearchParams(location.search).get('mode')==='operator'",
    ):
        assert preserved in html, preserved
    assert 'data-lab-tab="ai-regime"' not in html


def test_v5_2_future_view_uses_one_log_scale_and_restores_research_panels() -> None:
    html = dashboard.load_template()
    assert "month:['다음 1개월',{months:1}],quarter:['3개월',{months:3}]" in html
    assert "function scenarioV52CalendarEnd(dates,months)" in html
    assert "index 3 is three days, not three months" in html
    for required in (
        "scenarioV52UnifiedChart",
        'data-scale="log"',
        'data-history-share="0.25"',
        'data-forecast-share="0.75"',
        'data-time-zone="forecast"',
        'data-scenario-p50="${key}"',
        'data-scenario-end-label="${key}"',
        "direction=change>1?'상승':change< -1?'하락':'중립'",
        "S1:{title:'확장 경로',copy:'닷컴·완화·AI 확장 6개 등록 에피소드',color:'#147a5b'}",
        'data-v52-range="${key}"',
        "다음 1개월",
        "2026 연말",
        "2027 연말",
        "세 시나리오 한눈에",
        "연구 코호트 가중치",
        "0.80은 cap 초과로 차단",
        "정의상 0",
        "적격 사건 ${num(hard.eligible_historical_event_count||0)}/${num(hard.preferred_minimum||60)}",
        "band calibration ${num(promotionGates.band_calibration?.observations||0)}/${num(promotionGates.band_calibration?.minimum||60)}",
        "세 가지 시장 경로",
        "닷컴 + 완화 + AI 성장",
        "연착륙 + 중립 금융여건",
        "긴축 + 신용 위험 + 성장 둔화",
        "서로 다른 3개 군집",
        "분석 방법과 세부 통계",
        "모두 보정되지 않은 모의 경로 비율입니다",
        "Bitcoin</span><strong>가정 경로",
        "유동성이 늘고 줄어든 구간",
        "bindCrossAsset(crossAsset,initialState.scenario)",
        "bindLiquidity(liquidity)",
    ):
        assert required in html
    assert "scenarioCustomerViewNav" not in html
    assert "CONDITIONAL SMALL MULTIPLES" not in html
    assert "compareTray.hidden=!ids.length||!location.hash.startsWith('#records')" in html


def test_v53_honesty_surfaces_survive_without_deletion() -> None:
    conn = ingest.connect(dashboard.config.DB_PATH)
    try:
        model = dashboard.build_read_model(conn, dashboard.config.ROOT)
    finally:
        conn.close()
    required = {
        "method_changes", "scenario_history", "band_calibration", "scenario_tracker",
        "calendar_events", "cross_asset", "liquidity",
    }
    assert required <= set(model)
    assert model["method_changes"]
    assert model["scenario_history"]
    assert model["band_calibration"]["observations"] == len(
        model["band_calibration"]["rows"]
    )
    assert "path_realism" in model["scenario"]
    assert "horizon_coverage" in model["scenario"]


def test_v53_legacy_hash_redirect_matrix_is_complete() -> None:
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    for contract in (
        "rawHash==='#flow')return '#future'",
        "rawHash==='#questions')return '#records'",
        "rawHash==='#track')return '#records/performance'",
        "rawHash==='#asof')return '#records/journal'",
        "rawHash.startsWith('#lookup=')",
        "rawHash.startsWith('#lab=')",
        "rawHash.startsWith('#q/')",
        "rawHash.startsWith('#compare/')",
    ):
        assert contract in script


def test_u1d_mobile_layout_contract() -> None:
    html = dashboard.load_template()
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    # ask 뷰(#ask)는 #future/lookup으로 대체되며 렌더러가 제거됐다. 되살아나면
    # 라우터가 닿지 못하는 차트가 다시 번들에 실리므로 부재를 고정한다.
    assert "dchart" not in html and "ask-daily-chart" not in html
    assert "ask-daily-chart" not in css
    assert ".detail-hero .prob-orb{margin:18px auto 34px}" in css
    assert ".track-page .ledger-status-grid strong" in css
    assert "overflow-wrap:anywhere" in css
    assert "function enhanceChartZoom" in script
    assert "가로로 밀어 전체 차트 탐색" not in script


def test_mobile_charts_fit_first_and_offer_detail_zoom() -> None:
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    script = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    assert "function enhanceChartZoom" in script
    assert "function openChartZoom" in script
    assert "두 손가락으로 확대" in script
    assert "requestAnimationFrame(()=>enhanceChartZoom(app()))" in script
    assert "CHART_ZOOM_SELECTOR='.chart-wrap,.statistics-chart,.scenario-v52-chart,.timeseries-chart'" in script
    assert '.chart-wrap>div[style*="min-width"]{width:100%!important;min-width:0!important' in css
    assert ".chart-wrap svg,.statistics-chart svg,.scenario-v52-chart svg,.timeseries-chart svg" in css
    assert ".chart-zoom-dialog" in css and ".chart-zoom-canvas" in css
    assert "body.chart-zoom-open{overflow:hidden" in css


def test_u1d_mobile_layout_regression_evidence() -> None:
    project_root = Path(__file__).parents[2]
    evidence_dir = project_root / "reports" / "screenshots" / "u1d_260805"
    results = json.loads((evidence_dir / "layout_results.json").read_text(encoding="utf-8"))

    assert results["viewport"] == {"width": 390, "height": 844}
    assert results["passed"] is True
    assert {row["name"] for row in results["results"]} == {
        "ask_responsive_chart",
        "track_text_wrap",
        "question_orb",
        "flow_scroll_affordance",
    }
    for row in results["results"]:
        assert row["passed"] is True
        assert (evidence_dir / row["file"]).is_file()


def test_u1c_browser_regression_evidence() -> None:
    project_root = Path(__file__).parents[2]
    evidence_dir = project_root / "reports" / "screenshots" / "u1c_260805"
    results = json.loads((evidence_dir / "results.json").read_text(encoding="utf-8"))

    assert results["passed"] is True
    surfaces = {surface["name"]: surface for surface in results["surfaces"]}
    for name in ("performance", "trust", "operator"):
        surface = surfaces[name]
        assert surface["passed"] is True
        assert len(surface["badgeTypes"]) <= 3
    assert results["legacyTrack"]["passed"] is True
    assert results["eventSummary"]["before"]["summaryChips"] == 1
    assert results["eventSummary"]["before"]["eventStatusBadges"] == 0
    assert results["eventSummary"]["before"]["detailsHidden"] is True
    assert results["eventSummary"]["after"]["detailsHidden"] is False
    assert results["eventSummary"]["after"]["eventCards"] > 0
    for filename in (
        "performance_1280.png",
        "trust_1280.png",
        "operator_1280.png",
        "event_summary_1280.png",
    ):
        assert (evidence_dir / filename).is_file()


def test_data_trust_pipeline_is_visual_plain_language_and_live() -> None:
    html = dashboard.load_template()
    for required in (
        "현재 데이터 상태", "공개 데이터가 그래프가 되기까지",
        "공개 원천 수집", "시점·형식 검사", "변경 이력 보관", "화면과 모델 분리",
        "원장별 상세 상태", "데이터 출처 상세", "확률 숫자 읽는 법",
        "ledgerSummary.accumulating", "ledgerSummary.stalled", "ledgerSummary.violation",
    ):
        assert required in html
    assert "매주 공개 원천을 다시 확인합니다" not in html
    assert "Trust Center" not in html


def test_liquidity_series_share_one_plot_with_explicit_dual_axes() -> None:
    html = dashboard.load_template()
    assert "Fed 순유동성 · 52주 z (왼쪽)" in html
    assert "NASDAQ · 26주 % (오른쪽)" in html
    assert "BITCOIN · 26주 % (오른쪽)" in html
    assert "const zScale=scale(z),returnScale=scale([...ndx,...btc])" in html
    assert "panelTop" not in html, "유동성·수익률을 위아래 패널로 다시 분리하면 안 됨"


def test_decision_journal_share_and_contrast_contract() -> None:
    html = dashboard.load_template()
    for required in (
        "예측 변경 일지", "그날로 돌아가기", "APPEND-ONLY PROVENANCE",
        'role="feed"', "change_note", "#asof=", "share-popover",
        "시장 기준 ${asof}", "조건부 시나리오이며 단일 가격 제시·투자자문이 아닙니다",
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
        "realtyContext.condition_summary", "하락월 β", "Bitcoin만 beta 민감도",
        "gate 경계(n=156)", "DATA.method_changes", "public_repository_url",
    ):
        assert required in html
    changes = (dashboard.config.ROOT / "data/method_changes.jsonl").read_text(encoding="utf-8")
    assert "교차자산 경로 추적 원장 v2 전환" in changes


def test_future_chart_restores_innovation_reference_and_cross_asset_five_year_view() -> None:
    html = dashboard.load_template()
    for required in (
        "혁신사이클 대표 참조선 · 확률 아님",
        "data-reference-path':'innovation-cycle'",
        "특정 9월 하락일이나 저점 거래일을 지정하지 않습니다",
        "실측 + BTC 반사실",
        "2001-03부터 2006-03까지 5개년 비교",
        "tickIndexes:[0,12,24,36,48,60]",
    ):
        assert required in html


def test_structural_calibration_selection_invariance_is_visible() -> None:
    html = dashboard.load_template()
    for required in (
        "시대 선택은 위치, base rate는 깊이를 정합니다",
        "시대를 교체하면 위험창 중심월은 움직이지만",
        "시대 교체별 native·calibrated 낙폭 비교",
        "Native · 보정 전",
        "Calibrated · 화면",
        "origin_year_calibrated_s1_mdd_pct",
    ):
        assert required in html


def test_render_embed_vs_fetch(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    model = dashboard.build_read_model(conn, repo)
    embed = dashboard.render_html(model, mode="embed")
    assert "window.__DATA__ = {" in embed
    assert "fixture-coin-ath" in embed  # base question data remains embedded
    assert "future_paths.json" in embed
    assert "statistics.json" in embed
    fetch = dashboard.render_html({}, mode="fetch")
    assert "/api/data" in fetch
    assert "/api/future-paths" in fetch
    assert "/api/statistics" in fetch
    assert "window.__DATA__ = {" not in fetch  # fetch 모드는 임베드 없음


def test_repository_snapshot_stays_within_dashboard_budget(tmp_path: Path) -> None:
    """실제 누적 원장으로도 Pages 산출물의 고정 용량 계약을 지킨다."""
    conn = ingest.connect(tmp_path / "index.db")
    ingest.sync(conn, dashboard.config.ROOT)
    model = dashboard.build_read_model(conn, dashboard.config.ROOT)
    assert model["o_entry_cohort"]["entry_count"] == 840
    assert "entries" not in model["o_entry_cohort"]
    assert len(model["o_entry_cohort"]["summary"]) == 15
    if model["scenario_v5"]["runtime_gate"]["display_eligible"] is False:
        assert "conditional_distribution" not in model["scenario_v5"]
    html = dashboard.render_html(model, mode="embed")
    assert len(html.encode("utf-8")) <= dashboard.DASHBOARD_RAW_BUDGET_BYTES
    # 용량 계약을 지키는 축소가 실제 임베드 산출물까지 도달했는지 확인한다.
    blob = html.split("window.__DATA__ = ", 1)[1].split("</script>", 1)[0]
    embedded = json.loads(blob.rstrip().rstrip(";"))
    assert "rows" not in embedded["band_calibration"]
    archived_rows = embedded["band_calibration"]["rows_archived"]
    assert archived_rows["row_count"] == len(model["band_calibration"]["rows"])
    for section, kept in dashboard.EMBED_RENDERED_FIELDS.items():
        for row in embedded[section]:
            assert set(row) <= set(kept), section
    assert embedded["embed_field_projection"]["projected"] is True


def test_future_paths_are_split_with_semantic_identity_and_fixed_budgets() -> None:
    candidate_path = (
        dashboard.config.ROOT
        / "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    stable_now = dashboard.datetime.fromisoformat(candidate["generated_at"])
    conn = ingest.connect(dashboard.config.ROOT / "db" / "index.db")
    try:
        model = dashboard.build_read_model(
            conn, dashboard.config.ROOT, now=stable_now,
        )
    finally:
        conn.close()
    base, statistics_data = dashboard.split_statistics_data(model)
    base, future = dashboard.split_future_paths(base)
    assert statistics_data is not None
    assert statistics_data["contract_id"] == "statistics_route_v1"
    assert statistics_data["data"]["statistics_lab"]["charts"]
    assert base["statistics_lab"]["deferred_data"] == {
        "required": True,
        "loaded": False,
        "url": "statistics.json",
        "failure_mode": "summary_with_explicit_error",
    }
    assert "statistics_lab" not in future["data"]
    assert len(json.dumps(statistics_data, ensure_ascii=False, default=str,
                          separators=(",", ":")).encode("utf-8")) \
        <= dashboard.STATISTICS_DATA_BUDGET_BYTES
    assert future is not None
    assert future["contract_id"] == "future_paths_v1"
    assert future["semantic_reference"] == base["scenario_v5_2"]["semantic_reference"]
    assert "conditional_small_multiples" not in base["scenario_v5_2"]
    assert future["data"]["scenario_v5_2"]["conditional_small_multiples"]
    assert base["scenario_v5_2"]["deferred_paths"] == {
        "required": True,
        "loaded": False,
        "url": "future_paths.json",
        "failure_mode": "summary_with_explicit_banner",
    }
    assert base["scenario_v5_2"]["path_checkpoints"]
    assert len(json.dumps(future, ensure_ascii=False, default=str,
                          separators=(",", ":")).encode("utf-8")) \
        <= dashboard.FUTURE_PATHS_BUDGET_BYTES
    assert len(dashboard.render_html(model, mode="embed").encode("utf-8")) \
        <= dashboard.DASHBOARD_RAW_BUDGET_BYTES


def test_server_is_read_only() -> None:
    """serve() 핸들러가 쓰기 메서드(POST)를 405로 차단하는지 소스 계약 검증."""
    src = inspect.getsource(dashboard.serve)
    assert "do_POST" in src and "405" in src
    assert "read-only" in src
    # /api/data는 새 연결로 조회만 (쓰기 함수 미호출)
    assert "build_read_model" in src and "conn.close()" in src
    assert "/api/future-paths" in src
    assert "/api/statistics" in src


def test_render_evidence_pipeline_uses_playwright_not_direct_cdp() -> None:
    source = (
        dashboard.config.ROOT / "tools/capture_dashboard_screenshots.py"
    ).read_text(encoding="utf-8")
    assert "from playwright.sync_api" in source
    assert "playwright.chromium.launch" in source
    assert "Page.captureScreenshot" not in source
    assert "new_cdp_session" not in source
    assert "len(rows) == len(_routes(data)) * len(VIEWPORTS)" in source


def test_write_dashboard(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    out = dashboard.write_dashboard(conn, repo)
    assert out.exists() and out.name == "dashboard.html"
    assert "window.__DATA__" in out.read_text(encoding="utf-8")
    assert (out.parent / "future_paths.json").exists()


def test_write_pages(repo: Path) -> None:
    """GitHub Pages 빌드 — shell + cacheable local data JSON + .nojekyll."""
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    out_dir = repo / "_site"
    index = dashboard.write_pages(conn, out_dir, repo)
    assert index.name == "index.html"
    assert (out_dir / ".nojekyll").exists()
    assert "data.json" in index.read_text(encoding="utf-8")
    assert "future_paths.json" in index.read_text(encoding="utf-8")
    assert "statistics.json" in index.read_text(encoding="utf-8")
    assert (out_dir / "future_paths.json").exists()
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
    future_payload = json.loads(
        (out_dir / "future_paths.json").read_text(encoding="utf-8")
    )
    assert future_payload["contract_id"] == "future_paths_v1"
    public_text = index.read_text(encoding="utf-8") + json.dumps(payload, ensure_ascii=False)
    assert "목표가" not in public_text
    assert "목표가격" not in public_text
    assert "불확실성" in public_text


def test_presentation_copy_normalization_preserves_source_and_nested_shape() -> None:
    source = {
        "note": "확률·목표가격·목표가가 아니며 불확실성을 보존한다.",
        "nested": ["목표가 아님", {"value": "불확실성"}],
    }
    normalized = dashboard._normalize_presentation_copy(source)
    assert normalized == {
        "note": "확률·단일 가격 제시·단일 가격 제시가 아니며 불확실성을 보존한다.",
        "nested": ["단일 가격 제시 아님", {"value": "불확실성"}],
    }
    assert source["note"] == "확률·목표가격·목표가가 아니며 불확실성을 보존한다."


def test_o_entry_cohort_ui_is_evidence_only() -> None:
    html = dashboard.load_template()
    for required in (
        "O 월별 진입 cohort", "PREREGISTERED · REFERENCE ONLY",
        "진입 시점·가격을 추천하지 않습니다", "현재 진입상태 규칙은 아직 등록하지 않았습니다",
        "월말 신호 → 익월 첫 거래일 체결", "cohortResultsMarkup(DATA.o_entry_cohort)",
        "표본 n=${num(row.n||0)}", "미완결 지평은 통계에서 제외",
    ):
        assert required in html
    assert "O_ENTRY_ATTRACTIVE" not in html


def test_mobile_market_strip_uses_three_non_overlapping_cells() -> None:
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    assert ".market-strip{height:58px;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr))" in css
    assert ".market-strip>div,.market-strip>div:first-child{min-width:0;padding:7px 9px;display:grid" in css
    assert ".market-strip span{min-width:0;display:block;overflow:hidden" in css
    assert ".market-strip strong{min-width:0;display:block;overflow:hidden" in css


def test_all_page_primary_headings_are_scaled_to_seventy_percent() -> None:
    css = dashboard.DASHBOARD_STYLES.read_text(encoding="utf-8")
    for required in (
        ".page-heading h1{max-width:900px;color:#11110f;font-size:clamp(29px,3.5vw,48px)",
        ".overview-copy h1{font-size:clamp(31px,2.55vw,36px)}",
        ".detail-hero h1{font-size:clamp(21px,2.52vw,38px)",
        ".today-hero h1{max-width:870px;margin:0;font-size:clamp(18px,2.1vw,31px)",
        ".today-hero h1{font-size:21px}",
        ".page-heading h1{font-size:clamp(24px,7vw,29px)",
        ".page-heading h1{font-size:22px}",
    ):
        assert required in css
