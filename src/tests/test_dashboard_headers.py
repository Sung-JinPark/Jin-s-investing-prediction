"""Shared page chrome preserves real DOM behavior across the six menu layouts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ai_fc import dashboard


ROOT = Path(__file__).resolve().parents[2]


def _nav(class_name: str, *, buttons: bool = False) -> str:
    if buttons:
        tabs = (("summary", "전망 요약"), ("daily", "6개월 일별 전망"), ("path", "경로 분포"),
                ("drivers", "기여 요인"), ("backtest", "검증 성적"), ("volatility", "변동성 기준율"))
        return f'<nav class="{class_name}" role="tablist" aria-label="시계열 예측 화면">' + "".join(
            f'<button type="button" id="lab-tab-ts-{key}" role="tab" data-ts-tab="{key}" '
            f'aria-selected="{str(key == "summary").lower()}" aria-controls="lab-ts-{key}">{label}<small></small></button>'
            for key, label in tabs
        ) + '</nav>'
    return (
        f'<nav class="{class_name}" aria-label="페이지 선택">'
        '<a href="#one" aria-current="page"><span>01</span> 첫 화면</a>'
        '<a href="#two"><span>02</span> 다른 화면</a></nav>'
    )


def _layouts() -> dict[str, str]:
    """Retain the differing nesting and node types used by the actual renderers."""
    content = '<section id="content-marker"><h2>본문</h2><p>그래프와 데이터</p><div id="kept-status" role="status" aria-live="polite">자료 확인</div></section>'
    return {
        "today": (
            '<div class="overview-page today-page"><section class="today-dashboard">'
            '<header class="today-hero"><div><p class="eyebrow">TODAY</p>'
            '<h1 id="market-thesis">오늘의 시장</h1><p id="header-metadata">2026-10-20 기준</p></div>'
            '<div class="today-actions"><button type="button" id="kept-action">브리핑</button></div>'
            '</header>' + content + '</section></div>'
        ),
        "future": (
            '<div>' + _nav("section-tabs")
            + '<div class="page-heading"><div><h1 id="v52-page-title">세 가지 시장 경로</h1>'
            '<p class="page-lede" id="header-metadata">2026-10-20 기준</p></div></div>'
            + content + '</div>'
        ),
        "timeseries": (
            '<div class="timeseries-page"><header class="timeseries-hero"><div>'
            '<h1 id="timeseries-title">NASDAQ 시계열 예측</h1>'
            '<p id="header-metadata">2026-10-20 종가 기준 <span class="ts-provisional">잠정</span></p>'
            '</div></header>' + _nav("lab-tabs timeseries-tabs", buttons=True)
            + '<div id="lab-ts-summary" class="ts-panel"><section id="kept-brief" class="ts-brief" aria-label="세 줄 요약">'
            '<div><i>3개월 뒤 예상</i><p>지수 <b>27,569</b> · 지금보다 약 4.33% 상승 예상</p></div>'
            '<div><i>예상 범위</i><p><b>24,384~29,587</b> · 현재 대비 -7.7%~+12.0% · 계산상 80% 범위</p></div>'
            '<div><i>과거 예측 성적</i><p><b>70점 / 100점 · 보통</b> · <a href="#future/timeseries/backtest">성적표 보기</a></p></div>'
            '</section>' + content + '</div></div>'
        ),
        "trendlines": (
            '<div class="trend-page"><header class="trend-heading"><p class="eyebrow">추세선 · 03</p>'
            '<h1 id="trendlines-title">상·하방 추세선</h1><p id="header-metadata">2026-10-20 기준</p>'
            '</header>' + _nav("trend-assets") + '<section class="trend-body">' + content + '</section></div>'
        ),
        "statistics": (
            '<div class="statistics-page">' + _nav("section-tabs")
            + '<div class="page-heading statistics-heading"><div><h1 id="statistics-title">닷컴과 지금</h1>'
            '<p id="header-metadata">2026-10-20 기준</p></div></div>' + content + '</div>'
        ),
        "records": (
            '<div>' + _nav("context-tabs")
            + '<div class="page-heading"><div><h1 id="records-title">예측 기록</h1>'
            '<p id="header-metadata">2026-10-20 기준</p></div>'
            '<div class="heading-stat" style="min-height:170px;display:flex;flex-direction:column">'
            '<span>등록 질문</span><strong id="kept-record-count">19</strong></div></div>'
            + content + '</div>'
        ),
    }


@pytest.fixture(scope="module")
def chrome():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
            pytest.skip(f"installed Chrome not available: {exc}")
        yield browser
        browser.close()


def _chrome_document(extra_script: str = "") -> str:
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    chrome_helpers = source[source.index("function normalizePageChrome("):source.index("function bindDynamicMotion(")]
    # Exercise the shipped CSS. Its minifier can change selector meaning even
    # when the authored stylesheet has the intended computed styles.
    css = "\n".join(re.findall(r"<style>(.*?)</style>", dashboard.render_html({}, mode="embed"), re.S))
    assert css, "rendered dashboard must contain its production stylesheet"
    css += (ROOT / "src/ai_fc/dashboard_parts/trendlines.css").read_text(encoding="utf-8")
    harness = """
const el=html=>{const t=document.createElement('template');t.innerHTML=html;return t.content.firstElementChild;};
const app=()=>document.getElementById('app');
const noop=()=>{};
const cleanupExperienceLayer=noop,closeQuickPeek=noop,bindDynamicMotion=noop,bindExperienceLayer=noop,syncQuestionActions=noop;
const predictionSectionNav=()=>el('<nav class="section-tabs"><a href="#timeseries" aria-current="page"><span>01</span> 시계열</a><a href="#future"><span>02</span> 다른 전망</a></nav>');
""" + chrome_helpers + extra_script
    return '<style>' + css + '</style><main id="app"></main><div id="tip"></div><script>' + harness + '</script>'


@pytest.mark.parametrize("width,height", [(1280, 900), (390, 844)])
def test_six_menu_headers_share_layout_without_losing_nodes_or_actions(chrome, width: int, height: int) -> None:
    page = chrome.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
    try:
        page.set_content(_chrome_document())
        rows = {}
        for menu, markup in _layouts().items():
            rows[menu] = page.evaluate("""({menu,markup,width})=>{
              document.body.dataset.view=menu;
              const root=el(markup),metadata=root.querySelector('#header-metadata'),title=root.querySelector('h1');
              const status=root.querySelector('#kept-status');
              const brief=root.querySelector('#kept-brief'),count=root.querySelector('#kept-record-count');
              const action=root.querySelector('#kept-action');let clicks=0;if(action)action.addEventListener('click',()=>clicks++);
              const before={title:title.textContent,metadata:metadata.textContent,brief:brief?.textContent,count:count?.textContent};
              mount(root);normalizePageChrome(root);
              const head=root.querySelector(':scope > .page-header'),tabs=[...root.querySelectorAll(':scope > .page-tabs')];
              const children=[...root.children],style=getComputedStyle(head),titleStyle=getComputedStyle(title),after=getComputedStyle(head,'::after');
              const pos=el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width};};
              const selected=tabs.map(nav=>nav.querySelector('[aria-current="page"],[aria-selected="true"]')).filter(Boolean);
              const tabStyles=selected.map(node=>{const s=getComputedStyle(node);return {
                background:s.backgroundColor,color:s.color,shadow:s.boxShadow,border:s.borderBottomColor,borderWidth:s.borderBottomWidth,
                font:s.fontFamily,size:s.fontSize,weight:s.fontWeight,minHeight:s.minHeight,padding:s.padding,lineHeight:s.lineHeight};});
              if(action)action.click();
              const content=root.querySelector('#content-marker'),summary=root.querySelector('.page-header-summary'),tools=root.querySelector('.page-header-tools');
              return {rootClass:root.classList.contains('page-layout'),headCount:root.querySelectorAll('.page-header').length,
                headFirst:children[0]===head,outer:pos(root),head:pos(head),content:pos(content),tabs:tabs.map(pos),
                tabsInOrder:tabs.every((node,i)=>children.indexOf(node)===i+1),tabStyles,
                background:style.backgroundColor,paper:getComputedStyle(document.documentElement).getPropertyValue('--paper').trim(),image:style.backgroundImage,padding:style.padding,
                titleFont:titleStyle.fontFamily,titleSize:titleStyle.fontSize,titleWeight:titleStyle.fontWeight,titleColor:titleStyle.color,
                decorationHidden:after.display==='none'||after.content==='none',
                metadataPreserved:document.getElementById('header-metadata')===metadata&&metadata.textContent===before.metadata,
                livePreserved:root.querySelector('#kept-status')===status&&status.getAttribute('role')==='status'&&status.getAttribute('aria-live')==='polite',
                titlePreserved:root.querySelector('h1')===title&&title.textContent===before.title,
                briefPreserved:!brief||(root.querySelector('#kept-brief')===brief&&brief.textContent===before.brief&&!head.contains(brief)),
                briefRows:brief?[...brief.children].filter(node=>node.tagName==='DIV').length:0,
                briefAfterTabs:!brief||(tabs.at(-1).nextElementSibling===brief.closest('#lab-ts-summary')&&pos(tabs.at(-1)).bottom<=pos(brief).top+1),
                noHeaderMetric:!root.querySelector('.timeseries-next,.ts-next-pct,.ts-next-level')&&!head.querySelector('.page-header-summary'),
                countPreserved:!count||(root.querySelector('#kept-record-count')===count&&count.textContent===before.count&&!head.contains(count)&&!!summary&&summary.contains(count)),
                actionPreserved:!action||(root.querySelector('#kept-action')===action&&clicks===1&&!head.contains(action)&&!!tools&&tools.contains(action)),
                actionStyle:action?{color:getComputedStyle(action).color,background:getComputedStyle(action).backgroundColor,minHeight:getComputedStyle(action).minHeight}:null,
                codes:tabs.every(nav=>nav.matches('.timeseries-tabs')?!nav.querySelector('button>span,.page-tab-code'):[...nav.querySelectorAll('.page-tab-code')].every(node=>/^\\d{2}$/.test(node.textContent.trim()))),
                overflow:document.documentElement.scrollWidth>width+1};
            }""", {"menu": menu, "markup": markup, "width": width})
        expected_padding = "22px 24px" if width == 1280 else "18px 16px"
        expected_size = "32px" if width == 1280 else "26px"
        title_styles = set()
        selected_styles = set()
        header_positions = set()
        outer_positions = set()
        for menu, row in rows.items():
            assert row["rootClass"] and row["headFirst"] and row["headCount"] == 1, menu
            assert row["paper"] == "#fbfbf8" and row["background"] == "rgb(251, 251, 248)" and row["image"] == "none", menu
            assert row["padding"] == expected_padding and row["titleSize"] == expected_size, menu
            assert row["decorationHidden"] and not row["overflow"], menu
            assert row["tabsInOrder"] and row["head"]["bottom"] <= row["content"]["top"] + 1, menu
            assert row["metadataPreserved"] and row["titlePreserved"] and row["livePreserved"], menu
            assert row["briefPreserved"] and row["countPreserved"] and row["actionPreserved"] and row["codes"], menu
            if menu == "timeseries":
                assert row["briefRows"] == 3 and row["briefAfterTabs"] and row["noHeaderMetric"], menu
            if row["actionStyle"]:
                assert row["actionStyle"] == {"color": "rgb(17, 17, 15)", "background": "rgb(255, 255, 255)", "minHeight": "44px"}, menu
            assert row["head"]["left"] - row["outer"]["left"] == (32 if width == 1280 else 12), menu
            assert row["head"]["top"] - row["outer"]["top"] == (28 if width == 1280 else 20), menu
            header_positions.add((row["head"]["left"], row["head"]["top"], row["head"]["width"]))
            outer_positions.add((row["outer"]["left"], row["outer"]["top"], row["outer"]["width"]))
            if menu != "today":
                assert row["tabs"] and row["tabStyles"], menu
            for tab in row["tabs"]:
                assert row["head"]["bottom"] <= tab["top"] + 1 and tab["bottom"] <= row["content"]["top"] + 1, menu
            title_styles.add((row["titleFont"], row["titleSize"], row["titleWeight"], row["titleColor"]))
            for style in row["tabStyles"]:
                assert style["background"] == "rgb(17, 17, 15)" and style["color"] == "rgb(255, 255, 255)", menu
                assert "rgb(255, 79, 23)" in style["shadow"] and "inset" in style["shadow"], menu
                selected_styles.add(json.dumps(style, sort_keys=True))
        assert len(title_styles) == 1, rows
        assert len(selected_styles) == 1, rows
        assert len(header_positions) == 1 and len(outer_positions) == 1, rows
    finally:
        page.close()


@pytest.mark.parametrize("width,height", [(1280, 900), (390, 844)])
def test_load_errors_and_minimal_heading_layouts_preserve_status_and_retry(chrome, width: int, height: int) -> None:
    source = dashboard.DASHBOARD_SCRIPT.read_text(encoding="utf-8")
    load_state = source[source.index("function renderFuturePathsLoadState("):source.index("function earningsQuestionEvent(")]
    script = """
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let FUTURE_PATHS_ERROR='fixture failure',retries=0;const route=()=>retries++;
""" + load_state
    page = chrome.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
    try:
        page.set_content(_chrome_document(script))
        result = page.evaluate("""()=>{
          renderFuturePathsLoadState({},new Error('<fixture failure>'));
          const root=app().firstElementChild,header=root.querySelector('.page-header'),lead=header.querySelector('.page-lede'),reason=root.querySelector('.future-paths-reason'),retry=root.querySelector('[data-future-retry]');
          const textBefore=root.textContent,leadBefore=lead.textContent,reasonBefore=reason.textContent;
          normalizePageChrome(root);normalizePageChrome(root);
          const loaded={visibleLead:getComputedStyle(lead).display!=='none'&&lead.getBoundingClientRect().height>0,
            explicitError:reason.textContent==='사유: <fixture failure>'&&getComputedStyle(reason).display!=='none',
            stable:root.textContent===textBefore&&lead.textContent===leadBefore&&reason.textContent===reasonBefore,
            statusClass:lead.classList.contains('page-header-status'),
            aria:root.querySelector('.future-paths-checkpoints').getAttribute('aria-label')==='시나리오 체크포인트 요약',
            retryNode:root.querySelector('[data-future-retry]')===retry};
          retry.click();loaded.retryWorks=retries===1&&FUTURE_PATHS_ERROR===null;
          const bare=el('<section><h1 id="bare-title">최소 제목</h1><p>본문</p></section>'),bareTitle=bare.querySelector('h1');
          mount(bare);normalizePageChrome(bare);
          const minimal={same:bare.querySelector('h1')===bareTitle,wrapped:bare.firstElementChild.matches('header.page-header'),count:bare.querySelectorAll('.page-header').length};
          const self=el('<section class="page-heading"><h1 id="self-title">자료 확인 실패</h1><p role="status" aria-live="polite">재시도 대기</p></section>'),selfTitle=self.querySelector('h1'),status=self.querySelector('[role="status"]');
          mount(self);normalizePageChrome(self);
          const standalone={sameRoot:app().firstElementChild===self,header:self.classList.contains('page-header'),layout:self.classList.contains('page-layout'),
            title:self.querySelector('h1')===selfTitle,live:self.querySelector('[role="status"]')===status&&status.getAttribute('aria-live')==='polite'};
          const detail=el('<div><div class="detail-hero"><div><h1>질문 상세</h1><div class="detail-actions"><button type="button" id="pin" aria-pressed="true">MY RADAR</button><button type="button" id="compare" aria-pressed="false">비교</button></div></div><div class="prob-orb" style="--prob:71"><strong>71</strong><span>%</span><small>최신 예측 확률</small></div></div><section>본문</section></div>');
          const pin=detail.querySelector('#pin'),compare=detail.querySelector('#compare'),orb=detail.querySelector('.prob-orb');let pinClicks=0;
          pin.addEventListener('click',()=>{pinClicks++;pin.setAttribute('aria-pressed','false');});mount(detail);normalizePageChrome(detail);
          const buttonStyle=node=>{const s=getComputedStyle(node);return {background:s.backgroundColor,color:s.color,minHeight:s.minHeight};};
          const active=buttonStyle(pin),inactive=buttonStyle(compare);pin.click();
          pin.getAnimations().forEach(animation=>animation.finish());
          const detailControls={active,inactive,afterClick:buttonStyle(pin),sameButton:detail.querySelector('#pin')===pin&&pinClicks===1,
            outsideHeader:!detail.querySelector('.page-header').contains(pin)&&!detail.querySelector('.page-header').contains(orb),
            sameProbability:detail.querySelector('.prob-orb')===orb&&orb.querySelector('strong').textContent==='71'&&orb.style.getPropertyValue('--prob')==='71'};
          return {loaded,minimal,standalone,detailControls};
        }""")
        assert all(result["loaded"].values()), result
        assert result["minimal"] == {"same": True, "wrapped": True, "count": 1}
        assert all(result["standalone"].values()), result
        detail = result["detailControls"]
        assert detail["active"] == {"background": "rgb(17, 17, 15)", "color": "rgb(255, 255, 255)", "minHeight": "44px"}
        inactive = {"background": "rgb(255, 255, 255)", "color": "rgb(17, 17, 15)", "minHeight": "44px"}
        assert detail["inactive"] == detail["afterClick"] == inactive
        assert detail["sameButton"] and detail["outsideHeader"] and detail["sameProbability"]
    finally:
        page.close()
