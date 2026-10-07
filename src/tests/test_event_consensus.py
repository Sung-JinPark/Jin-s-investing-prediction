"""이벤트 발표값 표(실제·예상·이전) — 수집기·원장·화면 계약. 네트워크 없이 스텁으로 검증."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ai_fc import event_consensus as ec

ROOT = Path(__file__).resolve().parents[2]


def _root(tmp_path: Path) -> Path:
    for relative in ("data/calendar/events.csv", "data/contracts/calendar_sources.yaml"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def _econ(rows):
    return {"data": {"rows": [{"country": "United States", "description": "", **row} for row in rows]}}


def _stub(pages: dict[str, dict]):
    calls: list[str] = []

    def fetch(url: str) -> dict:
        calls.append(url)
        for key, payload in pages.items():
            if key in url:
                return payload
        return {"data": {"rows": []}}
    return fetch, calls


def test_parse_number_and_blank_cells() -> None:
    assert ec.clean_text("&nbsp;") is None and ec.clean_text(" ") is None
    assert ec.parse_number("1,701K") == 1_701_000
    assert ec.parse_number("-0.3%") == -0.3
    assert ec.parse_number("$4.70") == 4.70
    assert ec.parse_number("n/a") is None


def test_macro_rows_use_the_next_day_page_and_match_time(tmp_path: Path) -> None:
    """Nasdaq date 파라미터는 하루 밀려 있다(10-02 금 고용 → date=10-03)."""
    event = {"event_id": "nfp_x", "kind": "nfp", "date": "2026-10-02", "time_et": "08:30"}
    fetch, calls = _stub({
        "date=2026-10-03": _econ([
            {"gmt": "08:30", "eventName": "Nonfarm Payrolls", "actual": "29K", "consensus": "89K", "previous": "133K"},
            {"gmt": "08:30", "eventName": "Unemployment Rate", "actual": "4.2%", "consensus": "4.1%", "previous": "4.1%"},
        ]),
        "date=2026-10-02": _econ([
            {"gmt": "10:00", "eventName": "Nonfarm Payrolls", "actual": "999K", "consensus": "", "previous": ""},
        ]),
    })
    rows = {row["metric"]: row for row in ec.macro_rows(event, fetch)}
    assert rows["payroll_change"]["actual"] == "29K"
    assert rows["payroll_change"]["consensus"] == "89K" and rows["payroll_change"]["previous"] == "133K"
    assert rows["unemployment_rate"]["actual"] == "4.2%"
    assert "avg_hourly_earnings_mom" not in rows, "원천에 없는 지표는 만들지 않는다"
    assert any("date=2026-10-03" in url for url in calls)


def test_cpi_mom_then_yoy_by_order() -> None:
    event = {"event_id": "cpi_x", "kind": "cpi", "date": "2026-10-14", "time_et": "08:30"}
    fetch, _ = _stub({"date=2026-10-15": _econ([
        {"gmt": "08:30", "eventName": "CPI", "actual": "&nbsp;", "consensus": " ", "previous": "0.4%"},
        {"gmt": "08:30", "eventName": "CPI", "actual": "&nbsp;", "consensus": " ", "previous": "3.4%"},
    ])})
    rows = {row["metric"]: row for row in ec.macro_rows(event, fetch)}
    assert rows["headline_cpi_mom"]["previous"] == "0.4%" and rows["headline_cpi_yoy"]["previous"] == "3.4%"
    assert rows["headline_cpi_mom"]["actual"] is None and rows["headline_cpi_mom"]["consensus"] is None


def _eps_pages(reported_rows, forecast_rows):
    return {
        "earnings-surprise": {"data": {"earningsSurpriseTable": {"rows": reported_rows}}},
        "earnings-forecast": {"data": {"quarterlyForecast": {"rows": forecast_rows}}},
    }


def test_earnings_before_release_uses_next_quarter_consensus() -> None:
    event = {"event_id": "msft_x", "kind": "earnings", "date": "2026-10-28", "ticker": "MSFT"}
    fetch, _ = _stub(_eps_pages(
        [{"fiscalQtrEnd": "Jun 2026", "dateReported": "7/29/2026", "eps": 4.74, "consensusForecast": "4.21"}],
        [{"fiscalEnd": "Sep 2026", "consensusEPSForecast": 4.7, "noOfEstimates": 14}]))
    (row,) = ec.earnings_rows(event, fetch)
    assert (row["actual"], row["consensus"], row["previous"]) == (None, "$4.70", "$4.74")
    assert row["period"] == "Sep 2026 분기" and "14" in row["note"]


def test_earnings_after_release_uses_reported_and_as_reported_consensus() -> None:
    """일정의 실적일은 추정이라 실제 발표가 몇 주 어긋난다 — 3주 창 안의 발표를 그 회차로 본다."""
    event = {"event_id": "mu_x", "kind": "earnings", "date": "2026-09-24", "ticker": "MU"}
    fetch, _ = _stub(_eps_pages(
        [{"fiscalQtrEnd": "Aug 2026", "dateReported": "9/30/2026", "eps": 33.19, "consensusForecast": "31.41"},
         {"fiscalQtrEnd": "May 2026", "dateReported": "6/25/2026", "eps": 24.89, "consensusForecast": "20"}],
        []))
    (row,) = ec.earnings_rows(event, fetch)
    assert (row["actual"], row["consensus"], row["previous"]) == ("$33.19", "$31.41", "$24.89")


def test_refresh_appends_only_changes_and_loader_respects_cutoff(tmp_path: Path) -> None:
    root = _root(tmp_path)
    now = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
    payload = _econ([{"gmt": "08:30", "eventName": "Nonfarm Payrolls", "actual": "29K",
                      "consensus": "89K", "previous": "133K"}])
    fetch, _ = _stub({"date=2026-10-03": payload})
    first = ec.refresh(root, now=now, fetch=fetch)
    assert first["appended"] >= 1 and not first["failures"]
    ledger = root / ec.LEDGER_RELATIVE
    before = ledger.read_bytes()
    again = ec.refresh(root, now=now, fetch=fetch)
    assert again["appended"] == 0 and ledger.read_bytes() == before, "값이 같으면 덧붙이지 않는다"
    payload["data"]["rows"][0]["actual"] = "31K"  # 원천 정정
    later = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)
    assert ec.refresh(root, now=later, fetch=fetch)["appended"] == 1
    assert ledger.read_bytes().startswith(before), "append-only — 기존 바이트 무변경"
    shown = ec.load_event_consensus(root, now)["nfp_2026_10"]
    assert shown[0]["actual"] == "29K", "as_of 뒤에 수집된 정정은 그 시점 화면에 없다"
    assert ec.load_event_consensus(root, later)["nfp_2026_10"][0]["actual"] == "31K"


def test_failures_do_not_erase_other_rows(tmp_path: Path) -> None:
    root = _root(tmp_path)

    def fetch(url: str) -> dict:
        if "earnings" in url:
            raise ec.ConsensusError("blocked")
        return _econ([{"gmt": "08:30", "eventName": "Nonfarm Payrolls", "actual": "29K",
                       "consensus": "89K", "previous": "133K"}])
    result = ec.refresh(root, now=datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc), fetch=fetch)
    assert result["failures"] and result["appended"] >= 1


def test_committed_ledger_rows_are_well_formed() -> None:
    path = ROOT / ec.LEDGER_RELATIVE
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    for row in rows:
        assert {"captured_at", "event_id", "metric", "actual", "consensus", "previous", "source"} <= set(row)
        assert row["source_url"].startswith("https://")


def test_dashboard_renders_actual_forecast_previous() -> None:
    from ai_fc import dashboard

    html = dashboard.render_html({}, mode="embed")
    assert "<th scope=\"col\">실제</th><th scope=\"col\">예상</th><th scope=\"col\">이전</th>" in html
    board = html[html.index("function renderEventBoard"):html.index("function homeSignalSummary")]
    assert "evAfpCluster(item)" in board, "홈 일정 카드마다 세 칸"
    detail = html[html.index("function renderEventForecast"):html.index("function upcoming(")]
    assert "evAfpTable(afp)" in detail and "earningsCompanyName(peer)" in detail
    # 경제지표는 상회·하회에 색을 칠하지 않는다 — 좋고 나쁨이 지표마다 다르다
    tone = html[html.index("function evAfpTone"):html.index("const evAfpCell")]
    assert "row.metric!=='eps'" in tone


def test_event_cards_are_uniform_with_the_divider_at_the_middle() -> None:
    """2026-10-07 사용자 지시: 카드 크기 통일 · 가운데 선은 정확히 가운데 · 값이 없어도 칸은 그린다."""
    import re

    css = (ROOT / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")
    assert ".ev-cards{grid-auto-rows:1fr}" in css, "모든 카드가 같은 높이"
    assert "grid-template-rows:minmax(0,1fr) minmax(0,1fr)" in css, "위·아래 두 칸이 같은 높이"
    # 위 테두리 3px 을 아래 여백으로 갚아야 선이 카드의 정확한 가운데에 온다
    top, bottom = (int(v) for v in re.search(
        r"\.ev-card\{grid-template-rows:[^}]*padding:(\d+)px \d+px (\d+)px", css).groups())
    assert bottom == top + 3
    js = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    cluster = js[js.index("function evAfpCluster"):js.index("function evAfpTable")]
    assert "return row?evAfpStrip(row):empty" in cluster and "if(!rows.length)return empty" in cluster
