"""P7 수집 신호 분류기 — 저장된 gh run 로그 발췌 픽스처로 분류 규칙을 고정한다.

네트워크 없음. 실제 저장소 ALFRED 사실 원장은 읽기만 하고, 분류 시각(now) 이전에
``retrieved_at`` 된 사실로 범위를 묶어 데이터가 늘어나도 오라클이 깨지지 않게 한다.
쓰기 없음(분류기는 원장이 없다).
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.mts_research import ingest_triage as triage
from ai_fc.mts_research.ingest_triage import (
    classify_alfred_refresh,
    classify_daily6m_sources,
    classify_market_failures,
    classify_v2_monitor,
    classify_v2_refresh,
    classify_v2_verify,
    is_intraday,
    load_fact_index,
    load_sealed_v2,
    run_cli,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mts_ingest_triage"
BOUNDARY_1110 = "2026-11-11T04:59:59+00:00"
BOUNDARY_1106 = "2026-11-07T04:59:59+00:00"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _args(**overrides) -> argparse.Namespace:
    body = {"as_of": None, "append": False, "report": None, "kind": None, "now": None}
    body.update(overrides)
    return argparse.Namespace(**body)


@pytest.fixture(scope="module")
def fact_index():
    """실제 ALFRED 사실 원장 투영 (읽기 전용, 약 30초 — 모듈당 1회)."""
    return load_fact_index(ROOT)


# --- 픽스처 위생 -------------------------------------------------------------------


def test_fixtures_are_registered_envelopes_without_secrets():
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 13
    for path in files:
        text = path.read_text(encoding="utf-8")
        body = json.loads(text)
        assert body["fixture_schema"] == triage.FIXTURE_SCHEMA
        assert body["kind"] in triage.KINDS
        assert body["provenance"]["source"] == "gh run view --log"
        for needle in ("***", "FRED_API_KEY", "ghp_", "github_pat_", "@users.noreply", "token"):
            assert needle not in text, (path.name, needle)


def test_owned_file_names_avoid_protected_globs():
    owned = [
        "src/ai_fc/mts_research/ingest_triage.py",
        "src/tests/test_mts_research_ingest_triage.py",
        *(f"src/tests/fixtures/mts_ingest_triage/{p.name}" for p in FIXTURES.glob("*.json")),
    ]
    protected = [".github/workflows/timeseries*.yml", "tools/*timeseries*", "tools/*scenario*",
                 "tools/*v6*", "src/tests/test_multivariate_timeseries*.py"]
    assert not [(name, glob) for name in owned for glob in protected if fnmatch.fnmatch(name, glob)]


def test_module_has_no_network_client_and_no_v14_string():
    source = (ROOT / "src/ai_fc/mts_research/ingest_triage.py").read_text(encoding="utf-8")
    for needle in ("urllib", "requests", "http.client", "httpx", "socket", "timeseries_v14"):
        assert needle not in source


# --- v2_verify: DFM 컷오프 날짜 경계 ---------------------------------------------------


def test_verify_1110_boundary_is_pending_at_prepare_cutoff(fact_index):
    body = _fixture("v2_verify_42926210670")
    result = classify_v2_verify(body["report"], _utc(body["now"]), ROOT, fact_index=fact_index)
    assert result["status"] == "pending_date_boundary"
    assert result["exit_code"] == 0
    assert result["evidence"]["missing"] == [BOUNDARY_1110]
    assert result["evidence"]["max_available_at"] == BOUNDARY_1110
    assert result["items"][0]["self_heals_at_utc"] == "2026-11-11T00:00:00+00:00"
    assert result["github_annotations"][0].startswith("::notice ")


def test_verify_design_oracle_now_2347_pending_and_0600_fail(fact_index):
    report = _fixture("v2_verify_42926210670")["report"]
    pending = classify_v2_verify(report, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=fact_index)
    assert (pending["status"], pending["exit_code"]) == ("pending_date_boundary", 0)
    late = classify_v2_verify(report, _utc("2026-11-11T06:00:00Z"), ROOT, fact_index=fact_index)
    assert (late["status"], late["exit_code"]) == ("fail", 1)
    assert late["evidence"]["missing"] == []


def test_verify_1106_independent_episode_is_pending(fact_index):
    body = _fixture("v2_verify_42271710113")
    result = classify_v2_verify(body["report"], _utc(body["now"]), ROOT, fact_index=fact_index)
    assert result["status"] == "pending_date_boundary"
    assert result["evidence"]["missing"] == [BOUNDARY_1106]


def test_verify_success_report_is_ok(fact_index):
    body = _fixture("v2_verify_42950811442")
    result = classify_v2_verify(body["report"], _utc(body["now"]), ROOT, fact_index=fact_index)
    assert (result["status"], result["exit_code"]) == ("ok", 0)


def test_verify_mixed_errors_fail(fact_index):
    report = copy.deepcopy(_fixture("v2_verify_42926210670")["report"])
    report["errors"].append("DFM cache contract hash drift")
    result = classify_v2_verify(report, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=fact_index)
    assert (result["status"], result["exit_code"]) == ("fail", 1)


def test_verify_count_must_match_recomputed_boundary(fact_index):
    report = copy.deepcopy(_fixture("v2_verify_42926210670")["report"])
    report["errors"] = ["DFM evaluation cache incomplete: 2 cutoff(s)"]
    report["dfm_missing_evaluation_cutoffs"] = 2
    result = classify_v2_verify(report, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=fact_index)
    assert result["status"] == "fail"
    inconsistent = copy.deepcopy(_fixture("v2_verify_42926210670")["report"])
    inconsistent["dfm_missing_evaluation_cutoffs"] = 3
    result = classify_v2_verify(inconsistent, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=fact_index)
    assert result["status"] == "fail"


def test_verify_near_miss_wording_fails(fact_index):
    report = copy.deepcopy(_fixture("v2_verify_42926210670")["report"])
    report["errors"] = ["DFM evaluation cache incomplete: 1 cutoff(s) "]
    result = classify_v2_verify(report, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=fact_index)
    assert result["status"] == "fail"


def test_verify_cutoff_must_be_next_utc_day(monkeypatch):
    """개수가 맞아도 컷오프가 now 다음 UTC 날짜가 아니면 날짜 경계로 설명되지 않는다."""
    report = _fixture("v2_verify_42926210670")["report"]
    far = "2026-11-12T04:59:59+00:00"  # ET 하루 끝이지만 now+2일
    monkeypatch.setattr(triage, "date_boundary_missing_cutoffs",
                        lambda index, now: {"known_facts": 1, "max_available_at": far, "missing": [far]})
    result = classify_v2_verify(report, _utc("2026-11-10T23:47:00Z"), ROOT, fact_index=[])
    assert (result["status"], result["exit_code"]) == ("fail", 1)


def test_known_facts_rejects_branched_correction():
    stamp = _utc("2026-11-01T00:00:00Z")
    base = dict(source_id="alfred", series_id="X", observation_time="2026-10-01", vintage_start="2026-10-02",
                available_at="2026-10-02T04:59:59+00:00", retrieved_at=stamp)
    first = triage.FactIndexRow(revision_seq=0, observation_id="a", supersedes_observation_id=None, **base)
    linked = triage.FactIndexRow(revision_seq=1, observation_id="b", supersedes_observation_id="a", **base)
    branched = triage.FactIndexRow(revision_seq=1, observation_id="c", supersedes_observation_id="z", **base)
    assert [row.observation_id for row in triage.known_facts_at([first, linked], stamp)] == ["b"]
    with pytest.raises(triage.IngestTriageError):
        triage.known_facts_at([first, branched], stamp)


def test_et_day_end_follows_dst():
    assert triage._is_et_day_end(_utc("2026-10-17T03:59:59Z"))  # EDT
    assert triage._is_et_day_end(_utc("2026-11-11T04:59:59Z"))  # EST
    assert not triage._is_et_day_end(_utc("2026-10-17T04:59:59Z"))
    assert not triage._is_et_day_end(_utc("2026-11-11T05:59:59Z"))


# --- v2_refresh: market.failures · ALFRED · 로그만 ------------------------------------


def test_current_market_failures_fed_ebp_is_unexpected():
    for name in ("v2_refresh_market_42950811442", "v2_refresh_market_42926210670"):
        result = classify_market_failures(_fixture(name)["report"])
        assert (result["status"], result["exit_code"]) == ("unexpected", 3)
        unexpected = [item for item in result["items"] if item["status"] == "unexpected"]
        assert [item["series"] for item in unexpected] == ["FED_EBP"]
        assert "does not match format '%m/%d/%Y'" in unexpected[0]["reason"]
        # 워크플로 명령 이스케이프: % → %25
        assert "%25m/%25d/%25Y" in result["github_annotations"][0]


def test_only_three_fredgraph_451_is_ok():
    report = copy.deepcopy(_fixture("v2_refresh_market_42950811442")["report"])
    report["market"]["failures"] = [f for f in report["market"]["failures"] if f["series"] != "FED_EBP"]
    result = classify_market_failures(report)
    assert (result["status"], result["exit_code"]) == ("ok", 0)
    assert len(result["items"]) == 3
    assert all(item["item_class"] == "notice" for item in result["items"])


def test_451_without_official_api_cover_is_unexpected():
    report = copy.deepcopy(_fixture("v2_refresh_market_42950811442")["report"])
    report["market"]["failures"] = [f for f in report["market"]["failures"] if f["series"] != "FED_EBP"]
    report["fred_official_api"]["series"].pop("DTWEXB")
    result = classify_market_failures(report)
    assert result["status"] == "unexpected"


def test_market_near_miss_and_live_critical_parsers_are_unexpected():
    base = copy.deepcopy(_fixture("v2_refresh_market_42950811442")["report"])
    base["market"]["failures"] = [
        {"series": "NASDAQCOM", "reason": "NASDAQCOM returned HTTP 451 "},
    ]
    assert classify_market_failures(base)["status"] == "unexpected"
    base["market"]["failures"] = [{"series": "VIX", "reason": "VIX returned HTTP 451"}]
    assert classify_market_failures(base)["status"] == "unexpected"
    base["market"]["failures"] = [{"series": "TREASURY", "reason": "TREASURY 2026 returned HTTP 500"}]
    assert classify_market_failures(base)["exit_code"] == 3


def test_alfred_http_500_is_fail():
    result = classify_v2_refresh(_fixture("v2_refresh_alfred_42950811442")["report"])
    assert (result["status"], result["exit_code"]) == ("fail", 1)
    assert len(result["items"]) == 8
    assert classify_alfred_refresh({"failures": []})["status"] == "ok"
    odd = classify_alfred_refresh({"failures": [{"series_id": "GDPC1", "reason": "timeout"}]})
    assert odd["status"] == "unexpected"


def test_rebase_conflict_log_is_fail():
    body = _fixture("v2_refresh_rebase_42312277749")
    result = classify_v2_refresh(body["report"], body["log_lines"])
    assert (result["status"], result["exit_code"]) == ("fail", 1)
    assert "리베이스 충돌" in result["reasons"][0]


# --- daily6m_sources -----------------------------------------------------------------


def test_current_403_is_transport_pending_about_10h():
    body = _fixture("daily6m_sources_42950808534")
    result = classify_daily6m_sources(body["report"], body["history"])
    assert (result["status"], result["exit_code"]) == ("transport_pending", 0)
    streak = result["evidence"]["streaks"]["nasdaq_history"]
    assert streak["streak_start"] == "2026-11-10T17:04:35.248537+00:00"
    assert streak["last_clean"] == "2026-11-10T11:29:21+00:00"
    assert streak["length_known"] is True and streak["judged_on"] == "hours_upper"
    assert 10.0 < streak["hours_lower"] < 10.2  # 관측된 첫 403 부터
    assert 15.6 < streak["hours_upper"] < 15.8  # 마지막 clean 부터 — 판정 기준(< 24h)
    assert streak["n_forbidden"] == 5 and streak["n_other_failures"] == 0
    assert {item["source"] for item in result["items"]} == {"nasdaq_history", "nasdaq_info"}


def _forbidden_entry(report: dict, hours: float) -> dict:
    completed = _utc(report["completed_at"]) - timedelta(hours=hours)
    return {"completed_at": completed.isoformat(), "status": "partial",
            "transport_failures": copy.deepcopy(report["transport_failures"]),
            "source_failures": copy.deepcopy(report["source_failures"]), "source_pending": []}


def _clean_entry(report: dict, hours: float) -> dict:
    completed = _utc(report["completed_at"]) - timedelta(hours=hours)
    return {"completed_at": completed.isoformat(), "status": "applied",
            "transport_failures": [], "source_failures": [], "source_pending": []}


def test_403_escalates_on_upper_bound_at_24h():
    report = _fixture("daily6m_sources_42950808534")["report"]
    escalated = classify_daily6m_sources(report, [_clean_entry(report, 25), _forbidden_entry(report, 2)])
    assert (escalated["status"], escalated["exit_code"]) == ("escalate", 1)
    streak = escalated["evidence"]["streaks"]["nasdaq_info"]
    assert streak["hours_upper"] == 25.0 and streak["hours_lower"] == 2.0  # 하한이 짧아도 상한으로 판정
    assert classify_daily6m_sources(report, [_clean_entry(report, 24)])["status"] == "escalate"
    pending = classify_daily6m_sources(report, [_clean_entry(report, 23)])
    assert (pending["status"], pending["exit_code"]) == ("transport_pending", 0)


def test_403_without_clean_observation_is_not_pending():
    """history 가 비었거나 403 만 있으면 연속 길이를 확인할 수 없다 — pending 으로 낮추지 않는다."""
    report = _fixture("daily6m_sources_42950808534")["report"]
    empty = classify_daily6m_sources(report, [])
    assert (empty["status"], empty["exit_code"]) == ("escalate", 1)
    assert empty["evidence"]["streaks"]["nasdaq_history"]["length_known"] is False
    assert empty["evidence"]["streaks"]["nasdaq_history"]["hours_upper"] is None
    assert "연속 길이 미확인" in empty["reasons"][0]
    only_403 = classify_daily6m_sources(report, [_forbidden_entry(report, 1), _forbidden_entry(report, 3)])
    assert (only_403["status"], only_403["exit_code"]) == ("escalate", 1)


def test_cli_raw_daily6m_report_without_history_escalates(tmp_path):
    raw = tmp_path / "report.json"
    raw.write_text(json.dumps(_fixture("daily6m_sources_42950808534")["report"]), encoding="utf-8")
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(raw)))
    assert (code, payload["status"]) == (1, "escalate")


def test_clean_observation_breaks_streak():
    report = _fixture("daily6m_sources_42950808534")["report"]
    history = [_forbidden_entry(report, 30), _clean_entry(report, 2)]
    result = classify_daily6m_sources(report, history)
    assert result["status"] == "transport_pending"
    streak = result["evidence"]["streaks"]["nasdaq_history"]
    assert (streak["hours_lower"], streak["hours_upper"]) == (0.0, 2.0)


def test_non_403_failure_on_same_kind_does_not_break_streak():
    report = _fixture("daily6m_sources_42950808534")["report"]
    timeout = _clean_entry(report, 5)
    timeout["status"] = "partial"
    timeout["transport_failures"] = [{"kind": "nasdaq_history", "reason": "timeout"}]
    result = classify_daily6m_sources(report, [_clean_entry(report, 30), timeout])
    streak = result["evidence"]["streaks"]["nasdaq_history"]
    assert streak["n_other_failures"] == 1 and streak["hours_upper"] == 30.0
    assert result["status"] == "escalate"
    # 다른 kind 의 실패는 이 kind 에게 clean 이다(treasury 실패 실행에서 Nasdaq 은 수집됐다).
    other_kind = _clean_entry(report, 5)
    other_kind["status"] = "partial"
    other_kind["source_failures"] = [{"kind": "treasury", "reason": "source has duplicate or uncompleted session"}]
    result = classify_daily6m_sources(report, [_clean_entry(report, 30), other_kind])
    assert result["status"] == "transport_pending"
    assert result["evidence"]["streaks"]["nasdaq_history"]["hours_upper"] == 5.0
    # 같은 kind 의 source_pending 도 clean 이 아니다.
    pending = _clean_entry(report, 5)
    pending["source_pending"] = [{"kind": "nasdaq_info", "reason": "x"}]
    result = classify_daily6m_sources(report, [_clean_entry(report, 30), pending])
    assert result["evidence"]["streaks"]["nasdaq_info"]["n_other_failures"] == 1


def test_malformed_history_entry_is_rejected():
    report = _fixture("daily6m_sources_42950808534")["report"]
    bare = {"completed_at": _clean_entry(report, 2)["completed_at"], "transport_failures": []}
    with pytest.raises(triage.IngestTriageError):
        classify_daily6m_sources(report, [bare])


def test_403_with_cboe_source_pending_is_transport_pending():
    body = _fixture("daily6m_sources_42926207427")
    result = classify_daily6m_sources(body["report"], body["history"])
    assert result["status"] == "transport_pending"
    assert result["evidence"]["source_pending"][0]["kind"] == "cboe"
    streak = result["evidence"]["streaks"]["nasdaq_history"]
    assert streak["last_clean"] == "2026-11-10T11:29:21+00:00" and 12.3 < streak["hours_upper"] < 12.4


def test_intraday_fixtures_are_intraday_pending():
    for name in ("daily6m_sources_42667699768", "daily6m_sources_42690764777"):
        body = _fixture(name)
        result = classify_daily6m_sources(body["report"], body["history"])
        assert (result["status"], result["exit_code"]) == ("intraday_pending", 0), name
        assert result["items"][0]["intraday"]["session"] == "2026-11-09"


def test_design_oracle_raw_timestamp_is_intraday():
    try:
        datetime.strptime("Nov 9, 2026 12:44 PM ET", "%b %d, %Y")
    except ValueError as exc:
        residue = str(exc)
    assert residue == "unconverted data remains:  12:44 PM ET"
    completed = _utc("2026-11-09T17:46:28Z")
    assert is_intraday(residue, completed) is not None
    assert is_intraday("Nov 9, 2026 12:44 PM ET", completed) is not None
    assert is_intraday("Nov 10, 2026 12:44 PM ET", completed) is None  # 날짜 불일치


def test_after_close_or_nonsession_timestamp_is_not_intraday():
    assert is_intraday("unconverted data remains:  4:05 PM ET", _utc("2026-11-09T21:10:00Z")) is None
    assert is_intraday("unconverted data remains:  12:44 PM ET", _utc("2026-11-09T22:30:00Z")) is None
    assert is_intraday("unconverted data remains:  12:44 PM ET", _utc("2026-11-08T17:46:00Z")) is None  # 일요일
    assert is_intraday("unconverted data remains:  12:44 PM ET", _utc("2026-11-09T17:30:00Z")) is None  # 수집 전 시각
    report = copy.deepcopy(_fixture("daily6m_sources_42667699768")["report"])
    report["source_failures"][0]["reason"] = "unconverted data remains:  4:05 PM ET"
    assert classify_daily6m_sources(report, [])["status"] == "fail"


def test_treasury_source_failure_is_fail():
    body = _fixture("daily6m_sources_42294447871")
    result = classify_daily6m_sources(body["report"], body["history"])
    assert (result["status"], result["exit_code"]) == ("fail", 1)


def test_unknown_transport_or_orphan_missing_response_fails():
    report = copy.deepcopy(_fixture("daily6m_sources_42950808534")["report"])
    report["transport_failures"].append({"kind": "cboe", "reason": "HTTPError: HTTP Error 403: Forbidden"})
    assert classify_daily6m_sources(report, [])["status"] == "fail"
    orphan = copy.deepcopy(_fixture("daily6m_sources_42950808534")["report"])
    orphan["transport_failures"] = [orphan["transport_failures"][0]]  # nasdaq_history 만 403
    assert classify_daily6m_sources(orphan, [])["status"] == "fail"  # nasdaq_info missing_response 고아


# --- v2_monitor -----------------------------------------------------------------------


def test_monitor_first_saturday_is_by_design_with_repo_sealed_record():
    sealed = load_sealed_v2(ROOT)
    assert sealed is not None and sealed["summary"]["gate_pass"] is False
    body = _fixture("v2_monitor_42332576447")
    result = classify_v2_monitor(sealed, body["log_line"])
    assert (result["status"], result["exit_code"]) == ("by_design_notice", 0)
    assert classify_v2_monitor(sealed, None)["status"] == "by_design_notice"


def test_monitor_other_failures_fail():
    sealed = {"model_id": "m", "run_id": "r", "summary": {"gate_pass": False, "status": "x"}}
    assert classify_v2_monitor(sealed, "Traceback: KeyError 'x'")["status"] == "fail"
    passed = {"model_id": "m", "run_id": "r", "summary": {"gate_pass": True, "status": "x"}}
    assert classify_v2_monitor(passed, triage.MONITOR_STOP_LINES[1])["status"] == "fail"
    assert classify_v2_monitor(None, None)["status"] == "fail"


# --- CLI --------------------------------------------------------------------------------


def test_cli_payload_fields_and_exit_codes():
    code, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(FIXTURES / "v2_refresh_market_42950811442.json")))
    assert code == 3 and payload["status"] == "unexpected"
    for key, value in (("display_only", True), ("scoring_excluded", True), ("notice", "참고 의견, 매매 신호 아님"),
                       ("network_fetch_enabled", False), ("workflow_wired", False), ("records_values", False),
                       ("single_episode", True), ("ledger", None)):
        assert payload[key] == value
    assert payload["n"] == 4 and payload["n_dates"] >= 1
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(FIXTURES / "daily6m_sources_42950808534.json")))
    assert code == 0 and payload["status"] == "transport_pending"
    assert payload["now_source"] == "report_completed_at"
    assert payload["n_dates"] == 2


def test_cli_raw_report_and_append_writes_nothing(tmp_path):
    raw = tmp_path / "report.json"
    raw.write_text(json.dumps(_fixture("daily6m_sources_42294447871")["report"]), encoding="utf-8")
    before = sorted(p.name for p in (ROOT / "data/mts_research/ledgers").iterdir())
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(raw), append=True))
    assert code == 1 and payload["envelope"] == "raw_report"
    assert payload["mode"] == "append_ignored" and payload["ledger_write"] == "not_applicable"
    assert sorted(p.name for p in (ROOT / "data/mts_research/ledgers").iterdir()) == before


def test_cli_rejects_kind_mismatch_and_missing_report():
    code, payload = run_cli(ROOT, _args(kind="v2_verify", report=str(FIXTURES / "v2_monitor_42332576447.json")))
    assert code == 2 and payload["status"] == "error"
    code, payload = run_cli(ROOT, _args(kind="v2_verify", report=None))
    assert code == 2


def test_cli_verify_uses_fixture_now(monkeypatch, fact_index):
    monkeypatch.setattr(triage, "load_fact_index", lambda root: fact_index)
    report = str(FIXTURES / "v2_verify_42926210670.json")
    code, payload = run_cli(ROOT, _args(kind="v2_verify", report=report))
    assert code == 0 and payload["status"] == "pending_date_boundary"
    assert payload["now"] == "2026-11-10T23:52:49+00:00" and payload["now_source"] == "fixture_now"
    code, payload = run_cli(ROOT, _args(kind="v2_verify", report=report, now="2026-11-11T06:00:00Z"))
    assert code == 1 and payload["status"] == "fail"
