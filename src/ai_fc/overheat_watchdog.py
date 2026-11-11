"""닷컴 대비 과열도 자동 감시 — 갱신 파이프라인 바깥에서 매일 '정말 최신인가' 를 독립적으로 확인한다.

2026-11-10 사용자 지시: "항상 잘 업데이트 되는지 자동 감시 기능 넣어놔".

statistics-refresh 안의 14종 감사(``statistics-freshness``)는 같은 실행 안에서 돌기 때문에 ① 예약 실행 자체가
멈추면 아무것도 말하지 않고, ② 자료 나이 상한(월간 75일·분기 180일)으로 보므로 원천이 새 발표를 냈는데 우리가
놓친 경우를 몇 달 뒤에야 잡는다. 실제로 놓친 사례들(2026-09 주 1회 예약 시절 Z.1 7일 지연, 2026-10-27 census.gov
지연으로 전체 갱신 중단, 2026-11 JPX 파일명 변형으로 자동 판정 정지)은 모두 '실행은 됐거나 안 됐는데 아무도 몰랐던'
경우였다. 이 감시는 별도 예약으로 돌며 다음을 결정론으로 확인한다(LLM 없음).

1. 원천 대조 — 지표 입력 계열마다 FRED 의 최신 관측일이 스냅샷보다 새로운데, 그 발표가 ``SOURCE_GRACE_HOURS`` 보다
   오래됐으면 실패(새 발표 미반영). Z.1 직접 수집 계열은 FRED 미러(BOGZ1…Q)로 대조한다.
2. 갱신 생존 신호 — 스냅샷 생성 시각과 마지막 성공한 statistics-refresh 가 ``REFRESH_MAX_HOURS`` 안인가.
3. 라이브 사이트 — 배포된 data.json 의 과열도가 14개 지표를 모두 싣고, 저장소 스냅샷보다 늦지 않은가.
4. 지표 구성 — 계약의 14종이 모두 지수에 들어갔는가(skipped 0).
5. IPO 원천 — Ritter·Nasdaq 상태, 잠정 계열이 지난달까지 닫혔는가.
6. 테마 상장 감시 — 시장별 수집 성공, 판정 대기 적체, 활발한 시장이 오래 0건인지(파서 고장 의심), 홍콩 보고서 지연.

결과는 ``ok`` · ``warn`` · ``fail`` 로 나뉘고, 워크플로가 fail/warn 을 라벨 이슈 하나로 올렸다가 모두 해소되면 닫는다.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

CONTRACT_RELATIVE = Path("data/contracts/dotcom_overheat_index_v5.yaml")
SNAPSHOT_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")
IPO_STATUS_RELATIVE = Path("data/statistics/ipo/monthly_counts_status.json")
WATCH_RELATIVE = Path("data/statistics/ipo/theme_listing_watch.json")
LIVE_DATA_URL = "https://sung-jinpark.github.io/Jin-s-investing-prediction/data.json"
FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series?series_id={sid}&file_type=json&api_key={key}"
USER_AGENT = "JinsInvestingOverheatWatchdog/1.0 (+public research dashboard)"

#: 원천이 새 관측을 올린 뒤 이 시간 안에 반영되지 않으면 실패 — 하루 3번 갱신 + 예약 지연(2~5h 실측)을 넉넉히 덮는다.
SOURCE_GRACE_HOURS = 48
#: 스냅샷·마지막 성공 실행이 이보다 오래되면 갱신이 멈춘 것이다(예약은 하루 3번).
REFRESH_MAX_HOURS = 36
#: 배포본이 저장소 스냅샷보다 이만큼 늦으면 Pages 배포가 멈춘 것이다.
LIVE_MAX_LAG_HOURS = 12
#: 상장이 꾸준한 시장이 이 기간 동안 한 건도 안 잡히면 파서·원천 형식 변경을 의심한다(경고).
ACTIVE_VENUES = ("cn_a", "hk_main", "kr", "jp", "tw_twse", "tw_tpex")
SILENT_VENUE_DAYS = 45
#: 홍콩 New Listing Report 는 2주 남짓 간격으로 갱신된다 — 이보다 오래 멈추면 경고.
HK_REPORT_MAX_LAG_DAYS = 35
#: Z.1 직접 수집 계열의 FRED 미러(같은 Financial Accounts 코드).
FRED_MIRRORS = {"FL663067003": "BOGZ1FL663067003Q", "FL103163005": "BOGZ1FL103163005Q",
                "FA103163005": "BOGZ1FA103163005Q"}
NON_FRED_SOURCES = {"RITTER_IPOALL_MONTHLY"}


def _now(value: datetime | None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # FRED last_updated: '2026-11-06 16:03:36-06'
    text = text.replace(" ", "T", 1) if "T" not in text and " " in text else text
    if len(text) >= 3 and text[-3] in "+-" and text[-2:].isdigit() and ":" not in text[-3:]:
        text += ":00"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _finding(check: str, status: str, subject: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "subject": subject, "detail": detail}


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fred_series_meta(sid: str, *, key: str, get: Callable[[str], bytes] = _get) -> dict[str, str]:
    payload = json.loads(get(FRED_SERIES_URL.format(sid=sid, key=key)).decode("utf-8"))
    row = (payload.get("seriess") or [{}])[0]
    return {"observation_end": str(row.get("observation_end") or ""), "last_updated": str(row.get("last_updated") or "")}


# ── 개별 점검 ────────────────────────────────────────────────────────────


def check_indicator_coverage(snapshot: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, str]]:
    """계약의 지표가 스냅샷 차트에 모두 있는가 — 차트가 빠지면 지수가 조용히 지표를 건너뛴다."""
    charts = {chart.get("id") for chart in snapshot.get("charts") or []}
    missing = [spec["id"] for spec in contract.get("indicators") or [] if spec.get("chart") not in charts]
    if missing:
        return [_finding("coverage", "fail", ", ".join(missing), "계약 지표의 통계 차트가 스냅샷에 없다")]
    return [_finding("coverage", "ok", f"{len(contract.get('indicators') or [])}종", "계약 지표 차트 모두 있음")]


def check_source_currency(snapshot: dict[str, Any], contract: dict[str, Any], *, now: datetime,
                          fred: Callable[[str], dict[str, str]]) -> list[dict[str, str]]:
    """지표 입력 계열마다 원천(FRED) 최신 관측일 대 스냅샷 최신 관측일."""
    charts = {chart.get("id"): chart for chart in snapshot.get("charts") or []}
    sources = {row["series_id"]: row for row in snapshot.get("sources") or []}
    wanted: dict[str, list[str]] = {}
    for spec in contract.get("indicators") or []:
        for sid in (charts.get(spec.get("chart")) or {}).get("source_ids") or []:
            if sid not in NON_FRED_SOURCES:
                wanted.setdefault(sid, []).append(spec["id"])
    findings = []
    for sid, indicators in sorted(wanted.items()):
        ours = str((sources.get(sid) or {}).get("latest_observation") or "")
        mirror = FRED_MIRRORS.get(sid, sid)
        try:
            meta = fred(mirror)
        except Exception as exc:  # noqa: BLE001 — 감시는 원천 하나 실패로 멈추지 않는다
            findings.append(_finding("source_currency", "warn", sid, f"FRED 메타 조회 실패({type(exc).__name__}) — 대조 못 함"))
            continue
        theirs = meta["observation_end"]
        published = _ts(meta["last_updated"])
        label = f"{sid} ({', '.join(indicators)})"
        if not ours or not theirs:
            findings.append(_finding("source_currency", "warn", label, f"관측일 비교 불가 (우리 {ours or '-'} · 원천 {theirs or '-'})"))
        elif theirs > ours:
            age = (now - published).total_seconds() / 3600 if published else None
            if age is None or age > SOURCE_GRACE_HOURS:
                findings.append(_finding("source_currency", "fail", label,
                                         f"원천에 새 관측 {theirs} (발표 {meta['last_updated']}) — 스냅샷은 {ours}에 머묾"))
            else:
                findings.append(_finding("source_currency", "ok", label,
                                         f"원천 새 관측 {theirs} 발표 {age:.0f}시간 전 — 반영 유예 중"))
        else:
            findings.append(_finding("source_currency", "ok", label, f"원천 최신 {theirs} = 스냅샷 {ours}"))
    return findings


def check_refresh_alive(snapshot: dict[str, Any], *, now: datetime,
                        last_success: str | None) -> list[dict[str, str]]:
    findings = []
    generated = _ts(snapshot.get("generated_at"))
    if generated is None or (now - generated) > timedelta(hours=REFRESH_MAX_HOURS):
        findings.append(_finding("refresh_alive", "fail", "통계 스냅샷",
                                 f"생성 {snapshot.get('generated_at') or '-'} — {REFRESH_MAX_HOURS}시간 넘게 재생성 안 됨"))
    else:
        findings.append(_finding("refresh_alive", "ok", "통계 스냅샷", f"생성 {snapshot.get('generated_at')}"))
    if last_success is not None:
        moment = _ts(last_success)
        if moment is None or (now - moment) > timedelta(hours=REFRESH_MAX_HOURS):
            findings.append(_finding("refresh_alive", "fail", "statistics-refresh",
                                     f"마지막 성공 실행 {last_success or '-'} — 예약 실행이 멈췄거나 계속 실패"))
        else:
            findings.append(_finding("refresh_alive", "ok", "statistics-refresh", f"마지막 성공 {last_success}"))
    waiting = (snapshot.get("source_refresh") or {}).get("waiting_series") or []
    if waiting:
        findings.append(_finding("refresh_alive", "warn", "원천 대기",
                                 f"이전 검증값으로 버티는 계열: {', '.join(waiting)}"))
    return findings


def check_live_site(snapshot: dict[str, Any], live: dict[str, Any] | None, *, contract: dict[str, Any]) -> list[dict[str, str]]:
    if live is None:
        return [_finding("live_site", "fail", "data.json", "배포된 사이트 데이터를 읽지 못함")]
    index = live.get("dotcom_overheat") or {}
    expected = len(contract.get("indicators") or [])
    findings = []
    if index.get("status") != "ok" or index.get("overheat_pct") is None:
        findings.append(_finding("live_site", "fail", "과열도", f"사이트 과열도 상태 {index.get('status')}"))
    elif int(index.get("included") or 0) != expected or index.get("skipped"):
        skipped = ", ".join(str(row.get("id")) for row in index.get("skipped") or [])
        findings.append(_finding("live_site", "fail", "과열도",
                                 f"지표 {index.get('included')}/{expected}종만 반영 — 빠진 지표: {skipped or '-'}"))
    else:
        findings.append(_finding("live_site", "ok", "과열도", f"{index.get('overheat_pct')}% · 지표 {expected}종 모두"))
    ours, theirs = _ts(snapshot.get("generated_at")), _ts(index.get("generated_at"))
    if ours and theirs and (ours - theirs) > timedelta(hours=LIVE_MAX_LAG_HOURS):
        findings.append(_finding("live_site", "fail", "배포 시점",
                                 f"사이트 {index.get('generated_at')} < 저장소 {snapshot.get('generated_at')} — Pages 배포 멈춤"))
    elif ours and theirs:
        findings.append(_finding("live_site", "ok", "배포 시점", f"사이트 {index.get('generated_at')}"))
    return findings


def _previous_month(today: date) -> str:
    first = today.replace(day=1)
    last = first - timedelta(days=1)
    return f"{last.year:04d}-{last.month:02d}"


def check_ipo_sources(status: dict[str, Any] | None, *, now: datetime) -> list[dict[str, str]]:
    if not status:
        return [_finding("ipo_sources", "fail", "IPO 상태", "monthly_counts_status.json 없음")]
    findings = []
    checked = _ts(status.get("checked_at"))
    if checked is None or (now - checked) > timedelta(hours=REFRESH_MAX_HOURS):
        findings.append(_finding("ipo_sources", "fail", "IPO 수집", f"마지막 확인 {status.get('checked_at')}"))
    for name in ("ritter", "nasdaq"):
        state = (status.get(name) or {}).get("status")
        errors = (status.get(name) or {}).get("errors") or []
        detail = f"상태 {state}" + (" — " + ", ".join(f"{row.get('month')} {row.get('error')}" for row in errors)
                                     if errors else "")
        findings.append(_finding("ipo_sources", "ok" if state == "current" else "fail", name, detail))
    months = sorted(((status.get("nasdaq") or {}).get("months") or {}).keys())
    expected = _previous_month(now.date())
    if now.day > 5 and (not months or months[-1] < expected):
        findings.append(_finding("ipo_sources", "fail", "Nasdaq 잠정", f"지난달({expected}) 건수가 없음 — 마지막 {months[-1] if months else '-'}"))
    return findings


def check_theme_watch(watch: dict[str, Any] | None, *, now: datetime) -> list[dict[str, str]]:
    if not watch:
        return [_finding("theme_watch", "fail", "테마 상장 감시", "theme_listing_watch.json 없음")]
    findings = []
    checked = _ts(watch.get("checked_at"))
    if checked is None or (now - checked) > timedelta(hours=REFRESH_MAX_HOURS):
        findings.append(_finding("theme_watch", "fail", "감시 실행", f"마지막 확인 {watch.get('checked_at')}"))
    for venue, state in sorted((watch.get("venues") or {}).items()):
        ok_at = _ts(state.get("last_ok_at"))
        if state.get("status") != "current" and (ok_at is None or (now - ok_at) > timedelta(days=3)):
            findings.append(_finding("theme_watch", "fail", venue,
                                     f"3일 넘게 수집 실패 — {str(state.get('error') or '')[:120]}"))
    summary = watch.get("summary") or {}
    if int(summary.get("pending_overdue") or 0):
        findings.append(_finding("theme_watch", "fail", "판정 대기",
                                 f"7일 넘게 판정 못 한 상장 {summary.get('pending_overdue')}건 — 사업 설명 원천 확인"))
    elif int(summary.get("pending_review") or 0):
        findings.append(_finding("theme_watch", "warn", "판정 대기",
                                 f"판정 대기 {summary.get('pending_review')}건(유예 중) — 가장 오래된 상장 {summary.get('oldest_pending_listing')}"))
    latest: dict[str, str] = {}
    for row in watch.get("listings") or []:
        latest[row["venue"]] = max(latest.get(row["venue"], ""), str(row.get("listing_date") or ""))
    start = _ts(f"{watch.get('watch_start') or '2026-10-01'}T00:00:00+00:00")
    for venue in ACTIVE_VENUES:
        last = latest.get(venue)
        reference = _ts(f"{last}T00:00:00+00:00") if last else start
        if reference and (now - reference) > timedelta(days=SILENT_VENUE_DAYS):
            findings.append(_finding("theme_watch", "warn", venue,
                                     f"{SILENT_VENUE_DAYS}일 넘게 신규상장 0건(마지막 {last or '-'}) — 원천 형식 변경 의심"))
    hk_last = latest.get("hk_main")
    if hk_last and (now.date() - date.fromisoformat(hk_last)) > timedelta(days=HK_REPORT_MAX_LAG_DAYS):
        findings.append(_finding("theme_watch", "warn", "hk_main",
                                 f"홍콩 New Listing Report 가 {hk_last} 이후로 갱신되지 않음"))
    if not findings:
        findings.append(_finding("theme_watch", "ok", "테마 상장 감시",
                                 f"시장 {summary.get('venues_ok')}/{summary.get('venues_total')} · 판정 대기 0"))
    return findings


# ── 종합 ─────────────────────────────────────────────────────────────────


def run_watchdog(root: Path, *, now: datetime | None = None, fred_key: str | None = None,
                 last_success: str | None = None, live: dict[str, Any] | None | str = "fetch",
                 get: Callable[[str], bytes] = _get) -> dict[str, Any]:
    """모든 점검을 돌려 결과를 모은다. ``live='fetch'`` 면 배포본을 직접 읽는다."""
    moment = _now(now)
    contract = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    snapshot = json.loads((root / SNAPSHOT_RELATIVE).read_text(encoding="utf-8"))

    def read(relative: Path) -> dict[str, Any] | None:
        path = root / relative
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    if live == "fetch":
        try:
            live = json.loads(get(f"{LIVE_DATA_URL}?t={int(moment.timestamp())}").decode("utf-8"))
        except Exception:  # noqa: BLE001
            live = None
    findings = check_indicator_coverage(snapshot, contract)
    if fred_key:
        findings += check_source_currency(snapshot, contract, now=moment,
                                          fred=lambda sid: fred_series_meta(sid, key=fred_key, get=get))
    else:
        findings.append(_finding("source_currency", "warn", "FRED", "FRED_API_KEY 없음 — 원천 대조 생략"))
    findings += check_refresh_alive(snapshot, now=moment, last_success=last_success)
    findings += check_live_site(snapshot, live if isinstance(live, dict) else None, contract=contract)
    findings += check_ipo_sources(read(IPO_STATUS_RELATIVE), now=moment)
    findings += check_theme_watch(read(WATCH_RELATIVE), now=moment)
    counts = {state: sum(1 for row in findings if row["status"] == state) for state in ("fail", "warn", "ok")}
    return {
        "schema_version": 1,
        "dataset_id": "overheat_watchdog_v1",
        "checked_at": moment.isoformat(timespec="seconds"),
        "status": "fail" if counts["fail"] else ("warn" if counts["warn"] else "ok"),
        "counts": counts,
        "thresholds": {"source_grace_hours": SOURCE_GRACE_HOURS, "refresh_max_hours": REFRESH_MAX_HOURS,
                       "live_max_lag_hours": LIVE_MAX_LAG_HOURS, "silent_venue_days": SILENT_VENUE_DAYS,
                       "hk_report_max_lag_days": HK_REPORT_MAX_LAG_DAYS},
        "findings": findings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    icon = {"fail": "실패", "warn": "경고", "ok": "정상"}
    lines = [f"닷컴 대비 과열도 자동 감시 · {report['checked_at']} · 실패 {report['counts']['fail']} · "
             f"경고 {report['counts']['warn']} · 정상 {report['counts']['ok']}", "",
             "| 상태 | 점검 | 대상 | 내용 |", "|---|---|---|---|"]
    order = {"fail": 0, "warn": 1, "ok": 2}
    for row in sorted(report["findings"], key=lambda item: order[item["status"]]):
        lines.append(f"| {icon[row['status']]} | {row['check']} | {row['subject']} | {row['detail']} |")
    return "\n".join(lines) + "\n"
