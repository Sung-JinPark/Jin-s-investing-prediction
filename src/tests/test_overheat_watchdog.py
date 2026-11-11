"""닷컴 대비 과열도 자동 감시 — 점검별 실패 조건과 워크플로 배선 (네트워크 없음)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ai_fc.overheat_watchdog import (
    check_indicator_coverage, check_ipo_sources, check_live_site, check_refresh_alive, check_source_currency,
    check_theme_watch, render_markdown, run_watchdog,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc)
CONTRACT = {"indicators": [{"id": "unemployment_rate", "chart": "unemployment_rate"},
                           {"id": "margin_credit", "chart": "margin_credit_proxy"}]}


def _snapshot(**overrides) -> dict:
    snap = {
        "generated_at": "2026-11-09T16:22:42+00:00",
        "source_refresh": {"waiting_series": []},
        "charts": [{"id": "unemployment_rate", "source_ids": ["UNRATE"]},
                   {"id": "margin_credit_proxy", "source_ids": ["FL663067003"]}],
        "sources": [{"series_id": "UNRATE", "latest_observation": "2026-10-01"},
                    {"series_id": "FL663067003", "latest_observation": "2026-04-01"}],
    }
    snap.update(overrides)
    return snap


def _statuses(findings: list[dict]) -> list[tuple[str, str]]:
    return [(row["subject"].split(" ")[0], row["status"]) for row in findings]


def test_missed_source_release_fails_only_after_the_grace_period() -> None:
    asked = []

    def fred(sid: str) -> dict:
        asked.append(sid)
        if sid == "UNRATE":
            return {"observation_end": "2026-11-01", "last_updated": "2026-11-06 07:43:00-06"}  # 3일 넘게 지남
        return {"observation_end": "2026-07-01", "last_updated": "2026-11-09 11:56:00-06"}    # 막 발표 — 유예
    findings = check_source_currency(_snapshot(), CONTRACT, now=NOW, fred=fred)
    assert _statuses(findings) == [("FL663067003", "ok"), ("UNRATE", "fail")]
    assert "BOGZ1FL663067003Q" in asked, "Z.1 직접 수집 계열은 FRED 미러로 대조한다"
    assert "반영 유예" in findings[0]["detail"] and "2026-11-01" in findings[1]["detail"]


def test_stopped_refresh_and_waiting_sources_are_reported() -> None:
    stale = _snapshot(generated_at="2026-11-07T16:00:00+00:00",
                      source_refresh={"waiting_series": ["C30_POWER"]})
    findings = check_refresh_alive(stale, now=NOW, last_success="2026-11-07T16:01:00Z")
    assert [row["status"] for row in findings] == ["fail", "fail", "warn"]
    fresh = check_refresh_alive(_snapshot(), now=NOW, last_success="2026-11-09T16:24:09Z")
    assert all(row["status"] == "ok" for row in fresh)


def test_live_site_must_carry_all_indicators_and_not_lag() -> None:
    ok = {"dotcom_overheat": {"status": "ok", "overheat_pct": 54, "included": 2, "skipped": [],
                              "generated_at": "2026-11-09T16:22:42+00:00"}}
    assert all(row["status"] == "ok" for row in check_live_site(_snapshot(), ok, contract=CONTRACT))
    missing = {"dotcom_overheat": {**ok["dotcom_overheat"], "included": 1, "skipped": [{"id": "margin_credit"}]}}
    assert check_live_site(_snapshot(), missing, contract=CONTRACT)[0]["status"] == "fail"
    lagging = {"dotcom_overheat": {**ok["dotcom_overheat"], "generated_at": "2026-11-08T00:00:00+00:00"}}
    assert [row["status"] for row in check_live_site(_snapshot(), lagging, contract=CONTRACT)] == ["ok", "fail"]
    assert check_live_site(_snapshot(), None, contract=CONTRACT)[0]["status"] == "fail"


def test_coverage_ipo_and_theme_watch_failures() -> None:
    assert check_indicator_coverage(_snapshot(charts=[{"id": "unemployment_rate"}]), CONTRACT)[0]["status"] == "fail"
    ipo = {"checked_at": "2026-11-09T16:00:00+00:00", "ritter": {"status": "current"},
           "nasdaq": {"status": "stale", "months": {"2026-09": {}, "2026-10": {}}}}
    statuses = [row["status"] for row in check_ipo_sources(ipo, now=NOW)]
    assert statuses.count("fail") == 1, "nasdaq stale"
    late = check_ipo_sources({**ipo, "nasdaq": {"status": "current", "months": {"2026-09": {}}}},
                             now=datetime(2026, 11, 10, tzinfo=timezone.utc).replace(day=10))
    assert any("지난달" in row["detail"] for row in late if row["status"] == "fail")
    watch = {"checked_at": "2026-11-09T16:00:00+00:00", "watch_start": "2026-10-01",
             "venues": {"kr": {"status": "stale", "last_ok_at": "2026-11-01T00:00:00+00:00", "error": "OSError"},
                        "jp": {"status": "current", "last_ok_at": "2026-11-09T16:00:00+00:00"}},
             "summary": {"pending_review": 1, "pending_overdue": 1, "venues_ok": 1, "venues_total": 2},
             "listings": [{"venue": "kr", "listing_date": "2026-11-03"}, {"venue": "hk_main", "listing_date": "2026-09-30"},
                          {"venue": "cn_a", "listing_date": "2026-11-05"}, {"venue": "jp", "listing_date": "2026-11-06"},
                          {"venue": "tw_twse", "listing_date": "2026-11-01"}, {"venue": "tw_tpex", "listing_date": "2026-11-02"}]}
    found = {(row["subject"], row["status"]) for row in check_theme_watch(watch, now=NOW)}
    assert ("kr", "fail") in found, "3일 넘게 수집 실패"
    assert ("판정 대기", "fail") in found
    assert ("hk_main", "warn") in found, "홍콩 보고서 35일 넘게 멈춤"


def test_run_watchdog_on_the_repository_snapshot_without_network(tmp_path: Path) -> None:
    report = run_watchdog(ROOT, now=NOW, fred_key=None, last_success=None, live=None)
    assert report["dataset_id"] == "overheat_watchdog_v1" and report["status"] in {"fail", "warn", "ok"}
    checks = {row["check"] for row in report["findings"]}
    assert {"coverage", "source_currency", "refresh_alive", "live_site", "ipo_sources", "theme_watch"} <= checks
    text = render_markdown(report)
    assert text.startswith("닷컴 대비 과열도 자동 감시") and "| 상태 | 점검 |" in text
    json.dumps(report, ensure_ascii=False)


def test_workflow_runs_on_its_own_schedule_and_is_itself_watched() -> None:
    wf = yaml.safe_load((ROOT / ".github/workflows/overheat-watchdog.yml").read_text(encoding="utf-8"))
    events = wf.get("on", wf.get(True))
    assert len(events["schedule"]) >= 2 and "workflow_dispatch" in events
    commands = "\n".join(step.get("run", "") for step in wf["jobs"]["watchdog"]["steps"])
    assert "python -m ai_fc overheat-watchdog" in commands and "statistics-refresh.yml" in commands
    assert "gh issue close" in commands and "--label overheat-watchdog" in commands
    assert wf["jobs"]["watchdog"]["env"]["FRED_API_KEY"] == "${{ secrets.FRED_API_KEY }}"
    alert = yaml.safe_load((ROOT / ".github/workflows/ops-failure-alert.yml").read_text(encoding="utf-8"))
    assert "overheat-watchdog" in (alert.get("on", alert.get(True)))["workflow_run"]["workflows"]
