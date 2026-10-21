"""Daily issuance orchestration around the unchanged, pinned weekly kernel.

One active forecast per ISO week remains enforced by the original ledger.
New completed origins append explicit superseding revisions; same-origin
corrections still require the manual revision command. No historical run or
numerical dependency is changed by this operational policy.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import contracts as C, features as F, pipeline as P

POLICY = "daily6m_completed_origin_refresh_v1"


@P.serialized_writer
def refresh_timeseries_daily6m(root: Path, *, as_of: str | datetime | None = None) -> dict[str, Any]:
    cutoff = F.aware_time(as_of)
    stamp = cutoff.isoformat()
    C.load_contract(root)
    # Reuse all input gates before selecting a revision. A later native close
    # alone is insufficient when another required completed-session input is
    # missing. The original writer rechecks these gates before its append.
    try:
        frame = F.read_native_frame(root, as_of=cutoff)
        freshness = F.source_freshness(frame, cutoff)
        rejected = ["required source " + row["group"] + " " + row["status"]
                    for row in freshness if row["status"] != "fresh"]
        if rejected:
            return P.hold_payload(rejected, as_of=stamp, evidence={"source_freshness": list(freshness)})
        bundle = F.build_bundle(root, as_of=cutoff, rows=frame)
    except (F.Daily6mFeatureError, OSError, ValueError, RuntimeError) as exc:
        return P.hold_payload([str(exc)], as_of=stamp)
    if bundle.issues:
        return P.hold_payload(list(bundle.issues), as_of=stamp, evidence={"source_freshness": list(bundle.freshness)})

    iso = date.fromisoformat(bundle.anchor["date"]).isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    active = P._active(P.read_chain(root, C.FORECAST_LEDGER))
    supersedes = None
    if active:
        latest = P.load_run(root, active[-1])
        if cutoff < F.aware_time(latest["as_of"]) or bundle.anchor["date"] < latest["anchor_date"]:
            return P.hold_payload(["automatic refresh cannot move issuance or origin backwards"], as_of=stamp)
        same_week = [row for row in active if row["iso_week"] == week]
        if same_week:
            previous = P.load_run(root, same_week[-1])
            if bundle.anchor["date"] == previous["anchor_date"]:
                return {**previous, "skipped": "completed origin already published", "refresh_policy": POLICY}
            supersedes = previous["run_id"]

    # The outer lock covers selection AND append. Use the undecorated original
    # implementation to avoid taking its non-reentrant OS lock twice.
    result = P.forecast_timeseries_daily6m.__wrapped__(root, as_of=stamp, supersedes=supersedes)
    return {**result, "refresh_policy": POLICY}
