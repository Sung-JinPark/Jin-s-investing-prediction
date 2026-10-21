"""Latest-origin revisions, tested only in disposable research stores."""
import copy
import json
import shutil
from dataclasses import replace
from datetime import datetime

import pytest
from typer.testing import CliRunner

from ai_fc.cli import app
from ai_fc.timeseries_daily6m import contracts as C, features as F, pipeline as P, refresh as R
from test_timeseries_daily6m_pipeline import published, _fact


def advance(root, monkeypatch, day, stamp, *, issues=()):
    old = F.build_bundle(root, as_of=stamp)
    frame = F.eligible_frame([_fact(sid, day, value, available=stamp)
                              for sid, value in (("NASDAQCOM", 100), ("VIXCLS", 15),
                                                 ("DGS2", 4), ("T10Y2Y", .5), ("DTWEXBGS", 110))], as_of=stamp)
    lineage = copy.deepcopy(old.lineage)
    for row in lineage["market_rows"]:
        row.update(session=day, available_at=stamp, vintage_start=stamp, retrieved_at=stamp)
    bundle = replace(old, anchor={**old.anchor, "date": day, "available_at": stamp},
                     dates=(day,) * 800, history={"dates": [day], "index": [100.]},
                     lineage=lineage, issues=issues, freshness=F.source_freshness(frame, stamp))
    monkeypatch.setattr(F, "read_native_frame", lambda *args, **kwargs: frame.copy())
    monkeypatch.setattr(F, "build_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(F, "aware_time", lambda value=None: datetime.fromisoformat(stamp if value is None else value) if isinstance(value, (str, type(None))) else value)
    return bundle


def monday(published, monkeypatch):
    root, _, _ = published
    advance(root, monkeypatch, "2026-09-14", "2026-09-15T12:00:00+00:00")
    return R.refresh_timeseries_daily6m(root, as_of="2026-09-15T12:00:00+00:00")


def test_missing_then_arrived_input_appends_revision_and_publishes_latest(published, monkeypatch):
    root, original, _ = published
    first = monday(published, monkeypatch)
    prefix = (root / C.FORECAST_LEDGER).read_bytes()
    advance(root, monkeypatch, "2026-09-15", "2026-09-16T12:00:00+00:00",
            issues=("internal complete-session feature gap", "daily gap VIXCLS 2026-09-15"))
    held = R.refresh_timeseries_daily6m(root)
    assert held["status"] == "hold" and "daily gap VIXCLS 2026-09-15" in held["gate"]["reasons"]
    assert (root / C.FORECAST_LEDGER).read_bytes() == prefix
    assert P.publish_latest_timeseries_daily6m(root)["run_id"] == first["run_id"]
    advance(root, monkeypatch, "2026-09-15", "2026-09-16T12:01:00+00:00")
    revised = R.refresh_timeseries_daily6m(root)
    assert revised["supersedes"] == first["run_id"]
    assert revised["anchor_date"] == "2026-09-15"
    assert (root / C.FORECAST_LEDGER).read_bytes().startswith(prefix)
    assert P.publish_latest_timeseries_daily6m(root)["run_id"] == revised["run_id"]
    assert P.verify_timeseries_daily6m(root)["ok"]
    assert P.load_run(root, P.read_chain(root, C.FORECAST_LEDGER)[0])["run_id"] == original["run_id"]
    before = (root / C.FORECAST_LEDGER).read_bytes()
    assert R.refresh_timeseries_daily6m(root)["skipped"] == "completed origin already published"
    assert (root / C.FORECAST_LEDGER).read_bytes() == before


def test_same_input_shadow_is_exactly_the_original_explicit_revision(published, monkeypatch, tmp_path_factory):
    root, _, _ = published
    first = monday(published, monkeypatch)
    shadow = tmp_path_factory.mktemp("explicit-revision")
    shutil.copytree(root, shadow, dirs_exist_ok=True)
    advance(root, monkeypatch, "2026-09-15", "2026-09-16T12:00:00+00:00")
    candidate = R.refresh_timeseries_daily6m(root)
    baseline = P.forecast_timeseries_daily6m(shadow, as_of="2026-09-16T12:00:00+00:00", supersedes=first["run_id"])
    assert {k: v for k, v in candidate.items() if k != "refresh_policy"} == baseline
    assert (root / C.FORECAST_LEDGER).read_bytes() == (shadow / C.FORECAST_LEDGER).read_bytes()
    assert candidate["comparison"]["v8_raw_identity"]["pass"] is True


def test_same_origin_and_manual_weekly_default_remain_idempotent(published):
    root, run, _ = published
    before = (root / C.FORECAST_LEDGER).read_bytes()
    assert R.refresh_timeseries_daily6m(root)["run_id"] == run["run_id"]
    assert P.forecast_timeseries_daily6m(root)["skipped"] == "forecast already exists for this ISO week"
    assert (root / C.FORECAST_LEDGER).read_bytes() == before


def test_old_cutoff_cannot_rollback_or_append(published, monkeypatch):
    root, _, _ = published
    monday(published, monkeypatch)
    before = (root / C.FORECAST_LEDGER).read_bytes()
    advance(root, monkeypatch, "2026-09-11", "2026-09-12T12:00:00+00:00")
    assert R.refresh_timeseries_daily6m(root)["status"] == "hold"
    assert (root / C.FORECAST_LEDGER).read_bytes() == before


def test_existing_run_tampering_and_concurrent_writer_fail_closed(published):
    root, _, _ = published
    with P.writer_lock(root):
        with pytest.raises(P.Daily6mPipelineError, match="another daily6m writer"):
            R.refresh_timeseries_daily6m(root)
    row = P.read_chain(root, C.FORECAST_LEDGER)[0]
    path = root / row["run_path"]
    body = json.loads(path.read_text(encoding="utf-8"))
    body["anchor"]["value"] = 999
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(P.Daily6mPipelineError):
        R.refresh_timeseries_daily6m(root)


def test_cli_explicitly_routes_refresh_and_rejects_ambiguous_revision(monkeypatch):
    calls = []
    monkeypatch.setattr(R, "refresh_timeseries_daily6m", lambda root, **kw: calls.append(kw) or {"status": "hold"})
    result = CliRunner().invoke(app, ["timeseries-daily6m-forecast", "--refresh-latest", "--as-of", "2026-10-21T01:00:00+00:00"])
    assert result.exit_code == 0, result.output
    assert calls == [{"as_of": "2026-10-21T01:00:00+00:00"}]
    bad = CliRunner().invoke(app, ["timeseries-daily6m-forecast", "--refresh-latest", "--supersedes", "prior"])
    assert bad.exit_code != 0 and len(calls) == 1
