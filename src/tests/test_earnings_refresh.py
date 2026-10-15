"""Raw-first earnings replay fixtures; no test accesses live data or the network."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_fc import earnings_refresh as R
from ai_fc import event_consensus as E

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.fromisoformat("2026-10-15T00:00:00+00:00")


def _root(tmp_path):
    root = tmp_path / "repo"
    for relative in ("data/calendar/events.csv", "data/contracts/calendar_sources.yaml"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return root


def _html(value="12.95", published="2026-10-14T05:00:00Z"):
    return f'''<html><title>ASML reports Q3 2026 financial results</title>
    <meta property="article:published_time" content="{published}">
    <p data-isin="NL0010273215">ASML HOLDING NV US GAAP quarter ended September 27, 2026</p>
    <table><tr><th>in millions of euros</th><th>Q2 2026</th><th>Q3 2026</th></tr>
    <tr><td>EPS (basic; in euros)</td><td>7.59</td><td>{value}</td></tr>
    <tr><td>Total net sales</td><td>7680</td><td>11662.0</td></tr>
    <tr><td>Gross margin (%)</td><td>52.1</td><td>57.5</td></tr></table></html>'''


def _capture(root, out, *, now=NOW, value="12.95", nasdaq_fail=False, official_fail=False, fallback=False, published="2026-10-14T05:00:00Z", latency=0):
    tick = [now]
    def json_fetch(url):
        tick[0] += timedelta(seconds=latency)
        if nasdaq_fail:
            raise E.ConsensusError("fixture blocked")
        if "earnings-surprise" in url:
            return {"data": {"earningsSurpriseTable": {"rows": [{"dateReported": "7/15/2026", "fiscalQtrEnd": "Jun 2026", "eps": 8.81, "consensusForecast": "7.98"}]}}}
        return {"data": {"quarterlyForecast": {"rows": [{"fiscalEnd": "Sep 2026", "consensusEPSForecast": 12.47, "noOfEstimates": 3}]}}}
    def text_fetch(url):
        tick[0] += timedelta(seconds=latency)
        if official_fail or (fallback and "euronext" in url):
            raise OSError("fixture transport unavailable")
        if "tsmc" in url:
            return "<html><title>TSMC Q3 2026</title><p>Third quarter guidance US$44.6-45.8 billion</p></html>"
        return _html(value, published)
    return R.capture_earnings(root, output_dir=out, now=now, fetch_json=json_fetch, fetch_text=text_fetch, clock=lambda: tick[0])


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "data").rglob("*") if p.is_file()}


def _rehash(bundle, mutate):
    path = bundle / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    body = {k: v for k, v in value.items() if k not in {"bundle_id", "content_hash"}}
    body["bundle_id"] = "earnings-" + E.canonical_hash(body)[:24]
    path.write_bytes(R._bytes({**body, "content_hash": E.canonical_hash(body)}))


def test_capture_apply_keeps_official_eur_separate_and_repeated_poll_is_noop(tmp_path):
    root = _root(tmp_path)
    before = _snapshot(root)
    captured = _capture(root, tmp_path / "first", latency=1)
    assert captured["status"] == "captured" and captured["changed_hint"] is True and _snapshot(root) == before
    manifest = json.loads((Path(captured["bundle_path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert {"ASML", "TSM"} <= {e["ticker"] for e in manifest["events"]}
    assert captured["unsupported_events"] == [{"event_id": "005930_2026_q3_prelim_est", "ticker": "005930", "reason": "no_registered_keyless_earnings_adapter"}]
    assert all("005930" not in receipt["source_url"] for receipt in manifest["receipts"])
    assert all(R._time(r["captured_at"]) > R._time(r["requested_at"]) for r in manifest["receipts"])
    applied = R.apply_earnings(root, bundle_dir=captured["bundle_path"], now=NOW + timedelta(minutes=1))
    assert applied["changed"] and applied["appended"] >= 4
    rows = E.load_event_consensus(root, NOW + timedelta(minutes=1))["asml_2026_q3"]
    eps = next(r for r in rows if r["metric"] == "eps")
    official = next(r for r in rows if r["metric"] == "eps_reported")
    assert eps["actual"] is None and eps["consensus"] == "$12.47"
    assert official["actual"] == "EUR 12.95" and official["currency"] == "EUR" and official["comparison_allowed"] is False
    assert E.load_event_consensus(root, NOW) == {}, "response completion cannot be backdated to batch start"
    before = _snapshot(root)
    repeated = _capture(root, tmp_path / "repeat", now=NOW + timedelta(minutes=5))
    assert repeated["changed_hint"] is False
    assert R.apply_earnings(root, bundle_dir=repeated["bundle_path"], now=NOW + timedelta(minutes=6))["appended"] == 0
    assert _snapshot(root) == before


def test_revision_chain_preserves_legacy_and_older_bundle_cannot_revert_actual(tmp_path):
    root = _root(tmp_path)
    legacy = {"event_id": "asml_2026_q3", "metric": "eps", "label": "주당순이익(EPS)", "actual": None, "consensus": "$12.47", "previous": "$8.81", "period": "Sep 2026 분기", "source": E.EPS_SOURCE, "source_url": E.EPS_PAGE_URL.format(ticker="asml"), "note": "애널리스트 3명", "captured_at": "2026-10-11T09:43:03Z"}
    path = root / E.LEDGER_RELATIVE
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
    prefix = path.read_bytes()
    old = _capture(root, tmp_path / "old")
    first = R.apply_earnings(root, bundle_dir=old["bundle_path"], now=NOW + timedelta(minutes=1))
    assert first["changed"] and path.read_bytes().startswith(prefix)
    records = E._read_ledger(path)
    changed_eps = next(r for r in records if r.get("supersedes") == E.record_id(legacy))
    assert changed_eps["metric"] == "eps"
    new = _capture(root, tmp_path / "new", now=NOW + timedelta(minutes=5), value="13.01")
    assert R.apply_earnings(root, bundle_dir=new["bundle_path"], now=NOW + timedelta(minutes=6))["appended"] == 1
    before = _snapshot(root)
    stale = R.apply_earnings(root, bundle_dir=old["bundle_path"], now=NOW + timedelta(minutes=7))
    assert stale["appended"] == 0 and stale["stale_ignored"] > 0 and _snapshot(root) == before
    visible = E.load_event_consensus(root, NOW + timedelta(minutes=2))["asml_2026_q3"]
    assert next(r for r in visible if r["metric"] == "eps_reported")["actual"] == "EUR 12.95"


def test_nasdaq_failure_does_not_prevent_independent_official_append_and_recovery(tmp_path):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "partial", nasdaq_fail=True)
    assert captured["status"] == "partial" and captured["changed_hint"] is True
    applied = R.apply_earnings(root, bundle_dir=captured["bundle_path"], now=NOW + timedelta(minutes=1))
    assert applied["changed"] and applied["source_failures"]
    recovered = _capture(root, tmp_path / "recovered", now=NOW + timedelta(minutes=5))
    assert recovered["changed_hint"] is True
    assert R.apply_earnings(root, bundle_dir=recovered["bundle_path"], now=NOW + timedelta(minutes=6))["appended"] >= 2
    assert len([r for r in E._read_ledger(root / E.LEDGER_RELATIVE) if r["metric"] == "eps_reported"]) == 1


def test_successful_official_fallback_keeps_attempt_failure_diagnostic(tmp_path):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "fallback", fallback=True)
    assert captured["status"] == "captured" and captured["source_failures"] == [] and captured["attempt_failures"]
    assert R.apply_earnings(root, bundle_dir=captured["bundle_path"], now=NOW + timedelta(minutes=1))["changed"]


@pytest.mark.parametrize("tamper", ["path", "hash", "clock", "quarter", "currency", "omitted_source"])
def test_hash_valid_tampered_bundle_fails_before_any_canonical_append(tmp_path, tamper):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "capture")
    bundle = Path(captured["bundle_path"])
    before = _snapshot(root)
    def mutate(value):
        if tamper == "path":
            value["receipts"][0]["raw_path"] = "../escaped.gz"
        elif tamper == "hash":
            value["receipts"][0]["source_hash"] = "a" * 64
        elif tamper == "clock":
            value["receipts"][0]["captured_at"] = (NOW + timedelta(days=1)).isoformat()
        elif tamper in {"quarter", "currency"}:
            row = next(r for r in value["candidates"] if r["metric"] == "eps_reported")
            row["fiscal_quarter" if tamper == "quarter" else "currency"] = 4 if tamper == "quarter" else "USD"
        else:
            value["event_status"].pop()
    _rehash(bundle, mutate)
    with pytest.raises((R.EarningsRefreshError, E.ConsensusError)):
        R.apply_earnings(root, bundle_dir=bundle, now=NOW + timedelta(minutes=1))
    assert _snapshot(root) == before


def test_pending_tsmc_guidance_never_becomes_actual_and_future_publication_rejects(tmp_path):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "future", published="2026-10-16T05:00:00Z")
    assert captured["status"] == "partial"
    R.apply_earnings(root, bundle_dir=captured["bundle_path"], now=NOW + timedelta(minutes=1))
    for rows in E.load_event_consensus(root, NOW + timedelta(minutes=1)).values():
        assert all(r["actual"] is None for r in rows)


def test_fiscal_roll_forward_does_not_attach_next_quarter_to_old_event():
    event = {"event_id": "asml_2026_q3", "kind": "earnings", "date": "2026-10-14", "ticker": "ASML"}
    def fetch(url):
        if "earnings-surprise" in url:
            return {"data": {"earningsSurpriseTable": {"rows": [{"dateReported": "1/20/2027", "fiscalQtrEnd": "Dec 2026", "eps": 99}]}}}
        return {"data": {"quarterlyForecast": {"rows": [{"fiscalEnd": "Dec 2026", "consensusEPSForecast": 99}]}}}
    assert E.earnings_rows(event, fetch, as_of=NOW) == []


def test_claimed_nasdaq_failure_cannot_hide_valid_captured_rows(tmp_path):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "capture")
    bundle = Path(captured["bundle_path"])
    before = _snapshot(root)
    def mutate(value):
        for status in value["event_status"]:
            if status["kind"] == "nasdaq":
                event = next(e for e in value["events"] if e["event_id"] == status["event_id"])
                status["status"] = "failed"
                value["source_failures"].append({"event_id": event["event_id"], "ticker": event["ticker"], "kind": "nasdaq", "reason": "ClaimedFailure"})
        value["candidates"] = [r for r in value["candidates"] if r["metric"] != "eps"]
    _rehash(bundle, mutate)
    with pytest.raises(R.EarningsRefreshError, match="contradicts successful"):
        R.apply_earnings(root, bundle_dir=bundle, now=NOW + timedelta(minutes=1))
    assert _snapshot(root) == before


def test_unsupported_scope_cannot_be_silently_removed_from_bundle(tmp_path):
    root = _root(tmp_path)
    captured = _capture(root, tmp_path / "capture")
    bundle = Path(captured["bundle_path"])
    before = _snapshot(root)
    _rehash(bundle, lambda value: value.update(unsupported_events=[]))
    with pytest.raises(R.EarningsRefreshError, match="scope audit"):
        R.apply_earnings(root, bundle_dir=bundle, now=NOW + timedelta(minutes=1))
    assert _snapshot(root) == before
