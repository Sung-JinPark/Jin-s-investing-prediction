"""미국 운영기업 IPO 월별 건수 — Ritter 확정치 파싱·Nasdaq 잠정 필터·12개월 합·갱신 (네트워크 없음)."""

from __future__ import annotations

import hashlib
import html
import io
import json
import urllib.error
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_fc.authoritative_statistics import read_raw_artifact_receipts
from ai_fc.ipo_monthly_counts import (
    NASDAQ_TABLE_RELATIVE,
    RITTER_TABLE_RELATIVE,
    IPOMonthlyCountsError,
    count_nasdaq_month,
    ipo_count_series,
    load_ipo_monthly_tables,
    nasdaq_row_is_operating,
    parse_ritter_ipoall,
    parse_ritter_ipoall_rows,
    refresh_ipo_monthly_counts,
    refresh_nasdaq_table,
    refresh_ritter_table,
    ritter_year,
    trailing_sums,
)

ROOT = Path(__file__).resolve().parents[2]


def _xlsx(rows: list[list[object]], sheet: str = "IPOALL") -> bytes:
    def column(index: int) -> str:
        name = ""
        while index:
            index, rest = divmod(index - 1, 26)
            name = chr(65 + rest) + name
        return name

    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row, start=1):
            ref = f"{column(c)}{r}"
            if value is None:
                cells.append(f'<c r="{ref}"/>')
            elif isinstance(value, str):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("xl/workbook.xml", (
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            f'<sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>'))
        archive.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>'))
        archive.writestr("xl/worksheets/sheet1.xml", (
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>'))
    return target.getvalue()


def _ipoall_rows(last: tuple[int, int] = (2025, 12)) -> list[list[object]]:
    """1994-01 부터 ``last`` 까지 — net = 월 번호, gross = net + 3."""
    rows: list[list[object]] = [[1, 94, 13.8, 4, "see 1975", "see 1980", "The columns are ..."]]
    year, month = 1994, 2
    while (year, month) <= last:
        rows.append([month, year % 100, 10.0, month + 3, month, 50])
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    rows.append([None, None, None])
    rows.append(["the first column is the month", None, None, None, "the second column is the year"])
    return rows


def test_two_digit_years_split_at_sixty() -> None:
    assert ritter_year(60) == 1960
    assert ritter_year(99) == 1999
    assert ritter_year(0) == 2000
    assert ritter_year(25) == 2025
    with pytest.raises(IPOMonthlyCountsError):
        ritter_year(100)


def test_text_cells_are_missing_not_zero_and_notes_are_skipped() -> None:
    rows = [
        [1, 60, 13.8, 16, "see 1975", "see 1980", "The columns are the month, year ..."],
        [2, 60, 8, 16, None, None, "of IPOs that priced above the midpoint"],
        [3, 60, ".", 0, "na"],
        ["the first column is the month", None, None],
        [None, None, None],
    ]
    parsed = parse_ritter_ipoall_rows(rows)
    assert parsed == [
        {"month": "1960-01", "gross": 16, "net": None},
        {"month": "1960-02", "gross": 16, "net": None},
        {"month": "1960-03", "gross": 0, "net": None},
    ]


def test_parser_rejects_gaps_duplicates_and_fractional_counts() -> None:
    with pytest.raises(IPOMonthlyCountsError, match="not contiguous"):
        parse_ritter_ipoall_rows([[1, 25, 0, 5, 3], [3, 25, 0, 5, 3]])
    with pytest.raises(IPOMonthlyCountsError, match="duplicate"):
        parse_ritter_ipoall_rows([[1, 25, 0, 5, 3], [1, 25, 0, 5, 3]])
    with pytest.raises(IPOMonthlyCountsError, match="non-negative integer"):
        parse_ritter_ipoall_rows([[1, 25, 0, 5, 2.5]])
    with pytest.raises(IPOMonthlyCountsError, match="no monthly rows"):
        parse_ritter_ipoall_rows([["notes only"]])


def test_workbook_parse_reads_the_ipoall_sheet() -> None:
    parsed = parse_ritter_ipoall(_xlsx(_ipoall_rows()))
    assert parsed[0] == {"month": "1994-01", "gross": 4, "net": None}
    by_month = {row["month"]: row for row in parsed}
    assert by_month["1999-12"] == {"month": "1999-12", "gross": 15, "net": 12}
    assert parsed[-1]["month"] == "2025-12"
    with pytest.raises(IPOMonthlyCountsError, match="unreadable"):
        parse_ritter_ipoall(_xlsx(_ipoall_rows(), sheet="Other"))


NASDAQ_FIXTURE = {"data": {"priced": {"rows": [
    {"proposedTickerSymbol": "ADRX", "companyName": "ADARx Pharmaceuticals, Inc.", "proposedSharePrice": "17.00"},
    {"proposedTickerSymbol": "BRRKU", "companyName": "Bluerock Acquisition Corp. II", "proposedSharePrice": "10.00"},
    {"proposedTickerSymbol": "LOVIU", "companyName": "Live Oak Holdings", "proposedSharePrice": "10.00"},
    {"proposedTickerSymbol": "MRGR", "companyName": "Alpha Merger Co", "proposedSharePrice": "10.00"},
    {"proposedTickerSymbol": "CAPC", "companyName": "Beta Capital Corp", "proposedSharePrice": "10.00"},
    {"proposedTickerSymbol": "FNDX", "companyName": "Gamma Income Fund", "proposedSharePrice": "20.00"},
    {"proposedTickerSymbol": "RTRS", "companyName": "Delta Realty Trust", "proposedSharePrice": "20.00"},
    {"proposedTickerSymbol": "PENY", "companyName": "Penny Bio Inc.", "proposedSharePrice": "4.00"},
    {"proposedTickerSymbol": "RANG", "companyName": "Range Tech Inc.", "proposedSharePrice": "4.00-6.00"},
    {"proposedTickerSymbol": "RZAI", "companyName": "ROZE AI INC.", "proposedSharePrice": None},
    {"proposedTickerSymbol": "BIGC", "companyName": "Big Cloud Inc.", "proposedSharePrice": "1,234.00"},
]}}}


def test_nasdaq_filter_approximates_operating_companies() -> None:
    kept = [row["proposedTickerSymbol"] for row in NASDAQ_FIXTURE["data"]["priced"]["rows"]
            if nasdaq_row_is_operating(row)]
    # 가격 미공시(RZAI)는 남기고, 범위는 하단가($4)로 판정한다.
    assert kept == ["ADRX", "RZAI", "BIGC"]
    counts = count_nasdaq_month(json.dumps(NASDAQ_FIXTURE).encode("utf-8"))
    assert counts == {"priced_total": 11, "operating_approx": 3}


def test_nasdaq_counter_handles_empty_and_rejects_malformed_responses() -> None:
    assert count_nasdaq_month(b'{"data": {"priced": {"rows": null}}}') == {
        "priced_total": 0, "operating_approx": 0}
    assert count_nasdaq_month(b'{"data": {"priced": null}}')["priced_total"] == 0
    # 실제 응답에 섞여 오는 비 UTF-8 바이트는 이름 판정에만 영향, 개수는 그대로.
    assert count_nasdaq_month(
        b'{"data": {"priced": {"rows": [{"companyName": "Caf\xa2 Inc.", "proposedSharePrice": "9"}]}}}'
    ) == {"priced_total": 1, "operating_approx": 1}
    with pytest.raises(IPOMonthlyCountsError):
        count_nasdaq_month(b"<html>blocked</html>")
    with pytest.raises(IPOMonthlyCountsError):
        count_nasdaq_month(b'{"data": {"upcoming": {}}}')


def test_trailing_sums_need_twelve_contiguous_months() -> None:
    monthly = {f"2024-{m:02d}": 1 for m in range(1, 13)} | {"2025-01": 2, "2025-02": None, "2025-03": 1}
    sums = trailing_sums(monthly)
    assert sums == {"2024-12": 12, "2025-01": 13}


def _ritter_table(last: str = "2025-12") -> dict:
    months = []
    year, month = 1994, 1
    while f"{year:04d}-{month:02d}" <= last:
        months.append({"month": f"{year:04d}-{month:02d}", "gross": 12, "net": 10})
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return {"months": months, "last_confirmed_month": last}


def _nasdaq_table(months: dict[str, tuple[int, bool]]) -> dict:
    return {"months": {month: {"operating_approx": value, "priced_total": value * 2, "complete": complete}
                       for month, (value, complete) in months.items()}}


def test_confirmed_series_never_contains_provisional_counts() -> None:
    nasdaq = _nasdaq_table({"2025-11": (99, True), "2026-01": (40, True), "2026-02": (40, True),
                            "2026-03": (40, False)})
    built = ipo_count_series(_ritter_table(), nasdaq)
    assert built["last_confirmed_month"] == "2025-12"
    assert max(built["confirmed"]) == "2025-12"
    assert set(built["confirmed"].values()) == {120}          # Ritter 10건 × 12개월만
    # 확정월 이후 완결 달만, 확정월 이전 Nasdaq 값(2025-11=99)은 버린다. 미완결 3월은 제외.
    assert built["provisional"] == {"2026-01": 150, "2026-02": 180}
    assert [row["month"] for row in built["provisional_months"]] == ["2026-01", "2026-02"]


def test_new_confirmed_month_supersedes_the_provisional_one() -> None:
    nasdaq = _nasdaq_table({"2026-01": (40, True), "2026-02": (40, True)})
    built = ipo_count_series(_ritter_table(last="2026-01"), nasdaq)
    assert built["confirmed"]["2026-01"] == 120
    assert list(built["provisional"]) == ["2026-02"]
    assert built["provisional"]["2026-02"] == 150


def test_provisional_stops_at_the_first_missing_month() -> None:
    nasdaq = _nasdaq_table({"2026-01": (40, True), "2026-03": (40, True)})
    built = ipo_count_series(_ritter_table(), nasdaq)
    assert list(built["provisional"]) == ["2026-01"]


def _install_policy(root: Path) -> None:
    target = root / "data/contracts/authoritative_statistics_sources.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / "data/contracts/authoritative_statistics_sources.yaml").read_bytes())


def test_ritter_refresh_receipts_raw_once_and_fails_soft(tmp_path: Path) -> None:
    _install_policy(tmp_path)
    workbook = _xlsx(_ipoall_rows())
    calls: list[str] = []

    def fetcher(url: str):
        calls.append(url)
        return workbook, 200, "Mon, 19 Jan 2026 16:37:49 GMT"

    first = refresh_ritter_table(tmp_path, checked_at="2026-10-06T00:00:00+00:00", fetcher=fetcher)
    assert first["status"] == "updated" and first["last_confirmed_month"] == "2025-12"
    table = json.loads((tmp_path / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))
    assert table["raw_sha256"] == hashlib.sha256(workbook).hexdigest()
    store = tmp_path / "data/statistics/official_store"
    receipts = read_raw_artifact_receipts(store)
    assert [r.source_id for r in receipts] == ["ritter_ipoall_monthly"]
    assert (store / table["raw_path"]).read_bytes() == workbook
    assert calls == ["https://site.warrington.ufl.edu/ritter/files/IPOALL.xlsx"]

    second = refresh_ritter_table(tmp_path, checked_at="2026-10-07T00:00:00+00:00", fetcher=fetcher)
    assert second["status"] == "current"
    assert len(read_raw_artifact_receipts(store)) == 1           # 같은 바이트면 영수증을 늘리지 않는다

    def failing(_url: str):
        raise urllib.error.URLError("down")

    failed = refresh_ritter_table(tmp_path, checked_at="2026-10-08T00:00:00+00:00", fetcher=failing)
    assert failed == {"status": "fetch_failed", "error": "URLError", "table_kept": True}
    broken = refresh_ritter_table(
        tmp_path, checked_at="2026-10-08T00:00:00+00:00",
        fetcher=lambda _url: (_xlsx([["notes only"]]), 200, None),
    )
    assert broken["status"] == "parse_failed" and broken["table_kept"] is True
    assert json.loads((tmp_path / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))["raw_sha256"] == table["raw_sha256"]

    revised = _ipoall_rows(last=(2026, 3))
    revised[5][4] = 99                                            # 과거 달 개정
    third = refresh_ritter_table(tmp_path, checked_at="2026-10-09T00:00:00+00:00",
                                 fetcher=lambda _url: (_xlsx(revised), 200, None))
    # zip 항목 시각 때문에 바이트 해시는 고정값으로 비교하지 않는다.
    assert {key: third[key] for key in ("status", "last_confirmed_month", "revised_existing_months")} == {
        "status": "updated", "last_confirmed_month": "2026-03", "revised_existing_months": 1}
    assert third["raw_sha256"] != table["raw_sha256"]
    assert len(read_raw_artifact_receipts(store)) == 2
    history = json.loads((tmp_path / RITTER_TABLE_RELATIVE).read_text(encoding="utf-8"))["revisions"]
    assert history[-1]["superseded_raw_sha256"] == table["raw_sha256"]


def _write_ritter(root: Path, last: str) -> None:
    target = root / RITTER_TABLE_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_ritter_table(last)), encoding="utf-8")


def test_nasdaq_refresh_backfills_once_refreshes_recent_and_marks_failures_stale(tmp_path: Path) -> None:
    _write_ritter(tmp_path, "2026-06")
    requested: list[str] = []
    sleeps: list[float] = []

    def fetcher(url: str) -> bytes:
        requested.append(url.rsplit("=", 1)[1])
        return json.dumps(NASDAQ_FIXTURE).encode("utf-8")

    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    result = refresh_nasdaq_table(tmp_path, now=now, fetcher=fetcher, sleep=sleeps.append)
    assert requested == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert sleeps == [0.5, 0.5, 0.5]
    table = json.loads((tmp_path / NASDAQ_TABLE_RELATIVE).read_text(encoding="utf-8"))
    assert table["index_input"] is False and table["usage"] == "provisional_display_only"
    assert table["access"]["authorized_on"] == "2026-10-06"
    assert {m: row["complete"] for m, row in table["months"].items()} == {
        "2026-07": True, "2026-08": True, "2026-09": True, "2026-10": False}
    assert "companyName" not in json.dumps(table)                # 거래 목록은 저장하지 않는다
    assert "ADRX" not in json.dumps(table)
    assert result["status"] == "current"

    requested.clear()

    def flaky(url: str) -> bytes:
        requested.append(url.rsplit("=", 1)[1])
        raise urllib.error.URLError("blocked")

    stale = refresh_nasdaq_table(tmp_path, now=now, fetcher=flaky, sleep=lambda _s: None)
    assert requested == ["2026-09", "2026-10"]                    # 완결된 과거 달은 다시 받지 않는다
    assert stale["status"] == "stale"
    table = json.loads((tmp_path / NASDAQ_TABLE_RELATIVE).read_text(encoding="utf-8"))
    assert table["months"]["2026-09"]["operating_approx"] == 3 and table["months"]["2026-09"]["stale"] is True

    _write_ritter(tmp_path, "2026-08")                            # Ritter 가 확정월을 늘리면
    refresh_nasdaq_table(tmp_path, now=now, fetcher=fetcher, sleep=lambda _s: None)
    table = json.loads((tmp_path / NASDAQ_TABLE_RELATIVE).read_text(encoding="utf-8"))
    assert list(table["months"]) == ["2026-09", "2026-10"]        # 잠정 표에서 그 달들이 내려간다


def test_full_refresh_writes_status_without_network(tmp_path: Path) -> None:
    _install_policy(tmp_path)
    path, status = refresh_ipo_monthly_counts(
        tmp_path, now=datetime(2026, 2, 3, tzinfo=timezone.utc),
        ritter_fetcher=lambda _url: (_xlsx(_ipoall_rows()), 200, None),
        nasdaq_fetcher=lambda _url: json.dumps(NASDAQ_FIXTURE).encode("utf-8"),
        sleep=lambda _s: None,
    )
    assert path.is_file()
    assert status["ritter"]["status"] == "updated"
    assert status["nasdaq"]["months"] == {"2026-01": 3, "2026-02": 3}
    assert status["index_input"] == "ritter_net_confirmed_only"
    tables = load_ipo_monthly_tables(tmp_path)
    assert tables is not None and tables["nasdaq"]["provisional_after"] == "2025-12"


def test_table_pinned_to_a_different_raw_artifact_is_rejected(tmp_path: Path) -> None:
    _install_policy(tmp_path)
    refresh_ritter_table(tmp_path, checked_at="2026-10-06T00:00:00+00:00",
                         fetcher=lambda _url: (_xlsx(_ipoall_rows()), 200, None))
    table_path = tmp_path / RITTER_TABLE_RELATIVE
    table = json.loads(table_path.read_text(encoding="utf-8"))
    table["raw_sha256"] = "0" * 64
    table_path.write_text(json.dumps(table), encoding="utf-8")
    with pytest.raises(IPOMonthlyCountsError, match="raw artifact"):
        load_ipo_monthly_tables(tmp_path)


def test_shipped_tables_match_the_approved_definition() -> None:
    tables = load_ipo_monthly_tables(ROOT)
    assert tables is not None
    ritter, nasdaq = tables["ritter"], tables["nasdaq"]
    assert ritter["policy_source_id"] == "ritter_ipoall_monthly"
    assert ritter["source_url"] == "https://site.warrington.ufl.edu/ritter/files/IPOALL.xlsx"
    assert (ROOT / "data/statistics/official_store" / ritter["raw_path"]).is_file()
    assert nasdaq["index_input"] is False
    assert nasdaq["provisional_after"] == ritter["last_confirmed_month"]
    assert all(month > ritter["last_confirmed_month"] for month in nasdaq["months"])
    built = ipo_count_series(ritter, nasdaq)
    dotcom = [value for month, value in built["confirmed"].items() if "1995-01" <= month <= "1999-12"]
    assert len(dotcom) == 60
    # 2026-10-06 사용자 결정 문서의 기준값 — IPOALL 이 개정되면 이 테스트가 먼저 알린다.
    if ritter["last_confirmed_month"] == "2025-12":
        assert (min(dotcom), max(dotcom)) == (258, 711)
        assert built["confirmed"]["2025-12"] == 90


def test_policy_admits_only_the_ipoall_counts_as_numeric() -> None:
    from ai_fc.authoritative_statistics import SourcePolicyViolation, load_authoritative_source_policy

    policy = load_authoritative_source_policy(ROOT / "data/contracts/authoritative_statistics_sources.yaml")
    assert policy.require_numeric_source("ritter_ipoall_monthly").allowed_domains == ("site.warrington.ufl.edu",)
    for insight_only in ("ritter_ipo_research", "nasdaq_ipo_calendar"):
        with pytest.raises(SourcePolicyViolation):
            policy.require_numeric_source(insight_only)
    assert "provisional_display_only" in policy.rule_for("nasdaq_ipo_calendar").usage_roles


def test_theme_adr_additions_are_sourced_symmetric_and_confirmed_only(tmp_path: Path) -> None:
    """2026-10-08 사용자 결정: 시대 핵심 ADR(닷컴 반도체·인터넷 / 현재 반도체·AI)은 확정 계열에 더한다.

    잠정(Nasdaq 근사) 구간에는 더하지 않는다 — 근사 필터가 ADR 을 이미 센다(SK hynix 2026-07).
    """
    from ai_fc.ipo_monthly_counts import ipo_count_series, load_theme_adr_additions

    rows = load_theme_adr_additions(ROOT)
    assert {row["era"] for row in rows} == {"dotcom", "ai"}
    names = {row["company"] for row in rows}
    assert {"SK hynix", "Arm Holdings", "Taiwan Semiconductor Manufacturing"} <= names
    assert all(row["source_url"].startswith(("https://", "http://")) for row in rows)
    assert all(row["instrument"] in {"ADR", "ADS"} for row in rows)
    ritter = {"last_confirmed_month": "2024-12", "months": [
        {"month": f"{2024 if i >= 12 else 2023}-{(i % 12) + 1:02d}", "net": 5, "gross": 9} for i in range(24)]}
    nasdaq = {"months": {"2025-01": {"complete": True, "operating_approx": 7, "priced_total": 9}}}
    extra = [
        {"month": "2024-10", "era": "ai", "theme": "ai", "company": "X", "ticker": "", "exchange": "Nasdaq",
         "instrument": "ADS", "source_url": "https://example.org", "note": ""},
        {"month": "2025-01", "era": "ai", "theme": "semiconductor", "company": "Y", "ticker": "", "exchange": "Nasdaq",
         "instrument": "ADS", "source_url": "https://example.org", "note": ""},
    ]
    built = ipo_count_series(ritter, nasdaq, extra)
    assert built["confirmed"]["2024-12"] == 61, "확정월 가산 1건"
    assert built["theme_adr_added"] == {"2024-10": 1}, "확정월 이후(잠정) 행은 더하지 않는다"
    assert built["provisional"]["2025-01"] == 61 - 5 + 7
    base = ipo_count_series(ritter, nasdaq)
    assert base["confirmed"]["2024-12"] == 60 and base["theme_adr_added"] == {}


def test_theme_adr_rows_outside_the_era_theme_are_rejected(tmp_path: Path) -> None:
    from ai_fc.ipo_monthly_counts import (
        THEME_ADR_FIELDS, THEME_ADR_RELATIVE, IPOMonthlyCountsError, load_theme_adr_additions,
    )

    path = tmp_path / THEME_ADR_RELATIVE
    path.parent.mkdir(parents=True)
    path.write_text(",".join(THEME_ADR_FIELDS) + "\n"
                    "1999-10,dotcom,ai,Bad,,Nasdaq,ADS,https://example.org,\n", encoding="utf-8")
    with pytest.raises(IPOMonthlyCountsError):
        load_theme_adr_additions(tmp_path)
    path.write_text(",".join(THEME_ADR_FIELDS) + "\n"
                    "2026-07,ai,semiconductor,CXMT,,Shanghai STAR,A-share,https://example.org,\n", encoding="utf-8")
    with pytest.raises(IPOMonthlyCountsError):
        load_theme_adr_additions(tmp_path)


def test_published_ipo_chart_discloses_the_additions_and_spac_rule() -> None:
    payload = json.loads((ROOT / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8"))
    chart = next(c for c in payload["charts"] if c["id"] == "ipo_count_operating_12m")
    assert chart["definition"] == "ritter_net_plus_theme_adr_ipos_trailing_12_month_sum"
    assert any(row["company"] == "SK hynix" for row in chart["theme_adr_additions"])
    assert "SPAC은 닷컴기" in chart["caveat"]
