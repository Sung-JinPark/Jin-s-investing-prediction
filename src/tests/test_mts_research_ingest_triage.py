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
    body = {"as_of": None, "append": False, "report": None, "kind": None, "now": None, "history": None}
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
    """U2a: CLI 는 해시 고정 정책으로 FED_EBP 를 known_stall 로 판정한다(순수 함수는 종전대로 unexpected).

    workflow_wired 는 kind 별 — U2a 는 daily6m_sources 만 배선했다(v2_* 는 U2b 에서 True 로 갱신)."""
    code, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(FIXTURES / "v2_refresh_market_42950811442.json")))
    assert code == 0 and payload["status"] == "known_stall"
    assert payload["now_source"] == "report_market_retrieved_at"
    for key, value in (("display_only", True), ("scoring_excluded", True), ("notice", "참고 의견, 매매 신호 아님"),
                       ("network_fetch_enabled", False), ("workflow_wired", False), ("records_values", False),
                       ("single_episode", True), ("ledger", None)):
        assert payload[key] == value
    assert payload["n"] == 4 and payload["n_dates"] >= 1
    assert payload["evidence"]["policy_hash"] == triage.PINNED_POLICY_HASH
    assert payload["evidence"]["now_source"] == "report_market_retrieved_at"
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(FIXTURES / "daily6m_sources_42950808534.json")))
    assert code == 0 and payload["status"] == "transport_pending"
    assert payload["now_source"] == "report_completed_at"
    assert payload["n_dates"] == 2
    assert payload["workflow_wired"] is True and payload["evidence"]["history_provider"] == "fixture"


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


# --- U2a: 해시 고정 정책 · FED_EBP known_stall · 영수증 history · Nasdaq 창 ---------------------

FED_EBP_ONSET = "2026-10-07T07:46:53+00:00"
EBP_V3_AVAILABLE = "2026-11-05T16:36:13+00:00"


def _policy() -> dict:
    return triage.load_policy(ROOT)


def _fed_ebp_entry(name: str = "v2_refresh_market_42950811442") -> dict:
    report = _fixture(name)["report"]
    return next(entry for entry in report["market"]["failures"] if entry["series"] == "FED_EBP")


@pytest.mark.parametrize("name, age", [("v2_refresh_market_42950811442", 835.461),
                                       ("v2_refresh_market_42926210670", 832.094)])
def test_fed_ebp_known_stall_after_24h_with_fresh_sidecar(name, age):
    code, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(FIXTURES / f"{name}.json")))
    assert (code, payload["status"]) == (0, "known_stall")
    assert payload["now_source"] == "report_market_retrieved_at"
    assert payload["now"] == _fixture(name)["report"]["market"]["retrieved_at"]
    item = next(item for item in payload["items"] if item.get("series") == "FED_EBP")
    assert item["status"] == "known_stall" and item["reason_code"] == "known_stall_compensated"
    assert item["onset"] == FED_EBP_ONSET and item["age_hours"] == pytest.approx(age, abs=0.01)
    assert item["now_source"] == "report_market_retrieved_at"
    assert item["compensator"]["fresh"] is True and item["compensator"]["ledger_integrity"] == "ok"
    assert payload["github_annotations"][0].startswith("::warning title=ingest-triage v2_refresh::")


def test_v2_refresh_now_ignores_wall_clock(monkeypatch):
    """B1: v2_refresh 판정 시각은 보고의 market.retrieved_at — 벽시계를 2027 로 밀어도 결과가 같다."""
    baseline = {}
    for name in ("v2_refresh_market_42950811442", "v2_refresh_market_42926210670"):
        _, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(FIXTURES / f"{name}.json")))
        item = next(item for item in payload["items"] if item.get("series") == "FED_EBP")
        baseline[name] = (payload["status"], item["age_hours"], item["onset"])

    class _Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(triage, "datetime", _Future)
    for name, expected in baseline.items():
        _, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(FIXTURES / f"{name}.json")))
        item = next(item for item in payload["items"] if item.get("series") == "FED_EBP")
        assert (payload["status"], item["age_hours"], item["onset"]) == expected


def test_v2_refresh_without_market_retrieved_at_is_exit_2(tmp_path):
    report = copy.deepcopy(_fixture("v2_refresh_market_42950811442")["report"])
    report["market"].pop("retrieved_at")
    raw = tmp_path / "report.json"
    raw.write_text(json.dumps(report), encoding="utf-8")
    code, payload = run_cli(ROOT, _args(kind="v2_refresh", report=str(raw)))
    assert (code, payload["status"]) == (2, "error")
    assert "market.retrieved_at" in payload["error"]
    # 시간대 없는 시각도 거부한다(벽시계로 떨어지지 않음).
    report["market"]["retrieved_at"] = "2026-11-11T03:14:34"
    raw.write_text(json.dumps(report), encoding="utf-8")
    assert run_cli(ROOT, _args(kind="v2_refresh", report=str(raw)))[0] == 2


def test_fed_ebp_first_24h_escalates():
    rule = _policy()["known_stalls"]["fed_ebp_sealed_parser_iso_dates"]
    onset = _utc(FED_EBP_ONSET)
    fresh = {"fresh": True}
    assert triage.decide_fed_ebp(onset, onset + timedelta(hours=23), fresh, rule) == ("escalate", "first_window")
    assert triage.decide_fed_ebp(onset, onset + timedelta(hours=25), fresh, rule) == (
        "known_stall", "known_stall_compensated")
    assert triage.decide_fed_ebp(onset, onset + timedelta(hours=25), {"fresh": False}, rule) == (
        "escalate", "sidecar_lagging")


def _sidecar_copy(tmp_path: Path, *, keep_vintages: set[int] | None = None, tamper: bool = False) -> Path:
    """FED_EBP 영수증·원본 gzip·사이드카 원장 사본(tmp_path) — 실저장소에는 쓰지 않는다."""
    from ai_fc.mts_research.fed_ebp_sidecar import LEDGER_RELATIVE, RECEIPTS_RELATIVE, UPSTREAM_SOURCE_ID
    from ai_fc.timeseries_v8.contracts import canonical_hash

    root = tmp_path / "repo"
    receipts = [line for line in (ROOT / RECEIPTS_RELATIVE).read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("source_id") == UPSTREAM_SOURCE_ID]
    target = root / RECEIPTS_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text("\n".join(receipts) + "\n", encoding="utf-8")
    for raw_path in {json.loads(line)["raw_path"] for line in receipts}:
        (root / raw_path).parent.mkdir(parents=True, exist_ok=True)
        (root / raw_path).write_bytes((ROOT / raw_path).read_bytes())
    rows = [json.loads(line) for line in (ROOT / LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if keep_vintages is not None:
        rows = [row for row in rows if row["vintage_seq"] in keep_vintages]
    if tamper:
        rows[5]["ebp"] = float(rows[5]["ebp"]) + 0.5
    previous = None
    lines = []
    for row in rows:  # 체인을 다시 이어 read_chain 은 통과시키고 _plan_append 의 접두부 대조만 깨지게 한다
        body = {key: value for key, value in row.items() if key not in ("previous_hash", "content_hash")}
        body["previous_hash"] = previous
        body["content_hash"] = canonical_hash(body)
        previous = body["content_hash"]
        lines.append(json.dumps(body, ensure_ascii=False))
    ledger = root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_fed_ebp_lagging_sidecar_escalates(tmp_path):
    """사이드카 원장에서 빈티지 3 을 잘라내면 밀린 행 = 빈티지 3(available 11-05T16:36Z).

    now 는 실제 영수증 시각이어야 한다(서명 '이 실행의 영수증'): +105.3h(> 96h) → sidecar_lagging,
    +81.5h(≤ 96h) → known_stall."""
    root = _sidecar_copy(tmp_path, keep_vintages={1, 2})
    policy = _policy()
    entry = _fed_ebp_entry()
    stale = triage.fed_ebp_known_stall(root, entry, _utc("2026-11-10T01:54:05+00:00"), policy)
    assert (stale["status"], stale["reason_code"]) == ("escalate", "sidecar_lagging")
    assert stale["compensator"]["fresh"] is False and stale["compensator"]["pending_rows"] > 0
    assert stale["compensator"]["oldest_pending_available_at"] == EBP_V3_AVAILABLE
    fresh = triage.fed_ebp_known_stall(root, entry, _utc("2026-11-09T02:09:02+00:00"), policy)
    assert (fresh["status"], fresh["reason_code"]) == ("known_stall", "known_stall_compensated")
    assert fresh["compensator"]["fresh"] is True


def test_fed_ebp_ledger_integrity_violation_is_unexpected(tmp_path):
    """N12: 원장이 재생 접두부가 아니면(값 변조) 지연(escalate)이 아니라 무결성 위반(unexpected)."""
    root = _sidecar_copy(tmp_path, tamper=True)
    item = triage.fed_ebp_known_stall(root, _fed_ebp_entry(), _utc("2026-11-11T03:14:34+00:00"), _policy())
    assert (item["status"], item["reason_code"]) == ("unexpected", "sidecar_ledger_integrity")


def test_fed_ebp_signature_mismatch_is_unexpected():
    policy = _policy()
    now = _utc("2026-11-11T03:14:34+00:00")
    template = "time data '{day}' does not match format '{fmt}'"
    variant = {"series": "FED_EBP", "reason": template.format(day="1973-01-01", fmt="%Y/%m/%d")}
    assert triage.fed_ebp_known_stall(ROOT, variant, now, policy) is None  # 정규식 밖 → 기존 unexpected
    other = {"series": "FED_EBP", "reason": template.format(day="01.01.1973", fmt="%m/%d/%Y")}
    assert triage.fed_ebp_known_stall(ROOT, other, now, policy) is None
    # 정규식은 맞지만 날짜가 최신 빈티지 오류문과 다르면 서명 불일치.
    shifted = {"series": "FED_EBP", "reason": template.format(day="1974-01-01", fmt="%m/%d/%Y")}
    item = triage.fed_ebp_known_stall(ROOT, shifted, now, policy)
    assert (item["status"], item["reason_code"]) == ("unexpected", "signature_mismatch")
    # 이 실행이 받은 영수증이 아니면(now 가 영수증 시각과 다름) 서명 불일치.
    late = triage.fed_ebp_known_stall(ROOT, _fed_ebp_entry(), now + timedelta(minutes=1), policy)
    assert late["reason_code"] == "signature_mismatch" and late["signature"]["received_this_run"] is False
    # 정책 경로로 분류해도 FED_EBP 외 형식 밖 항목은 그대로 unexpected.
    report = copy.deepcopy(_fixture("v2_refresh_market_42950811442")["report"])
    report["market"]["failures"].append({"series": "VIX", "reason": "VIX returned HTTP 500"})
    result = classify_market_failures(report, root=ROOT, policy=policy)
    assert (result["status"], result["exit_code"]) == ("unexpected", 3)


def test_policy_hash_is_pinned():
    from ai_fc.timeseries_v8.contracts import canonical_hash

    policy = _policy()
    assert canonical_hash(policy) == triage.PINNED_POLICY_HASH
    assert policy["registration_kind"] == "post_hoc_operational"
    assert len(policy["memo_deviations"]) == 1
    stall = policy["known_stalls"]["fed_ebp_sealed_parser_iso_dates"]
    assert stall["compensator_max_lag_hours"] == 96 and stall["escalate_window_hours"] == 24
    nasdaq = policy["known_stalls"]["nasdaq_forbidden_alfred_supplemented"]
    assert nasdaq["escalate_window_hours"] == [24, 26] and nasdaq["known_stall_until_hours"] == 336
    assert nasdaq["max_native_lag_sessions"] == 2
    approval = policy["approval"]
    assert approval["approval_text"] == "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
    assert approval["approval_form"] == "delegated_bundle_instruction" and approval["literal_template_match"] is False
    assert approval["template_text"] != approval["approval_text"]
    assert _utc(approval["instructed_at_upper_bound"]) == _utc("2026-11-11T09:03:44Z")
    assert policy["effect"]["gate_effect"] == "none" and policy["effect"]["notice"] == "참고 의견, 매매 신호 아님"


def test_policy_tamper_is_exit_2(tmp_path):
    root = tmp_path / "repo"
    target = root / triage.POLICY_RELATIVE
    target.parent.mkdir(parents=True)
    raw = (ROOT / triage.POLICY_RELATIVE).read_bytes()
    target.write_bytes(raw.replace(b'"compensator_max_lag_hours": 96', b'"compensator_max_lag_hours": 97'))
    assert target.read_bytes() != raw
    code, payload = run_cli(root, _args(kind="v2_refresh", report=str(FIXTURES / "v2_refresh_market_42950811442.json")))
    assert (code, payload["status"]) == (2, "error") and "해시 불일치" in payload["error"]
    target.unlink()
    code, payload = run_cli(root, _args(kind="daily6m_sources", report=str(FIXTURES / "daily6m_sources_42950808534.json")))
    assert code == 2 and "정책 파일이 없다" in payload["error"]


def _raw_report(tmp_path: Path, name: str) -> Path:
    raw = tmp_path / f"{name}.json"
    raw.write_text(json.dumps(_fixture(name)["report"]), encoding="utf-8")
    return raw


@pytest.mark.parametrize("name, hours", [("daily6m_sources_42926207427", 2.568),
                                         ("daily6m_sources_42950808534", 5.916)])
def test_receipt_history_session_anchor_oracle(tmp_path, name, hours):
    report = _fixture(name)["report"]
    history = triage.receipt_history(ROOT, _utc(report["completed_at"]))
    anchor = [entry for entry in history if entry["basis"] == "session_anchor"]
    assert len(anchor) == 1 and anchor[0]["s_last"] == "2026-11-09" and anchor[0]["next_session"] == "2026-11-10"
    assert anchor[0]["completed_at"] == "2026-11-10T21:15:00+00:00" and anchor[0]["caught_up"] is False
    assert all(_utc(entry["completed_at"]) < _utc(report["completed_at"]) for entry in history)
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(_raw_report(tmp_path, name)),
                                        history="receipts_ledger"))
    assert (code, payload["status"]) == (0, "transport_pending")
    for streak in payload["evidence"]["streaks"].values():
        assert streak["hours_upper"] == hours and streak["last_clean"] == "2026-11-10T21:15:00+00:00"


def test_receipt_history_weekend_is_caught_up(tmp_path):
    """금요일(2026-11-06) 종가를 수집했고 completed_at 이 일요일이면 잃은 세션이 없다 → caught_up → pending."""
    root = tmp_path / "repo"
    store = root / "data/timeseries_daily6m"
    store.mkdir(parents=True)
    (store / "source_receipts.jsonl").write_text(json.dumps({
        "kind": "nasdaq_info", "http_status": 200, "retrieved_at": "2026-11-06T21:20:00+00:00",
        "source_id": "nasdaq_comp_official"}) + "\n", encoding="utf-8")
    (store / "source_observations.jsonl").write_text(json.dumps({
        "source_id": "nasdaq_comp_official", "observation_time": "2026-11-06",
        "available_at": "2026-11-06T21:20:00+00:00"}) + "\n", encoding="utf-8")
    completed = _utc("2026-11-08T15:00:00Z")
    history = triage.receipt_history(root, completed)
    anchor = [entry for entry in history if entry["basis"] == "session_anchor"][0]
    assert anchor["caught_up"] is True and anchor["next_session"] == "2026-11-09"
    assert _utc(anchor["completed_at"]) == completed - timedelta(seconds=1)
    report = copy.deepcopy(_fixture("daily6m_sources_42950808534")["report"])
    report["completed_at"] = completed.isoformat()
    result = classify_daily6m_sources(report, history)
    assert result["status"] == "transport_pending"
    assert result["evidence"]["streaks"]["nasdaq_history"]["hours_upper"] < 0.01


def test_nasdaq_windows():
    policy = _policy()
    fresh = {"fresh": True, "lag_sessions": 1, "max_native_lag_sessions": 2}
    stale = {"fresh": False, "lag_sessions": 3, "max_native_lag_sessions": 2}

    def streak(hours):
        return {"hours_lower": 0.0, "hours_upper": hours, "length_known": True, "n_other_failures": 0}

    def status(hours, compensator):
        return triage._streak_item("nasdaq_history", streak(hours), policy=policy, compensator=compensator)["status"]

    assert status(23.9, fresh) == "transport_pending"
    assert status(24.5, fresh) == "escalate"
    assert status(30.0, fresh) == "known_stall"
    assert status(30.0, stale) == "escalate"
    assert status(30.0, None) == "escalate"
    assert status(337.0, fresh) == "escalate"
    unknown = {"hours_lower": 3.0, "hours_upper": None, "length_known": False, "n_other_failures": 0}
    assert triage._streak_item("nasdaq_history", unknown, policy=policy, compensator=fresh)["status"] == "escalate"
    # 정책 없이 부르면 종전 동작(24h 이상 escalate).
    assert triage._streak_item("nasdaq_history", streak(30.0))["status"] == "escalate"
    assert triage.STATUS_EXIT["known_stall"] == 0 and triage.ANNOTATION_LEVEL["known_stall"] == "warning"


def test_alfred_compensator_oracle():
    result = triage.alfred_nasdaq_compensator(ROOT, _utc("2026-11-11T03:09:58.374834Z"), _policy())
    assert result == {"native_last": "2026-11-09", "last_completed": "2026-11-10", "lag_sessions": 1,
                      "fresh": True, "max_native_lag_sessions": 2}


def test_cli_history_receipts_ledger(tmp_path):
    """N3: --history receipts_ledger 는 raw 보고(history 없음)에 영수증 history 를 붙이고 n_dates 도 그 목록으로 센다."""
    name = "daily6m_sources_42950808534"
    report = _fixture(name)["report"]
    code, payload = run_cli(ROOT, _args(kind="daily6m_sources", report=str(_raw_report(tmp_path, name)),
                                        history="receipts_ledger"))
    assert code == 0 and payload["evidence"]["history_provider"] == "daily6m_receipts_session_anchored_v1"
    history = triage.receipt_history(ROOT, _utc(report["completed_at"]))
    expected = {_utc(report["completed_at"]).date()} | {_utc(entry["completed_at"]).date() for entry in history}
    assert payload["n_dates"] == len(expected) >= 2
    assert triage._n_dates(_utc("2026-11-11T00:00:00Z"), [{"completed_at": "2026-11-09T00:00:00Z"}]) == 2
    assert triage._n_dates(_utc("2026-11-11T00:00:00Z"), []) == 1
    # history 인자는 daily6m_sources 에만.
    code, payload = run_cli(ROOT, _args(kind="v2_refresh", history="receipts_ledger",
                                        report=str(FIXTURES / "v2_refresh_market_42950811442.json")))
    assert code == 2


def test_research_cli_verb_specific_arguments():
    """§4.7: --history 는 ingest-triage, --catch-up 은 coherence-monitor, --if-stale 은 v8-live-monitor 전용."""
    from ai_fc.mts_research import cli as research_cli

    for argv in (["fed-ebp-sidecar", "--history", "receipts_ledger"], ["ingest-triage", "--catch-up"],
                 ["coherence-monitor", "--if-stale"], ["v8-live-monitor", "--history", "receipts_ledger"]):
        with pytest.raises(SystemExit) as exc:
            research_cli.main(argv)
        assert exc.value.code == 2, argv
