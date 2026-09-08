"""V13-VOL 대시보드 패널 — 배선(기본 숨김)·X1 이름충돌 6항·레일 tier 게이트를 JS/CSS 소스에서 고정한다.

표시 설계서 docs/design/v13_vol_live_card_display_design_260908.md §1.2(X1)·§4.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
STYLE = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")


def _panel_source() -> str:
    start = SCRIPT.index("function renderTimeseriesV13VolPanel(")
    end = SCRIPT.index("function bindTimeseriesV13VolInteractions(")
    return SCRIPT[start:end]


def test_v13_vol_panel_is_wired_hidden_by_default() -> None:
    assert "const TS_TABS=[['summary','전망 요약','01']" in SCRIPT, "기존 4탭 리터럴 보존"
    assert "const TS_V13_TAB=['volatility','변동성 기준율','05']" in SCRIPT
    assert "[...TS_TABS,TS_V13_TAB].map(" in SCRIPT, "탭 마크업이 5탭을 그린다(비활성=검증 대기)"
    assert "function timeseriesV13TabEnabled(" in SCRIPT
    assert "get('review')==='v13vol'" in SCRIPT, "T2 는 ?review=v13vol 로만 열람"
    assert "tier==='t3_live_card')return true" in SCRIPT
    # 세 렌더 경로(V8 · HOLD · 레거시) 모두 패널을 싣고 탭 토글이 5번째 패널을 안다
    assert SCRIPT.count("${panel('volatility',renderTimeseriesV13VolPanel(DATA.timeseries_v13_vol))}") == 3
    assert SCRIPT.count("if(timeseriesV13TabEnabled(DATA.timeseries_v13_vol))enabled.push('volatility');") == 2
    assert "[...TS_TABS,TS_V13_TAB].forEach(([name])=>{const node=$(`#lab-ts-${name}`,root);if(node)node.hidden=name!==next;});" in SCRIPT
    assert "bindTimeseriesTabs(root,enabled,'summary');" in SCRIPT, "V8 HOLD 경로에도 탭 바인더"


def test_v13_vol_panel_satisfies_x1_six_items() -> None:
    src = _panel_source()
    # ① 명칭 — 제목·셀 라벨은 '기준율', 예측이라는 이름을 쓰지 않는다
    assert "<h2>변동성 이벤트 기준율</h2>" in src
    assert "<b>기준율 ${v13Pct(c.p)}</b>" in src
    assert "아래 숫자는 예측이 아니라" in src
    # ② 출처 배지 상시 — live/hold/absent 어느 분기에서도 head 에 포함
    assert "v13-source-badge" in src and "수치모델 · " in src and "당일 수준 지속(PB)" in src
    assert src.count("${head}") == 2, "hold 분기와 live 분기 모두 배지가 있는 head 를 쓴다"
    # ③ 지평 단위 — 영업일 + 달력일 병기
    assert "영업일</abbr>" in src and "'63':'(≈90달력일)'" in src
    # ④ caveat lead 상시 — 홀드아웃 미검증 굵게(가드 플래그) + 참고 의견
    assert "<b>홀드아웃 미검증</b>" in src and "참고 의견 — 매매 신호가 아닙니다" in src
    assert src.count("${caveat}") == 2
    # ⑤ 역할 관계 + 괴리는 표시만
    assert "base rate(outside view)" in src and "합치거나 평균내지 않습니다" in src
    assert "표시만(자동 조정 없음)" in src and "divergence_threshold_pp" in src
    # ⑥ 결합·평균·컨센서스 산식 0 — LLM 확률은 차이 표시에만 쓰인다
    assert "컨센서스" not in src and "평균(" not in src
    assert "(llm+" not in src and "+llm)" not in src and "*llm" not in src
    assert "model63-llm" in src, "괴리 = 차이 표시만"
    # h63 보정 약함 텍스트 마커 + 80% 대역 + 기후 병기
    assert "▲ 보정 약함" in src and "[80%: " in src and "기후 ${v13Pct(c.clim_base_rate)}" in src
    # hold 분기: 사유 목록 + 마지막 값 재사용 금지 문구, 숫자 없음
    assert "timeseries-hold-reasons" in src and "마지막 값을 재사용하지 않습니다" in src
    for term in ("persistence_hint", "base_rate_hint", "business_day_hint", "band80_coef_hint", "v13_weak_hint"):
        assert f"  {term}:'" in SCRIPT, term


def test_v13_vol_rail_entry_is_tier_gated_and_parseable() -> None:
    registry = SCRIPT.split("const MID_CATEGORIES={")[1].split("\n};")[0]
    entry = re.search(r"\{key:'volatility'[^}]*\}", registry)
    assert entry, "레일 항목 존재"
    assert "hash:'#timeseries/volatility'" in entry.group(0)
    assert "available:()=>DATA?.timeseries_v13_vol?.publication?.display_tier==='t3_live_card'" in entry.group(0)


def test_v13_vol_css_keeps_badge_and_caveat_visible_at_every_width() -> None:
    assert ".v13-source-badge{" in STYLE and ".v13-caveat{" in STYLE
    assert ".v13-h-tabs{display:none}" in STYLE
    mobile = STYLE.split("@media (max-width:620px){", 1)[1].split("}\n}", 1)[0]
    assert ".v13-h-tabs{display:flex" in mobile
    assert 'data-active-h="63"' in mobile
    for cls in (".v13-source-badge", ".v13-caveat"):
        assert f"{cls}{{display:none" not in STYLE and f"{cls}{{visibility:hidden" not in STYLE
    assert ".v13-vol-table td.is-weak i{" in STYLE, "색만이 아니라 텍스트 마커"


def test_v13_vol_panel_has_no_trailing_line_comments() -> None:
    # 컴팩터가 줄을 공백으로 잇는다 — 줄 끝 // 주석은 번들을 죽인다 (test_compacted_bundle 과 같은 규율)
    start = SCRIPT.index("function timeseriesV13TabEnabled(")
    end = SCRIPT.index("function renderTimeseriesV8(")
    for line in SCRIPT[start:end].splitlines():
        stripped = line.strip()
        assert not re.search(r"(?<![:'\"])//(?!.*['\"`])", stripped) or stripped.startswith("/*") or stripped.startswith("*"), line
