"""Read-only operational preflight for the frozen daily6m numerical kernel.

The automatic job must checkpoint registered inputs before invoking the
kernel. It cannot rely on the older sparse V2 VIX fallback when other live
tails have added optional provenance columns to the frame.
"""
from pathlib import Path


def check_daily6m_readiness(root: Path, *, as_of=None) -> dict:
    from . import daily6m_sources as S
    from .timeseries_daily6m import features as F

    cutoff = F.aware_time(as_of)
    completed = F.last_completed_session(cutoff)
    native = S._native_at(Path(root), cutoff)
    vix = native.get("VIXCLS", {})
    route = "native_pit" if completed in vix else None
    if route is None:
        observations = S.load_verified_source_observations(Path(root), as_of=cutoff)
        for row in observations:
            if (row["source_id"] == "cboe_vix_archive" and row["series_id"] == "VIX"
                    and row["observation_time"] == completed):
                if any(F.aware_time(row[key]) > cutoff for key in ("available_at", "vintage_start", "retrieved_at")):
                    raise ValueError("registered current-session VIX capture is after preflight cutoff")
                route = "registered_captured_forward"
    report = {"schema_version": 1, "as_of": cutoff.isoformat(), "expected_session": completed,
              "ready": False, "status": "source_pending", "vix_route": route,
              "latest_native_vix_session": max(vix, default=None), "reasons": [],
              "forecast_writes": False, "source_writes": False}
    if route is None:
        report["reasons"] = ["verified current-session VIX has not been checkpointed"]
        return report
    # This is the unchanged kernel's own receipt, calendar, PIT and freshness
    # validation. The preflight neither repairs a frame nor changes a value.
    frame = F.read_native_frame(Path(root), as_of=cutoff)
    freshness = F.source_freshness(frame, cutoff)
    report["source_freshness"] = list(freshness)
    report["reasons"] = ["required source " + row["group"] + " " + row["status"]
                         for row in freshness if row["status"] != "fresh"]
    for sid in ("NASDAQCOM", "VIXCLS"):
        rows = frame[(frame["series_id"] == sid) & (frame["day"] == completed)]
        if rows.empty:
            report["reasons"].append("verified completed-session close missing: " + sid)
    report["ready"] = not report["reasons"]
    report["status"] = "ready" if report["ready"] else "source_pending"
    return report
