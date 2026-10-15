"""Warm-watch scheduling uses fixture clocks and immutable temporary bundles."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.earnings_refresh import EarningsRefreshError
from ai_fc.earnings_watch import watch_earnings


START = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = START
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def event(*, status="confirmed", offset=6 * 3600, identity="tsmc_2026_q3"):
    return {"event_id": identity, "kind": "earnings", "status": status,
            "scheduled_at": (START + timedelta(seconds=offset)).isoformat()}


def source(identity="tsmc_2026_q3", kind="official", status="pending"):
    return {"event_id": identity, "kind": kind, "status": status}


def fixture_capture(clock, sequence):
    attempts = []
    def collect(root, *, output_dir, now, **_kwargs):
        attempt = Path(output_dir)
        assert attempt.is_relative_to(root) and not attempt.exists()
        assert now == clock()
        item = sequence[min(len(attempts), len(sequence) - 1)]
        attempts.append(attempt)
        attempt.mkdir()
        manifest = {"events": item.get("events", [event()]),
                    "event_status": item.get("statuses", [source(kind="nasdaq"), source()]),
                    "attempt": len(attempts)}
        (attempt / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (attempt / "raw.html").write_text(f"fixture-{len(attempts)}", encoding="utf-8")
        clock.now += timedelta(seconds=item.get("latency", 0))
        return {"status": item.get("status", "captured"), "changed_hint": item.get("changed", False),
                "bundle_path": str(attempt), "bundle_id": f"attempt-{len(attempts)}",
                "source_failures": item.get("source_failures", [])}
    return collect, attempts


def run(tmp_path, sequence, **kwargs):
    clock = Clock()
    capture, attempts = fixture_capture(clock, sequence)
    target = tmp_path / ".tmp" / "selected"
    report = watch_earnings(tmp_path, output_dir=target, clock=clock, sleep=clock.sleep,
                            capture=capture, **kwargs)
    return report, clock, attempts, target


def test_pending_then_changed_returns_immediately_and_only_keeps_final_bundle(tmp_path):
    report, clock, attempts, target = run(tmp_path, [{}, {}, {"changed": True}])
    assert report["changed_hint"] is True and report["watch_attempts"] == 3
    assert report["watch_seconds"] == 120 and clock.sleeps == [60, 60]
    assert report["bundle_path"] == str(target.resolve())
    assert (target / "raw.html").read_text() == "fixture-3"
    assert all(not p.exists() for p in attempts)
    assert not list(target.parent.glob(".earnings-watch-*"))


def test_changed_first_attempt_does_not_wait(tmp_path):
    report, clock, _, _ = run(tmp_path, [{"changed": True}])
    assert report["watch_attempts"] == 1 and report["watch_seconds"] == 0
    assert clock.sleeps == []
    assert report["watch_pending"] is True
    assert datetime.fromisoformat(report["watch_until"]) > clock.now


def test_partial_capture_returns_without_hiding_operational_failure(tmp_path):
    failures = [{"kind": "nasdaq", "reason": "fixture unavailable"}]
    report, clock, _, _ = run(tmp_path, [{"status": "partial", "source_failures": failures,
                                        "statuses": [source(kind="nasdaq", status="failed"), source(status="failed")]}])
    assert report["status"] == "partial" and report["source_failures"] == failures
    assert report["watch_attempts"] == 1 and clock.sleeps == []
    assert report["watch_pending"] is False


def test_one_blocked_issuer_does_not_stop_the_healthy_nasdaq_release_watch(tmp_path):
    partial = {"status": "partial", "source_failures": [{"kind": "official", "reason": "HTTPError"}],
               "statuses": [source(kind="nasdaq"), source(status="failed")]}
    released = {**partial, "changed": True,
                "statuses": [source(kind="nasdaq", status="reported"), source(status="failed")]}
    report, clock, _, _ = run(tmp_path, [partial, partial, released])
    assert report["status"] == "partial" and report["changed_hint"] is True
    assert report["source_failures"] == partial["source_failures"]
    assert report["watch_attempts"] == 3 and clock.sleeps == [60, 60]
    assert report["watch_pending"] is False


def test_partial_watch_budget_continues_only_with_a_healthy_registered_source(tmp_path):
    partial = {"status": "partial", "source_failures": [{"kind": "official", "reason": "HTTPError"}],
               "statuses": [source(kind="nasdaq"), source(status="failed")]}
    report, clock, _, _ = run(tmp_path, [partial], max_seconds=90)
    assert report["status"] == "partial" and report["changed_hint"] is False
    assert report["watch_attempts"] == 3 and clock.sleeps == [60, 30]
    assert report["watch_pending"] is True


@pytest.mark.parametrize("kind", ["nasdaq", "official"])
def test_either_provider_actual_completes_event_without_waiting(tmp_path, kind):
    report, clock, _, _ = run(tmp_path, [{"statuses": [source(kind=kind, status="reported")]}])
    assert report["watch_attempts"] == 1 and clock.sleeps == []
    assert report["watch_pending"] is False and report["watch_until"] is None


@pytest.mark.parametrize("events", [[], [event(status="estimated")],
                                        [event(offset=6 * 3600 + 1)],
                                        [event(offset=-3 * 3600 - 1)]])
def test_no_event_estimated_or_outside_window_does_not_wait(tmp_path, events):
    report, clock, _, _ = run(tmp_path, [{"events": events}])
    assert report["status"] == "captured" and report["changed_hint"] is False
    assert report["watch_attempts"] == 1 and clock.sleeps == []


def test_watch_budget_has_final_poll_and_nochange_is_normal(tmp_path):
    report, clock, _, target = run(tmp_path, [{}], max_seconds=90)
    assert report["status"] == "captured" and report["changed_hint"] is False
    assert report["watch_attempts"] == 3 and report["watch_seconds"] == 90
    assert clock.sleeps == [60, 30] and target.is_dir()
    assert report["watch_pending"] is True
    assert datetime.fromisoformat(report["watch_until"]) > clock.now


def test_zero_budget_still_captures_once(tmp_path):
    report, clock, _, _ = run(tmp_path, [{}], max_seconds=0)
    assert report["watch_attempts"] == 1 and clock.sleeps == []


def test_capture_latency_counts_toward_budget(tmp_path):
    report, clock, _, _ = run(tmp_path, [{"latency": 100}], max_seconds=90)
    assert report["watch_attempts"] == 1 and report["watch_seconds"] == 100
    assert clock.sleeps == []


def test_watch_stops_exactly_at_three_hours_after_scheduled_time(tmp_path):
    report, clock, _, _ = run(tmp_path, [{"events": [event(offset=-3 * 3600 + 30)]}])
    assert clock.sleeps == [30] and report["watch_seconds"] == 30
    assert report["watch_attempts"] == 2
    assert report["watch_pending"] is False and report["watch_until"] is None


def test_reported_other_event_does_not_hide_pending_event(tmp_path):
    items = {"events": [event(identity="asml_2026_q3"), event()],
             "statuses": [source("asml_2026_q3", status="reported"), source()]}
    report, clock, _, _ = run(tmp_path, [items, {"changed": True}])
    assert report["watch_attempts"] == 2 and clock.sleeps == [60]


def test_existing_output_is_preserved_before_any_capture(tmp_path):
    output = tmp_path / "selected"
    output.mkdir()
    (output / "sentinel").write_text("untouched")
    with pytest.raises(EarningsRefreshError, match="already exists"):
        watch_earnings(tmp_path, output_dir=output, capture=lambda *_a, **_k: pytest.fail("unexpected capture"))
    assert (output / "sentinel").read_text() == "untouched"


def test_output_cannot_escape_workspace(tmp_path):
    with pytest.raises(EarningsRefreshError, match="within its workspace"):
        watch_earnings(tmp_path, output_dir=tmp_path / ".." / "escaped")


def test_source_exception_is_not_swallowed_and_scratch_is_cleaned(tmp_path):
    def broken(*_args, **_kwargs):
        raise RuntimeError("source fixture failure")
    with pytest.raises(RuntimeError, match="source fixture failure"):
        watch_earnings(tmp_path, output_dir="selected", capture=broken)
    assert not (tmp_path / "selected").exists() and not list(tmp_path.glob(".earnings-watch-*"))


@pytest.mark.parametrize("kwargs", [{"max_seconds": -1}, {"max_seconds": 19801},
                                         {"max_seconds": float("nan")}, {"poll_seconds": 0},
                                         {"poll_seconds": 61}, {"poll_seconds": True}])
def test_invalid_watch_durations_rejected(tmp_path, kwargs):
    with pytest.raises(EarningsRefreshError, match="duration"):
        watch_earnings(tmp_path, output_dir="selected", **kwargs)
