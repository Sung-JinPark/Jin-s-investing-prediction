"""Automatic source ordering and explicit waits; no durable store writes."""
import copy
import runpy
import sys
from pathlib import Path

import pytest
import yaml

from ai_fc import daily6m_readiness as R, daily6m_sources as S
from ai_fc.timeseries_daily6m import features as F

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-15T02:30:00+00:00"
ORIGIN = "2026-10-14"


def _frame():
    return F.eligible_frame([
        {"source_id":"alfred", "series_id":sid, "observation_time":ORIGIN,
         "value":value, "value_status":"ok", "source_hash":"a"*64,
         "available_at":"2026-10-15T00:00:00+00:00", "vintage_start":"2026-10-15T00:00:00+00:00",
         "retrieved_at":"2026-10-15T00:00:00+00:00", "vintage_end":None}
        for sid,value in [("NASDAQCOM",100),("VIXCLS",15),("DGS2",4),("T10Y2Y",0.5),("DTWEXBGS",110)]
    ],as_of=NOW)


def test_pending_checkpoint_never_enters_the_sparse_legacy_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(S,"_native_at",lambda *args:{"VIXCLS":{"2026-10-13":{}}})
    monkeypatch.setattr(S,"load_verified_source_observations",lambda *args,**kwargs:[])
    monkeypatch.setattr(F,"read_native_frame",lambda *args,**kwargs:pytest.fail("pending input reached frozen fallback"))
    result=R.check_daily6m_readiness(tmp_path,as_of=NOW)
    assert not result["ready"] and result["status"]=="source_pending"
    assert result["expected_session"]==ORIGIN and result["latest_native_vix_session"]=="2026-10-13"
    assert result["forecast_writes"] is result["source_writes"] is False
    assert list(tmp_path.iterdir())==[]


def test_eligible_native_close_does_not_require_a_captured_replacement(tmp_path,monkeypatch):
    monkeypatch.setattr(S,"_native_at",lambda *args:{"VIXCLS":{ORIGIN:{}}})
    monkeypatch.setattr(S,"load_verified_source_observations",lambda *args,**kwargs:pytest.fail("native input was replaced"))
    frame=_frame(); original=frame.copy(deep=True)
    monkeypatch.setattr(F,"read_native_frame",lambda *args,**kwargs:frame)
    result=R.check_daily6m_readiness(tmp_path,as_of=NOW)
    assert result["ready"] and result["vix_route"]=="native_pit"
    import pandas as pd
    pd.testing.assert_frame_equal(frame,original)


def _captured():
    return {"source_id":"cboe_vix_archive","series_id":"VIX","observation_time":ORIGIN,
            "available_at":"2026-10-15T00:00:00+00:00","vintage_start":"2026-10-15T00:00:00+00:00",
            "retrieved_at":"2026-10-15T00:00:00+00:00"}


@pytest.mark.parametrize("mutation",[{"observation_time":"2026-10-13"},{"source_id":"unregistered"},{"series_id":"OTHER"}])
def test_old_or_other_sources_do_not_satisfy_the_current_vix_checkpoint(tmp_path,monkeypatch,mutation):
    monkeypatch.setattr(S,"_native_at",lambda *args:{"VIXCLS":{"2026-10-13":{}}})
    monkeypatch.setattr(S,"load_verified_source_observations",lambda *args,**kwargs:[{**_captured(),**mutation}])
    monkeypatch.setattr(F,"read_native_frame",lambda *args,**kwargs:pytest.fail("unready source reached kernel"))
    assert not R.check_daily6m_readiness(tmp_path,as_of=NOW)["ready"]


def test_verified_current_capture_still_runs_all_frozen_input_checks(tmp_path,monkeypatch):
    monkeypatch.setattr(S,"_native_at",lambda *args:{"VIXCLS":{"2026-10-13":{}}})
    monkeypatch.setattr(S,"load_verified_source_observations",lambda *args,**kwargs:[_captured()])
    calls=[]
    monkeypatch.setattr(F,"read_native_frame",lambda *args,**kwargs:calls.append(kwargs) or _frame())
    result=R.check_daily6m_readiness(tmp_path,as_of=NOW)
    assert result["ready"] and result["vix_route"]=="registered_captured_forward" and len(calls)==1
    monkeypatch.setattr(F,"source_freshness",lambda *args:[{"group":"dollar","status":"stale"}])
    result=R.check_daily6m_readiness(tmp_path,as_of=NOW)
    assert not result["ready"] and result["reasons"]==["required source dollar stale"]


def test_future_capture_and_broken_evidence_are_not_downgraded_to_normal_waits(tmp_path,monkeypatch):
    monkeypatch.setattr(S,"_native_at",lambda *args:{"VIXCLS":{"2026-10-13":{}}})
    monkeypatch.setattr(S,"load_verified_source_observations",lambda *args,**kwargs:[{**_captured(),"retrieved_at":"2026-10-15T02:31:00+00:00"}])
    with pytest.raises(ValueError,match="after preflight cutoff"):
        R.check_daily6m_readiness(tmp_path,as_of=NOW)
    def corrupt(*args,**kwargs): raise RuntimeError("raw receipt hash mismatch")
    monkeypatch.setattr(S,"load_verified_source_observations",corrupt)
    with pytest.raises(RuntimeError,match="hash mismatch"):
        R.check_daily6m_readiness(tmp_path,as_of=NOW)


@pytest.mark.parametrize("status,ready,exit_code",[("ready",True,0),("source_pending",False,0),("validation_failed",False,1)])
def test_command_preserves_auditable_report_and_output(tmp_path,monkeypatch,status,ready,exit_code):
    def check(*args,**kwargs):
        if status=="validation_failed": raise ValueError("invalid source metadata")
        return {"status":status,"ready":ready,"reasons":[],"forecast_writes":False,"source_writes":False}
    monkeypatch.setattr(R,"check_daily6m_readiness",check)
    report=tmp_path/"report.json"; output=tmp_path/"github-output"
    monkeypatch.setattr(sys,"argv",["check_daily6m_readiness.py","--root",str(tmp_path),"--report",str(report),"--github-output",str(output)])
    command=runpy.run_path(str(ROOT/"tools/check_daily6m_readiness.py"))
    assert command["main"]()==exit_code
    import json
    assert json.loads(report.read_text(encoding="utf8"))["status"]==status
    assert output.read_text()=="ready="+str(ready).lower()+"\n"


def test_automatic_run_waits_for_source_replay_and_cannot_recursively_dispatch():
    workflow=lambda name:yaml.safe_load((ROOT/".github/workflows"/name).read_text(encoding="utf8"))
    daily=workflow("timeseries-daily6m.yml"); source=workflow("daily6m-sources-refresh.yml")
    assert daily["jobs"]["sources"]["uses"]=="./.github/workflows/daily6m-sources-refresh.yml"
    assert daily["jobs"]["sources"]["with"]=={"suppress_forecast_dispatch":True}
    assert daily["jobs"]["research"]["needs"]=="sources"
    steps=daily["jobs"]["research"]["steps"]
    guard=next(i for i,s in enumerate(steps) if s.get("id")=="readiness")
    report=next(s for s in steps if s.get("name")=="Preserve the ready or waiting decision")
    assert report["with"]["include-hidden-files"] is True and report["with"]["if-no-files-found"]=="error"
    for name in ["Refresh the latest completed origin without rewriting prior forecasts","Score only completed and published daily outcomes","Recheck preview gates and publish current HOLD or ready pointer","Commit only the new research ledger and derived pointer"]:
        i=next(i for i,s in enumerate(steps) if s.get("name")==name)
        assert i>guard and steps[i]["if"]=="${{ steps.readiness.outputs.ready == 'true' }}"
    trigger=source.get("on",source.get(True))
    assert trigger["workflow_call"]["inputs"]["suppress_forecast_dispatch"]["default"] is False
    dispatch=next(s for s in source["jobs"]["publish"]["steps"] if s.get("name")=="Recheck and regenerate the separate weekly research forecast")
    assert dispatch["if"]=="${{ steps.decision.outputs.changed == 'true' }}"
    assert dispatch["env"]["SUPPRESS_FORECAST_DISPATCH"]=="${{ inputs.suppress_forecast_dispatch || false }}"
    assert 'if [ "$workflow" = "timeseries-daily6m.yml" ] && [ "$SUPPRESS_FORECAST_DISPATCH" = "true" ]; then' in dispatch["run"]
