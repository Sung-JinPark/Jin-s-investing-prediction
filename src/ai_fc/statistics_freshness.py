"""Per-indicator collection health, independent of observation-period labels.

This is display/operations metadata. It neither changes observations nor certifies
historical point-in-time availability. A successful fetch can return an unchanged
quarterly/annual release; that is distinct from failing to fetch the source.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

CHECK_MAX_HOURS = 72
STATUS_LABELS = {
    "current": "수집 정상",
    "source_waiting": "원천 응답 대기",
    "check_overdue": "수집 확인 지연",
    "observation_overdue": "자료 기간 점검 필요",
    "unverified": "확인 기록 없음",
}
# Operational backstops, measured from the END of the native period. These are
# deliberately wider than release lags: release schedules and revisions vary.
# Exact newest-publication checks are the collector's native full-source fetch.
PERIOD_MAX_AGE_DAYS = {"daily": 10, "weekly": 21, "monthly": 75, "quarterly": 180, "annual": 400}
SERIES_MAX_AGE_DAYS = {
    "M2SL": 45, "UNRATE": 45, "GS10": 35, "HQMCB10YR": 45,
    "GDP": 135, "Y034RC1Q027SBEA": 135, "Y001RC1Q027SBEA": 135,
    # This explicitly selected Financial Accounts DSR series is published later
    # than TDSP. They cannot be substituted merely to obtain a newer date.
    "BOGZ1FL010000346Q": 275,
}


def _timestamp(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment.astimezone(timezone.utc) if moment.tzinfo is not None else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _frequency(source: dict[str, Any]) -> str:
    # IPOALL has monthly observations but an explicitly annual revision cadence.
    if source.get("revision_cadence") == "author_revises_roughly_annually":
        return "annual"
    native = str(source.get("native_frequency") or "")
    return next((name for name in PERIOD_MAX_AGE_DAYS if native.startswith(name)), "unknown")


def _period_end(observed: date, frequency: str) -> date:
    if frequency == "annual":
        return date(observed.year, 12, 31)
    month = ((observed.month - 1) // 3 + 1) * 3 if frequency == "quarterly" else observed.month
    if frequency in {"quarterly", "monthly"}:
        return date(observed.year, month, calendar.monthrange(observed.year, month)[1])
    return observed


def load_source_checks(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    """Latest actual retrieval of the SAME validated source/hash/series.

    Raw receipt clocks, unlike observation revisions, advance for unchanged
    source bytes. Matching the current snapshot hash avoids blessing an unrelated
    download as a successful validation of its displayed observations.
    """
    path = root / "data/statistics/official_store/ledgers/raw_receipts.jsonl"
    if not path.is_file():
        return {}
    from .authoritative_statistics import (
        load_authoritative_source_policy, read_raw_artifact_receipts, verify_raw_artifact_receipt,
    )

    sources = {row["series_id"]: row for row in payload.get("sources") or []}
    checks: dict[str, str] = {}
    selected = {}
    for receipt in read_raw_artifact_receipts(path.parent.parent):
        if receipt.http_status != 200:
            continue
        for declared_series in receipt.series_ids:
            # The IPO workbook receipt declares fields, while the chart source
            # declares the dataset. Only its explicit net field feeds the index.
            series_id = {"RITTER_IPOALL_MONTHLY.net": "RITTER_IPOALL_MONTHLY"}.get(declared_series, declared_series)
            source = sources.get(series_id)
            if (source is None or receipt.source_id != source.get("policy_source_id")
                    or receipt.raw_sha256 != source.get("raw_sha256")):
                continue
            prior = _timestamp(checks.get(series_id))
            current = _timestamp(receipt.fetched_at)
            if current is not None and (prior is None or current > prior):
                checks[series_id] = receipt.fetched_at
                selected[series_id] = receipt
    policy_path = root / "data/contracts/authoritative_statistics_sources.yaml"
    if not policy_path.is_file():
        policy_path = Path(__file__).resolve().parents[2] / "data/contracts/authoritative_statistics_sources.yaml"
    policy = load_authoritative_source_policy(policy_path)
    verified = set()
    for receipt in selected.values():
        key = (receipt.source_id, receipt.raw_sha256, receipt.artifact_path)
        if key not in verified:
            verify_raw_artifact_receipt(path.parent.parent, policy, receipt)
            verified.add(key)
    return checks


def _source_health(source: dict[str, Any], *, now: datetime,
                   successful_check: Any = None, require_receipt: bool = False) -> dict[str, Any]:
    sid = str(source.get("series_id") or "")
    observed = _date(source.get("latest_observation"))
    checked = _timestamp(successful_check if require_receipt else successful_check or source.get("available_at"))
    frequency = _frequency(source)
    age_limit = SERIES_MAX_AGE_DAYS.get(sid, PERIOD_MAX_AGE_DAYS.get(frequency))
    age = (now.date() - _period_end(observed, frequency)).days if observed else None
    if source.get("refresh_status") == "verified_cache_waiting_source":
        status = "source_waiting"
    elif checked is None or observed is None or frequency == "unknown" or checked > now or observed > now.date():
        status = "unverified"
    elif (now - checked).total_seconds() > CHECK_MAX_HOURS * 3600:
        status = "check_overdue"
    elif age_limit is not None and age is not None and age > age_limit:
        status = "observation_overdue"
    else:
        status = "current"
    return {"series_id": sid, "frequency": frequency,
            "latest_observation": source.get("latest_observation"),
            "last_successful_check": checked.isoformat(timespec="seconds") if checked else None,
            "status": status, "period_age_days": age, "max_period_age_days": age_limit,
            "source_url": source.get("source_url")}


def build_indicator_freshness(
    payload: dict[str, Any], *, contract: dict[str, Any],
    checked_at: datetime | str | None = None,
    ipo_status: dict[str, Any] | None = None,
    source_checks: dict[str, str] | None = None,
    theme_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _timestamp(checked_at) if checked_at is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("freshness checked_at must be an aware ISO timestamp")
    sources = {row["series_id"]: row for row in payload.get("sources") or []}
    charts = {row["id"]: row for row in payload.get("charts") or []}
    if theme_status is None:
        theme_status = (charts.get("ipo_count_operating_12m") or {}).get("theme_listing_watch")
    priority = ["unverified", "source_waiting", "check_overdue", "observation_overdue", "current"]
    rows = []
    for spec in contract.get("indicators") or []:
        chart = charts.get(spec.get("chart")) or {}
        current = next((s for s in chart.get("series") or []
                        if s.get("label") == spec.get("current_series") and not s.get("provisional")), {})
        points = current.get("points") or []
        latest = points[-1].get("date") if points else None
        observed = _date(latest)
        source_ids = list(chart.get("metric_source_ids") or chart.get("source_ids") or [])
        health = []
        for sid in source_ids:
            source = sources.get(sid) or {"series_id": sid}
            check = (source_checks or {}).get(sid)
            if sid == "RITTER_IPOALL_MONTHLY" and ipo_status:
                ritter = ipo_status.get("ritter") or {}
                if (ritter.get("status") == "current"
                        and ritter.get("raw_sha256") == source.get("raw_sha256")
                        and (source_checks is None or sid in source_checks)):
                    check = ipo_status.get("checked_at")
            item = _source_health(source, now=now, successful_check=check,
                                  require_receipt=source_checks is not None)
            if sid == "RITTER_IPOALL_MONTHLY" and ipo_status:
                if (ipo_status.get("ritter") or {}).get("status") != "current":
                    item["status"] = "source_waiting"
            health.append(item)
        status = next((state for state in priority if any(h["status"] == state for h in health)), "unverified")
        if observed is None or observed > now.date():
            status = "unverified"
        successful = [h["last_successful_check"] for h in health if h["last_successful_check"]]
        last_check = min(successful, key=lambda value: _timestamp(value)) if len(successful) == len(health) and health else None
        frequencies = {h["frequency"] for h in health}
        if observed is None:
            label = "기간 확인 필요"
        elif "quarterly" in frequencies:
            label = f"{observed.year}년 {(observed.month - 1) // 3 + 1}분기"
        else:
            label = f"{observed.year}-{observed.month:02d}"
        source_through = min((str(h["latest_observation"]) for h in health if h["latest_observation"]), default=None)
        if status == "current" and source_through and str(latest)[:7] < source_through[:7]:
            status = "observation_overdue"
        if "weekly" in frequencies:
            label += " 월평균"
        row = {"id": spec.get("id"), "title": chart.get("title") or spec.get("id"),
               "period_label": label, "latest_observation": latest,
               "source_observation_through": source_through,
               "last_successful_check": last_check, "status": status,
               "status_label": STATUS_LABELS[status], "source_ids": source_ids, "sources": health}
        if spec.get("id") == "ipo_count_operating_12m":
            row["period_label"] += " 확정 · 최근 12개월 합"
            row["note"] = "확정 원본은 약 연 1회 개정됩니다. 잠정치는 과열도 지수에 포함되지 않습니다."
            provisional = next((s for s in chart.get("series") or [] if s.get("provisional")), {})
            provisional_points = provisional.get("points") or []
            if provisional_points:
                row["provisional_through"] = provisional_points[-1].get("date")
                row["provisional_value"] = provisional_points[-1].get("value")
        rows.append(row)
    # A failed provisional feed must be reported even though it cannot enter the index.
    auxiliary_issues = []
    if ipo_status is not None:
        moment = _timestamp(ipo_status.get("checked_at"))
        if moment is None or moment > now or (now - moment).total_seconds() > CHECK_MAX_HOURS * 3600:
            auxiliary_issues.append("ipo_monthly_check_overdue")
        for name in ("ritter", "nasdaq"):
            if (ipo_status.get(name) or {}).get("status") != "current":
                auxiliary_issues.append(f"ipo_{name}_source_waiting")
    elif any(spec.get("id") == "ipo_count_operating_12m" for spec in contract.get("indicators") or []):
        auxiliary_issues.append("ipo_monthly_check_missing")
    waiting = (payload.get("source_refresh") or {}).get("waiting_series") or []
    auxiliary_issues.extend(f"source_waiting:{sid}" for sid in waiting)
    # Theme additions are a separate dependency from the annual US IPO source.
    # Monitor collection/review without changing the frozen counting definition.
    if theme_status is not None:
        moment = _timestamp(theme_status.get("checked_at"))
        if moment is None or moment > now or (now - moment).total_seconds() > CHECK_MAX_HOURS * 3600:
            auxiliary_issues.append("ipo_theme_watch_check_overdue")
        auxiliary_issues.extend(f"ipo_theme_venue_waiting:{venue}"
                                for venue, state in (theme_status.get("venues") or {}).items()
                                if state.get("status") != "current")
        if int((theme_status.get("summary") or {}).get("pending_overdue") or 0):
            auxiliary_issues.append("ipo_theme_review_overdue")
        for row in rows:
            if row["id"] == "ipo_count_operating_12m":
                summary = theme_status.get("summary") or {}
                row["note"] += f" 해외 상장 감시 {summary.get('venues_ok', 0)}/{summary.get('venues_total', 0)}개 시장 확인."
                if row["status"] == "current" and any(issue.startswith("ipo_theme_") for issue in auxiliary_issues):
                    row["status"] = "source_waiting"
                    row["status_label"] = STATUS_LABELS["source_waiting"]
    issues = [row["id"] for row in rows if row["status"] != "current"]
    return {"schema_version": 1, "dataset_id": "statistics_indicator_freshness_v1",
            "checked_at": now.isoformat(timespec="seconds"), "snapshot_generated_at": payload.get("generated_at"),
            "status": "ok" if rows and not issues and not auxiliary_issues else "attention",
            "check_max_hours": CHECK_MAX_HOURS,
            "check_meaning": "successful source retrieval and native-period lag checks; unchanged releases remain unchanged",
            "probability_space": "reference_only", "model_use": False, "official_forecast_input": False,
            "indicators": rows, "issues": issues, "auxiliary_issues": auxiliary_issues}


def audit_statistics_freshness(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    from .dotcom_overheat import load_contract
    from .statistics_lab import load_statistics_lab

    payload = load_statistics_lab(root)
    path = root / "data/statistics/ipo/monthly_counts_status.json"
    ipo_status = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    theme_path = root / "data/statistics/ipo/theme_listing_watch.json"
    theme_status = json.loads(theme_path.read_text(encoding="utf-8")) if theme_path.is_file() else None
    contract = load_contract(root)
    if not isinstance(contract, dict) or not isinstance(contract.get("indicators"), list):
        raise ValueError("invalid statistics indicator contract")
    if ipo_status is not None and not isinstance(ipo_status, dict):
        raise ValueError("invalid IPO monthly source status")
    if theme_status is not None and not isinstance(theme_status, dict):
        raise ValueError("invalid IPO theme watch status")
    report = build_indicator_freshness(payload, contract=contract, checked_at=now,
                                       ipo_status=ipo_status, source_checks=load_source_checks(root, payload),
                                       theme_status=theme_status)
    if theme_status is None and any(row["id"] == "ipo_count_operating_12m" for row in report["indicators"]):
        report["auxiliary_issues"].append("ipo_theme_watch_missing")
        report["status"] = "attention"
    return report


def freshness_markdown(report: dict[str, Any]) -> str:
    lines = [f"14개 지표 원천 갱신 점검 · {report['checked_at']}", "",
             "| 지표 | 자료 기간 | 마지막 원천 확인 (UTC) | 상태 |", "|---|---|---|---|"]
    for row in report["indicators"]:
        lines.append(f"| {row['title']} | {row['period_label']} | {row['last_successful_check'] or '-'} | {row['status_label']} |")
    if report["auxiliary_issues"]:
        lines.extend(["", "추가 점검: " + ", ".join(report["auxiliary_issues"])])
    if report.get("error_type"):
        lines.extend(["", f"감사 자료 오류: {report['error_type']} ({report['error_category']})"])
    return "\n".join(lines)
