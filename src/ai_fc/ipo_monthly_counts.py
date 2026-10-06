"""미국 운영기업 IPO 월별 건수 — Ritter IPOALL(확정) + Nasdaq 캘린더(잠정).

2026-10-06 사용자 결정으로 닷컴 대비 과열도(``dotcom_overheat_index_v2``)에 IPO 건수가
들어간다. 정의는 Jay Ritter 의 **net** 건수 — SPAC·폐쇄형 펀드·REIT·유닛·ADR·공모가
$5 미만·은행/S&L·LP·CRSP 미등재를 뺀 운영기업 IPO 다.

두 원천의 지위는 다르다.

* **확정 (Ritter IPOALL.xlsx)** — 지수 입력. 원본 바이트는 공식 저장소 raw 에
  content-addressed 로 남기고(영수증 = raw_receipts.jsonl), 파싱한 월별 표
  (``ritter_ipoall_monthly.json``)는 그 sha256 을 고정해 가리킨다. 연 1회 개정된다.
* **잠정 (Nasdaq IPO 캘린더 API)** — Ritter 마지막 확정월 **이후** 달만, 차트의 점선으로만
  쓴다. 운영기업을 이름·가격 규칙으로 근사할 뿐이라 Ritter net 보다 많이 센다
  (2023~2025 실측: 87·103·116 vs 54·72·90, 필터 v1). 지수에도, 확정 계열에도 섞지 않는다.
  Ritter 가 새 달을 게시하면 그 달은 확정 계열이 대체한다.

Nasdaq API 는 브라우저형 User-Agent 를 요구한다. 저장소의 일반 원칙(UA 위장 금지 —
CNN 사례)의 예외이며, **이 엔드포인트 하나에 한해** 사용자가 2026-10-06 승인했다.
거래 목록은 저장하지 않고 월별 건수만 남긴다(재배포 주의).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

RITTER_IPOALL_URL = "https://site.warrington.ufl.edu/ritter/files/IPOALL.xlsx"
RITTER_POLICY_SOURCE_ID = "ritter_ipoall_monthly"
RITTER_SERIES_ID = "RITTER_IPOALL_MONTHLY"
RITTER_TABLE_RELATIVE = Path("data/statistics/ipo/ritter_ipoall_monthly.json")
RITTER_PARSER_VERSION = "ritter-ipoall-monthly-v1"
RITTER_USER_AGENT = "JinsInvestingIPOReferenceBatch/1.0 (+public research dashboard)"

NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/ipo/calendar?date={month}"
NASDAQ_SOURCE_ID = "NASDAQ_IPO_CALENDAR_MONTHLY"
NASDAQ_POLICY_SOURCE_ID = "nasdaq_ipo_calendar"
NASDAQ_TABLE_RELATIVE = Path("data/statistics/ipo/nasdaq_calendar_monthly.json")
NASDAQ_FILTER_VERSION = "nasdaq-operating-approx-v1"
#: 2026-10-06 사용자 승인 — 이 엔드포인트에 한한 브라우저형 UA. 다른 원천에 쓰지 않는다.
NASDAQ_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
NASDAQ_UA_AUTHORIZATION = {
    "authorized_by": "repository_owner",
    "authorized_on": "2026-10-06",
    "scope": "api.nasdaq.com/api/ipo/calendar only",
    "note": "browser-like User-Agent required by the endpoint; exception to the no-UA-spoofing stance",
}
NASDAQ_REQUEST_INTERVAL_SECONDS = 0.5
STATUS_RELATIVE = Path("data/statistics/ipo/monthly_counts_status.json")

TRAILING_MONTHS = 12

#: Ritter net 과 Nasdaq 근사 필터 v1 의 연간 비교 실측(2026-10-06, 같은 API 월별 응답 36개). 잠정치가 과대계상이라는
#: 표시 근거다 — 계산에 쓰지 않는다.
NASDAQ_OVERCOUNT_MEASURED = (
    {"year": 2023, "nasdaq_operating_approx": 87, "ritter_net": 54},
    {"year": 2024, "nasdaq_operating_approx": 103, "ritter_net": 72},
    {"year": 2025, "nasdaq_operating_approx": 116, "ritter_net": 90},
)


class IPOMonthlyCountsError(ValueError):
    pass


# ── Ritter IPOALL ──────────────────────────────────────────────────────────


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _count(value: Any, *, label: str) -> int | None:
    """정수 건수 또는 None. 'see 1975'·'na'·'.'·빈칸은 '없음'이지 0 이 아니다."""
    if value is None or isinstance(value, str):
        return None
    if not _is_number(value):
        raise IPOMonthlyCountsError(f"IPOALL {label} is not a count: {value!r}")
    number = float(value)
    if not number.is_integer() or number < 0:
        raise IPOMonthlyCountsError(f"IPOALL {label} is not a non-negative integer: {value!r}")
    return int(number)


def ritter_year(two_digit: int) -> int:
    """IPOALL 의 연도는 두 자리다 — 60~99 는 1900년대, 00~59 는 2000년대."""
    if not 0 <= two_digit <= 99:
        raise IPOMonthlyCountsError(f"IPOALL year out of range: {two_digit}")
    return 1900 + two_digit if two_digit >= 60 else 2000 + two_digit


def parse_ritter_ipoall_rows(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """IPOALL 시트 행 → [{month: 'YYYY-MM', gross, net}] (오름차순·연속).

    열 0=월, 1=두 자리 연도, 3=gross, 4=net. 월·연도가 숫자가 아닌 행(설명문)은 건너뛴다.
    """
    by_month: dict[str, dict[str, Any]] = {}
    for row in rows:
        if len(row) < 4 or not _is_number(row[0]) or not _is_number(row[1]):
            continue
        month_number, year_number = float(row[0]), float(row[1])
        if not month_number.is_integer() or not year_number.is_integer():
            raise IPOMonthlyCountsError(f"IPOALL month/year not integral: {row[:2]!r}")
        month = int(month_number)
        if not 1 <= month <= 12:
            raise IPOMonthlyCountsError(f"IPOALL month out of range: {month}")
        year = ritter_year(int(year_number))
        key = f"{year:04d}-{month:02d}"
        if key in by_month:
            raise IPOMonthlyCountsError(f"IPOALL duplicate month: {key}")
        by_month[key] = {
            "month": key,
            "gross": _count(row[3], label=f"{key} gross"),
            "net": _count(row[4] if len(row) > 4 else None, label=f"{key} net"),
        }
    if not by_month:
        raise IPOMonthlyCountsError("IPOALL has no monthly rows")
    ordered = [by_month[key] for key in sorted(by_month)]
    for prior, current in zip(ordered, ordered[1:]):
        if _month_index(current["month"]) != _month_index(prior["month"]) + 1:
            raise IPOMonthlyCountsError(
                f"IPOALL months not contiguous: {prior['month']} -> {current['month']}"
            )
    return ordered


def parse_ritter_ipoall(raw: bytes) -> list[dict[str, Any]]:
    from .statistics_lab import StatisticsLabError, _xlsx_sheet_rows

    try:
        rows = _xlsx_sheet_rows(raw, "IPOALL")
    except StatisticsLabError as exc:
        raise IPOMonthlyCountsError(f"IPOALL workbook unreadable: {exc}") from exc
    return parse_ritter_ipoall_rows(rows)


def last_confirmed_month(months: list[dict[str, Any]]) -> str | None:
    """net 값이 있는 마지막 달. 이후 빈 행이 있어도 그 달까지가 확정이다."""
    confirmed = [row["month"] for row in months if row.get("net") is not None]
    return confirmed[-1] if confirmed else None


# ── Nasdaq calendar (provisional) ──────────────────────────────────────────

_NON_OPERATING_NAME = re.compile(
    r"\b(acquisition|acquisitions|merger|spac|blank\s+check|fund|trust|reit|etf|"
    r"notes?|units?|capital\s+corp(oration)?)\b",
    re.IGNORECASE,
)
_PRICE = re.compile(r"\d+(?:\.\d+)?")


def _first_price(value: Any) -> float | None:
    if value is None:
        return None
    match = _PRICE.search(str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def nasdaq_row_is_operating(row: dict[str, Any]) -> bool:
    """운영기업 근사 — SPAC·펀드·신탁·REIT·ETF·채권·유닛·$5 미만을 뺀다.

    이름·티커·가격만 보는 규칙이라 ADR·은행·LP·CRSP 미등재는 걸러내지 못한다 → 과대계상.
    가격이 비어 있으면(미공시) 남긴다.
    """
    name = str(row.get("companyName") or "")
    if _NON_OPERATING_NAME.search(name):
        return False
    ticker = str(row.get("proposedTickerSymbol") or "").strip().upper()
    if len(ticker) == 5 and ticker.endswith("U"):      # Nasdaq 5자리 티커 접미 U = 유닛
        return False
    price = _first_price(row.get("proposedSharePrice"))
    if price is not None and price < 5.0:
        return False
    return True


def count_nasdaq_month(raw: bytes) -> dict[str, int]:
    """캘린더 응답 → {priced_total, operating_approx}. 거래 목록은 반환하지 않는다."""
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise IPOMonthlyCountsError("Nasdaq calendar response is not JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or "priced" not in data:
        raise IPOMonthlyCountsError("Nasdaq calendar response has no priced section")
    priced = data.get("priced") or {}
    rows = priced.get("rows") or []
    if not isinstance(rows, list):
        raise IPOMonthlyCountsError("Nasdaq priced rows malformed")
    return {
        "priced_total": len(rows),
        "operating_approx": sum(1 for row in rows if isinstance(row, dict) and nasdaq_row_is_operating(row)),
    }


# ── series ─────────────────────────────────────────────────────────────────


def _month_index(month: str) -> int:
    year, number = month.split("-")
    return int(year) * 12 + int(number) - 1


def _month_from_index(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def trailing_sums(monthly: dict[str, int | None], window: int = TRAILING_MONTHS) -> dict[str, int]:
    """연속 ``window`` 개월이 모두 있는 달에만 합계를 낸다(빈 달을 0 으로 채우지 않는다)."""
    result: dict[str, int] = {}
    for month in monthly:
        end = _month_index(month)
        values = [monthly.get(_month_from_index(end - offset)) for offset in range(window)]
        if all(value is not None for value in values):
            result[month] = int(sum(values))  # type: ignore[arg-type]
    return result


def nasdaq_month_is_complete(month: str, fetched_at: str) -> bool:
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    return _month_index(month) < fetched.year * 12 + fetched.month - 1


def ipo_count_series(
    ritter: dict[str, Any], nasdaq: dict[str, Any] | None,
) -> dict[str, Any]:
    """확정 12개월 합계(월별) + 확정월 이후 잠정 12개월 합계.

    잠정 = Ritter 확정월은 확정치, 그 이후 달은 Nasdaq 근사치로 채운 12개월 합. 확정
    계열에는 Nasdaq 값이 한 건도 들어가지 않는다.
    """
    months = ritter.get("months") or []
    net = {row["month"]: row.get("net") for row in months}
    last = ritter.get("last_confirmed_month") or last_confirmed_month(months)
    if last is None:
        raise IPOMonthlyCountsError("Ritter table has no confirmed month")
    confirmed_net = {month: value for month, value in net.items() if _month_index(month) <= _month_index(last)}
    confirmed = trailing_sums(confirmed_net)
    provisional: dict[str, int] = {}
    provisional_months: list[dict[str, Any]] = []
    if nasdaq:
        extension: dict[str, int | None] = dict(confirmed_net)
        for month, row in sorted((nasdaq.get("months") or {}).items()):
            if _month_index(month) <= _month_index(last):
                continue
            if not row.get("complete"):
                continue
            extension[month] = int(row["operating_approx"])
            provisional_months.append({"month": month, "operating_approx": int(row["operating_approx"]),
                                       "priced_total": int(row["priced_total"])})
        # 확정월 다음 달부터 끊김 없이 이어진 달까지만 잠정 합계를 낸다.
        cursor = _month_index(last) + 1
        while _month_from_index(cursor) in extension:
            cursor += 1
        sums = trailing_sums(extension)
        provisional = {
            month: value for month, value in sums.items()
            if _month_index(last) < _month_index(month) < cursor
        }
    return {
        "last_confirmed_month": last,
        "confirmed": confirmed,
        "provisional": provisional,
        "provisional_months": [row for row in provisional_months if row["month"] in provisional],
    }


# ── refresh (network) ──────────────────────────────────────────────────────


def _ritter_fetch(url: str) -> tuple[bytes, int, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": RITTER_USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), int(response.status), response.headers.get("Last-Modified")


def _nasdaq_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": NASDAQ_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


_FETCH_ERRORS = (OSError, urllib.error.URLError, TimeoutError, ValueError)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def refresh_ritter_table(
    root: Path, *, checked_at: str,
    fetcher: Callable[[str], tuple[bytes, int, str | None]] = _ritter_fetch,
) -> dict[str, Any]:
    """IPOALL 을 받아 바뀌었을 때만 raw 영수증을 남기고 월별 표를 다시 쓴다.

    실패는 조용히 덮지 않는다 — 기존 표를 그대로 두고 상태에 이유를 남긴다.
    """
    from .authoritative_statistics import load_authoritative_source_policy, persist_raw_artifact

    table_path = root / RITTER_TABLE_RELATIVE
    previous = _read_json(table_path)
    try:
        body, http_status, last_modified = fetcher(RITTER_IPOALL_URL)
    except _FETCH_ERRORS as exc:
        return {"status": "fetch_failed", "error": type(exc).__name__, "table_kept": previous is not None}
    digest = hashlib.sha256(body).hexdigest()
    if previous and previous.get("raw_sha256") == digest:
        return {"status": "current", "raw_sha256": digest,
                "last_confirmed_month": previous.get("last_confirmed_month")}
    try:
        months = parse_ritter_ipoall(body)
    except IPOMonthlyCountsError as exc:
        return {"status": "parse_failed", "error": str(exc), "raw_sha256": digest,
                "table_kept": previous is not None}
    policy_path = root / "data/contracts/authoritative_statistics_sources.yaml"
    if not policy_path.is_file():
        policy_path = Path(__file__).resolve().parents[2] / "data/contracts/authoritative_statistics_sources.yaml"
    receipt = persist_raw_artifact(
        root / "data/statistics/official_store",
        load_authoritative_source_policy(policy_path),
        source_id=RITTER_POLICY_SOURCE_ID,
        payload=body,
        source_uri=RITTER_IPOALL_URL,
        fetched_at=checked_at,
        http_status=http_status,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        series_ids=[f"{RITTER_SERIES_ID}.gross", f"{RITTER_SERIES_ID}.net"],
    )
    revisions: list[dict[str, Any]] = list((previous or {}).get("revisions") or [])
    changed_months: list[str] = []
    if previous:
        old = {row["month"]: (row.get("gross"), row.get("net")) for row in previous.get("months") or []}
        changed_months = [
            row["month"] for row in months
            if row["month"] in old and old[row["month"]] != (row["gross"], row["net"])
        ]
        revisions.append({
            "superseded_raw_sha256": previous.get("raw_sha256"),
            "superseded_fetched_at": previous.get("fetched_at"),
            "superseded_last_confirmed_month": previous.get("last_confirmed_month"),
            "revised_existing_months": len(changed_months),
        })
    table = {
        "schema_version": 1,
        "dataset_id": "ritter_ipoall_monthly_v1",
        "series_id": RITTER_SERIES_ID,
        "policy_source_id": RITTER_POLICY_SOURCE_ID,
        "title": "U.S. IPO monthly gross and net counts (IPOALL)",
        "provider": "Jay R. Ritter, University of Florida",
        "source_url": RITTER_IPOALL_URL,
        "parser_version": RITTER_PARSER_VERSION,
        "definition": {
            "net": "operating-company IPOs; excludes SPACs, closed-end funds, REITs, unit offers, ADRs, "
                   "offer prices below $5, banks and S&Ls, limited partnerships, and non-CRSP listings",
            "gross": "all IPOs including SPACs, direct listings, penny stocks, units and closed-end funds",
        },
        "revision_cadence": "author_revises_roughly_annually",
        "raw_sha256": digest,
        "raw_path": receipt.artifact_path,
        "receipt_id": receipt.receipt_id,
        "http_status": http_status,
        "last_modified": last_modified,
        "fetched_at": checked_at,
        "available_at": checked_at,
        "first_month": months[0]["month"],
        "last_month": months[-1]["month"],
        "last_confirmed_month": last_confirmed_month(months),
        "months": months,
        "revisions": revisions,
    }
    _write_json(table_path, table)
    return {"status": "updated", "raw_sha256": digest,
            "last_confirmed_month": table["last_confirmed_month"],
            "revised_existing_months": len(changed_months)}


def _months_between(first: str, last: str) -> list[str]:
    return [_month_from_index(index) for index in range(_month_index(first), _month_index(last) + 1)]


def refresh_nasdaq_table(
    root: Path, *, now: datetime,
    fetcher: Callable[[str], bytes] = _nasdaq_fetch,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """확정월 이후 달 — 비어 있으면 한 번 채우고, 이번 달·지난달은 매번 다시 센다.

    실패한 달은 기존 값을 두고 stale 로 표시한다(통계 갱신을 막지 않는다).
    """
    ritter = _read_json(root / RITTER_TABLE_RELATIVE)
    if not ritter or not ritter.get("last_confirmed_month"):
        return {"status": "skipped", "reason": "ritter table unavailable"}
    table_path = root / NASDAQ_TABLE_RELATIVE
    previous = _read_json(table_path) or {}
    stored: dict[str, dict[str, Any]] = dict(previous.get("months") or {})
    current_month = f"{now.year:04d}-{now.month:02d}"
    first = _month_from_index(_month_index(ritter["last_confirmed_month"]) + 1)
    targets = _months_between(first, current_month) if _month_index(first) <= _month_index(current_month) else []
    previous_month = _month_from_index(_month_index(current_month) - 1)
    fetched_at = now.isoformat(timespec="seconds")
    errors: list[dict[str, str]] = []
    requested = 0
    for month in targets:
        row = stored.get(month)
        if row and row.get("complete") and month not in {current_month, previous_month}:
            continue
        if requested:
            sleep(NASDAQ_REQUEST_INTERVAL_SECONDS)
        requested += 1
        try:
            body = fetcher(NASDAQ_CALENDAR_URL.format(month=month))
            counts = count_nasdaq_month(body)
        except (*_FETCH_ERRORS, IPOMonthlyCountsError) as exc:
            errors.append({"month": month, "error": type(exc).__name__})
            if row:
                stored[month] = {**row, "stale": True}
            continue
        stored[month] = {
            **counts,
            "fetched_at": fetched_at,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "complete": nasdaq_month_is_complete(month, fetched_at),
            "stale": False,
        }
    # Ritter 가 확정한 달은 잠정 표에서 내린다 — 확정치가 대체한다.
    kept = {month: row for month, row in sorted(stored.items()) if month in targets}
    table = {
        "schema_version": 1,
        "dataset_id": "nasdaq_ipo_calendar_monthly_v1",
        "source_id": NASDAQ_SOURCE_ID,
        "policy_source_id": NASDAQ_POLICY_SOURCE_ID,
        "usage": "provisional_display_only",
        "index_input": False,
        "source_url_template": NASDAQ_CALENDAR_URL,
        "access": {"user_agent": "browser_like", **NASDAQ_UA_AUTHORIZATION},
        "filter_version": NASDAQ_FILTER_VERSION,
        "filter_rules": [
            "exclude names matching acquisition/merger/SPAC/blank check/capital corp",
            "exclude names matching fund/trust/REIT/ETF/notes/units",
            "exclude 5-letter tickers ending in U (units)",
            "exclude proposed price below $5 (missing price kept)",
        ],
        "known_bias": "overcounts versus Ritter net (ADRs, banks, LPs, non-CRSP not screened)",
        "overcount_measured": list(NASDAQ_OVERCOUNT_MEASURED),
        "stores": "monthly counts only; no deal lists",
        "provisional_after": ritter["last_confirmed_month"],
        "status": "stale" if errors else "current",
        "months": kept,
    }
    _write_json(table_path, table)
    return {"status": table["status"], "requested": requested, "errors": errors,
            "months": {month: row["operating_approx"] for month, row in kept.items()}}


def refresh_ipo_monthly_counts(
    root: Path, *, now: datetime | None = None,
    ritter_fetcher: Callable[[str], tuple[bytes, int, str | None]] = _ritter_fetch,
    nasdaq_fetcher: Callable[[str], bytes] = _nasdaq_fetch,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Path, dict[str, Any]]:
    moment = now or datetime.now(timezone.utc)
    checked_at = moment.isoformat(timespec="seconds")
    ritter = refresh_ritter_table(root, checked_at=checked_at, fetcher=ritter_fetcher)
    nasdaq = refresh_nasdaq_table(root, now=moment, fetcher=nasdaq_fetcher, sleep=sleep)
    status = {
        "schema_version": 1,
        "dataset_id": "ipo_monthly_counts_status_v1",
        "checked_at": checked_at,
        "ritter": ritter,
        "nasdaq": nasdaq,
        "index_input": "ritter_net_confirmed_only",
    }
    path = root / STATUS_RELATIVE
    _write_json(path, status)
    return path, status


def load_ipo_monthly_tables(root: Path) -> dict[str, Any] | None:
    """통계 빌드용 — Ritter 표가 없으면 None. raw 영수증 바이트와 sha 를 대조한다."""
    ritter = _read_json(root / RITTER_TABLE_RELATIVE)
    if ritter is None:
        return None
    raw_path = root / "data/statistics/official_store" / str(ritter.get("raw_path") or "")
    if raw_path.is_file() and hashlib.sha256(raw_path.read_bytes()).hexdigest() != ritter.get("raw_sha256"):
        raise IPOMonthlyCountsError("Ritter table raw_sha256 does not match its raw artifact")
    return {"ritter": ritter, "nasdaq": _read_json(root / NASDAQ_TABLE_RELATIVE)}


def month_start(month: str) -> str:
    year, number = month.split("-")
    return date(int(year), int(number), 1).isoformat()
