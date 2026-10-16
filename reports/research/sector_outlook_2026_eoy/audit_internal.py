"""Read-only, stdlib-only audit for the 2026 year-end sector research.

Run: python reports/research/sector_outlook_2026_eoy/audit_internal.py
Use --offline to replay saved public snapshots without HTTP GETs. Only internal_audit.json
and public_snapshot/*.json beside this script are written. No application imports, collectors, sync commands,
broker/security endpoints, dependency installation, or secret reads are used.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "internal_audit.json"
AS_OF = "2026-10-12T09:16:14+09:00"
CUTOFF = dt.datetime.fromisoformat(AS_OF)
READ_FILES = [
    "AGENTS.md", "db/index.db", "dualdb/db/dualdb.sqlite",
    "calibration/ledger.csv", "calibration/benchmark_ledger.csv",
    "calibration/corrections.csv", "calibration/approvals.csv",
    "calibration/research_status_overrides.csv", "data/contracts/ledger_registry.yaml",
    "_site/data.json", "_site/statistics.json", "_site/future_paths.json",
    "data/statistics/dotcom_statistics_latest.json",
    "data/statistics/official_store/ledgers/normalized_observations.jsonl",
    "data/statistics/official_store/ledgers/raw_receipts.jsonl",
    "data/statistics/official_store/ledgers/raw_receipt_corrections.jsonl",
    "data/timeseries_v8/multivariate_v8_latest.json",
    "data/timeseries_v8/ledgers/shadow_forecasts.jsonl",
    "data/timeseries/ledgers/source_backfill_audit.jsonl",
    "data/timeseries_v13/vol/vol_latest.json",
    "data/timeseries_v13/ledgers/approvals.jsonl",
    "data/timeseries_v13/ledgers/holdout_scorings.jsonl",
    "data/scenarios/nasdaq_latest.json",
    "data/ai_capital_cycle/company_capex_quarterly_latest.json",
    "data/ai_capital_cycle/ai_regime_latest.json",
    "data/ai_capital_cycle/coverage_latest.json",
    "data/ai_capital_cycle/d0_source_audit.json",
    "src/ai_fc/dashboard.py", "src/ai_fc/db/ingest.py",
]
PUBLIC_URLS = [
    "https://sung-jinpark.github.io/Jin-s-investing-prediction/data.json",
    "https://sung-jinpark.github.io/Jin-s-investing-prediction/statistics.json",
    "https://sung-jinpark.github.io/Jin-s-investing-prediction/future_paths.json",
]


def timestamp(value):
    """Never invent a timezone for a naive historical timestamp."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def timely(value):
    parsed = timestamp(value)
    return parsed is not None and parsed <= CUTOFF


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def read_jsonl(relative):
    return [json.loads(line) for line in (ROOT / relative).read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]


def sha(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fingerprint(paths):
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for path in sorted(set(paths)) if path.is_file()}


def database(relative):
    connection = sqlite3.connect((ROOT / relative).as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    return connection


def query(connection, sql, args=()):
    return [dict(row) for row in connection.execute(sql, args)]


def inventory(connection):
    names = [row["name"] for row in query(connection,
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: {
        "n": connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0],
        "columns": [row["name"] for row in query(connection, 'PRAGMA table_info("' + name + '")')],
    } for name in names}


def mean(values):
    return sum(values) / len(values) if values else None


def forecast_audit(connection):
    forecasts = query(connection, "SELECT * FROM forecasts ORDER BY forecast_ts,forecast_id")
    probability_records = query(connection, "SELECT * FROM probability_record ORDER BY entity_type,entity_id")
    explicit = {(row["entity_type"], row["entity_id"]): row for row in probability_records}
    resolutions = query(connection, "SELECT * FROM resolutions ORDER BY resolved_date,forecast_id")
    events = query(connection, "SELECT * FROM resolution_event ORDER BY question_id")
    records = []
    invalid = []
    for forecast in forecasts:
        record = explicit.get(("forecast", forecast["forecast_id"]))
        reason = []
        if record is None or record.get("source_unit") not in ("fraction", "percent"):
            reason.append("missing_or_unsupported_explicit_probability_unit")
        else:
            factor = 0.01 if record["source_unit"] == "percent" else 1.0
            converted = forecast["probability"] * factor
            if not 0 <= converted <= 1 or not math.isclose(converted, record["probability"], abs_tol=1e-12):
                reason.append("canonical_probability_mismatch_or_out_of_bounds")
            if forecast["ci80_lo"] is not None and forecast["ci80_hi"] is not None:
                lower = forecast["ci80_lo"] * factor
                upper = forecast["ci80_hi"] * factor
                if not 0 <= lower <= converted <= upper <= 1:
                    reason.append("confidence_interval_does_not_contain_probability")
        path = ROOT / forecast["path"]
        file_hash = sha(path) if path.is_file() else None
        if file_hash != forecast["file_sha256"]:
            reason.append("source_file_hash_mismatch")
        if reason:
            invalid.append({"forecast_id": forecast["forecast_id"], "reasons": reason})
        records.append({
            "forecast_id": forecast["forecast_id"], "question_id": forecast["question_id"],
            "source_probability": forecast["probability"],
            "source_unit": None if record is None else record["source_unit"],
            "canonical_probability": None if record is None else record["probability"],
            "canonical_unit": "fraction", "probability_space": None if record is None else record["probability_space"],
            "forecast_ts": forecast["forecast_ts"], "forecast_timestamp_timezone_proven": timestamp(forecast["forecast_ts"]) is not None,
            "ingested_at": forecast["ingested_at"], "research_status": forecast["research_status"],
            "path": forecast["path"], "file_sha256": file_hash,
        })
    brier_mismatches = []
    for row in resolutions:
        record = explicit.get(("resolution", row["forecast_id"] + "@" + row["resolved_date"]))
        # Resolution entity IDs are discovered from explicit metadata, not magnitude.
        if record is None:
            matches = [item for item in probability_records if item["entity_type"] == "resolution"
                       and item["entity_id"].split("@")[0] == row["forecast_id"]]
            record = matches[0] if len(matches) == 1 else None
        if record is None:
            brier_mismatches.append({"forecast_id": row["forecast_id"], "reason": "explicit_resolution_unit_missing"})
        elif not math.isclose((record["probability"] - row["outcome"]) ** 2, row["brier"], abs_tol=1e-12):
            brier_mismatches.append({"forecast_id": row["forecast_id"], "reason": "brier_mismatch"})
    raw = query(connection, "SELECT * FROM v_brier")
    primary = query(connection, "SELECT * FROM v_brier_primary")
    domain_events = query(connection,
        "SELECT domain,COUNT(*) AS n_independent_events,AVG(primary_brier) AS brier FROM resolution_event GROUP BY domain ORDER BY domain")
    independent_latest = mean([(event["latest_probability"] - event["outcome"]) ** 2 for event in events])
    independent_first = mean([(event["first_probability"] - event["outcome"]) ** 2 for event in events])
    corrected = query(connection, "SELECT * FROM v_benchmark_corrected")
    valid_ids = {row["forecast_id"] for row in query(connection, "SELECT * FROM v_benchmark_valid")}
    benchmark_invalid = [{"forecast_id": row["forecast_id"], "resolved_date": row["resolved_date"],
                          "market_prob": row["market_prob"], "reason": "fraction_contract_violation_pending_correction"}
                         for row in corrected if row["forecast_id"] not in valid_ids]
    return {
        "probability_contract": {"canonical_unit": "fraction", "explicit_metadata_table": "probability_record",
            "legacy_forecasts_and_resolution_source_unit": "percent", "source_unit_not_inferred_from_magnitude": True,
            "probability_metadata_groups": query(connection, "SELECT entity_type,source_unit,probability_space,COUNT(*) AS n FROM probability_record GROUP BY entity_type,source_unit,probability_space")},
        "source_forecast_rows": records, "invalid_forecast_rows": invalid, "brier_mismatches": brier_mismatches,
        "n_resolved_ledger_rows": len(resolutions), "n_independent_events": len(events),
        "row_brier_all": raw, "row_brier_primary": primary, "independent_event_brier_by_domain": domain_events,
        "independent_event_brier_primary_time_weighted": mean([event["primary_brier"] for event in events]),
        "independent_event_brier_first_forecast": independent_first,
        "independent_event_brier_latest_forecast": independent_latest,
        "independent_event_rows": events,
        "gates": {name: query(connection, "SELECT * FROM " + name) for name in ["v_gate_status", "v_gate_status_all", "v_gate_status_v2"]},
        "research_status_overrides": query(connection, "SELECT * FROM research_status_override"),
        "benchmark": {"n_raw_rows": len(corrected), "n_valid_rows": len(valid_ids), "rejected_rows": benchmark_invalid,
            "paired_comparisons": query(connection, "SELECT * FROM v_benchmark_pairwise"),
            "inference": "No valid paired ML/market scores; relative forecasting skill cannot be claimed."},
        "corrections": query(connection, "SELECT * FROM correction_ledger ORDER BY correction_id"),
        "claims_not_supported": ["calibrated sector-return probabilities", "statistically established return-prediction skill",
            "earnings-beat accuracy implies stock-price outperformance"],
        "historical_origin_validation_limit": "Naive forecast_ts and ingested_at fields have no explicit timezone; source row input availability is not reconstructed here. The audit proves currently stored units and scores, not original-time leakage-free forecasting.",
        "anchor_adjustment_validation": "Full anchor + signed adjustments proof requires each original forecast's structured adjustments; this read audit makes no new official forecast and does not infer these from prose.",
    }


def official_statistics_audit():
    observations = read_jsonl("data/statistics/official_store/ledgers/normalized_observations.jsonl")
    receipts = read_jsonl("data/statistics/official_store/ledgers/raw_receipts.jsonl")
    corrections = read_jsonl("data/statistics/official_store/ledgers/raw_receipt_corrections.jsonl")
    published = read_json("data/statistics/dotcom_statistics_latest.json")
    by_id = {row["observation_id"]: row for row in observations}
    latest = {}
    violations = []
    units = collections.Counter()
    for row in observations:
        units[row["unit"]] += 1
        prior_id = row.get("supersedes_observation_id")
        if row["revision_seq"] > 0:
            prior = by_id.get(prior_id)
            if prior is None or prior["revision_seq"] + 1 != row["revision_seq"]:
                violations.append({"observation_id": row["observation_id"], "reason": "missing_or_nonsequential_supersedes"})
            elif (prior["source_id"], prior["series_id"], prior["observation_date"]) != (row["source_id"], row["series_id"], row["observation_date"]):
                violations.append({"observation_id": row["observation_id"], "reason": "supersedes_changes_observation_key"})
        if not timely(row["available_at"]):
            violations.append({"observation_id": row["observation_id"], "reason": "available_at_unknown_or_after_research_cutoff"})
            continue
        key = (row["source_id"], row["series_id"], row["observation_date"])
        previous = latest.get(key)
        if previous is None or row["revision_seq"] > previous["revision_seq"]:
            latest[key] = row
    raw_files = {}
    bad_raw = []
    for receipt in receipts:
        relative = "data/statistics/official_store/" + receipt["artifact_path"]
        if relative not in raw_files:
            path = ROOT / relative
            raw_files[relative] = sha(path) if path.is_file() else None
        if raw_files[relative] != receipt["raw_sha256"]:
            bad_raw.append({"receipt_id": receipt["receipt_id"], "reason": "raw_artifact_hash_missing_or_mismatch"})
    raw_hashes = {receipt["raw_sha256"] for receipt in receipts}
    orphan_hashes = sorted({row["raw_sha256"] for row in observations} - raw_hashes)
    latest_series = collections.defaultdict(list)
    for row in latest.values():
        latest_series[row["series_id"]].append(row)
    summary = []
    for series, rows in sorted(latest_series.items()):
        newest = max(rows, key=lambda row: row["observation_date"])
        summary.append({"series_id": series, "n_dates": len(rows), "latest_observation": newest["observation_date"],
            "value": newest["value"], "unit": newest["unit"], "available_at": newest["available_at"],
            "vintage_date": newest["vintage_date"], "revision_seq": newest["revision_seq"], "raw_sha256": newest["raw_sha256"]})
    return {
        "n_rows": len(observations), "n_unique_observations_as_of": len(latest), "n_revision_rows": sum(row["revision_seq"] > 0 for row in observations),
        "n_raw_receipts": len(receipts), "n_raw_artifacts_checked": len(raw_files), "units": dict(units),
        "n_raw_receipt_corrections": len(corrections), "raw_receipt_corrections": corrections,
        "revision_and_cutoff_violations": violations, "raw_hash_failures": bad_raw, "orphan_raw_sha256": orphan_hashes,
        "series_latest": summary,
        "source_policy": published["numeric_source_policy"],
        "source_approval_metadata": [{key: row.get(key) for key in ["series_id", "policy_source_id", "authority_class", "numeric_input_allowed", "source_url", "latest_observation"]} for row in published["sources"]],
        "revision_approval_limit": "Normalized observation rows contain revision_seq and supersedes lineage but no per-revision approval/reviewer metadata. Current-latest revisions selected here are not asserted to be individually approved; only published source-policy approvals are evidenced.",
        "point_in_time_limit": published["vintage_warning"],
        "reference_only": {key: published[key] for key in ["model_use", "official_forecast_input", "generated_at", "knowledge_cutoff", "observation_through"]},
    }, latest_series, [ROOT / relative for relative in raw_files]


def month_offset(date, months):
    target = date.year * 12 + date.month - 1 - months
    year, month = divmod(target, 12)
    return dt.date(year, month + 1, min(date.day, calendar.monthrange(year, month + 1)[1]))


def stale_market_facts(series_rows):
    result = []
    for series in ["NASDAQSOX", "NASDAQCOM", "SP500"]:
        rows = sorted(series_rows.get(series, []), key=lambda row: row["observation_date"])
        rows = [row for row in rows if row["unit"] == "index" and row["value"] not in (None, ".", "")]
        if not rows:
            result.append({"series_id": series, "status": "missing"})
            continue
        newest = rows[-1]
        date = dt.date.fromisoformat(newest["observation_date"])
        targets = {"ytd": dt.date(date.year - 1, 12, 31), "1m": month_offset(date, 1), "3m": month_offset(date, 3)}
        periods = {}
        for name, target in targets.items():
            candidates = [row for row in rows if row["observation_date"] <= target.isoformat()]
            if candidates:
                base = candidates[-1]
                periods[name] = {"requested_base_date": target.isoformat(), "base_date": base["observation_date"],
                    "base_value": float(base["value"]), "price_return_fraction": float(newest["value"]) / float(base["value"]) - 1}
        result.append({"series_id": series, "price_date": newest["observation_date"], "value": float(newest["value"]),
            "unit": "index", "source_id": newest["source_id"], "available_at": newest["available_at"],
            "stale_calendar_days_at_research_as_of": (CUTOFF.date() - date).days,
            "status": "stale_reference_not_current_price", "return_unit": "fraction", "returns": periods,
            "dividend_policy": "Price indices; no dividend reinvestment, not ETF total-return comparisons.",
            "raw_sha256": newest["raw_sha256"]})
    return result


def model_audit():
    v8 = read_json("data/timeseries_v8/multivariate_v8_latest.json")
    v13 = read_json("data/timeseries_v13/vol/vol_latest.json")
    shadow = read_jsonl("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")
    holdouts = read_jsonl("data/timeseries_v13/ledgers/holdout_scorings.jsonl")
    approvals = read_jsonl("data/timeseries_v13/ledgers/approvals.jsonl")
    backfill = read_jsonl("data/timeseries/ledgers/source_backfill_audit.jsonl")
    holdout_summary = []
    for run in holdouts:
        holdout_summary.append({"approval_receipt_id": run.get("approval_receipt_id"),
            "cells": {key: {field: cell.get(field) for field in ["h", "target", "origins", "first_origin", "last_origin", "verdict", "G1_pass", "G2_pass", "G4_pass"]}
                for key, cell in run.get("cells", {}).items()}})
    return {
        "v8": {"snapshot": v8, "n_shadow_forecast_rows": len(shadow),
            "current_freshness_recomputed": "stale at 2026-10-12; saved fresh labels were evaluated in September",
            "origin_integrity_warning": "as_of=2026-09-04 while knowledge_cutoff is 2026-09-12 and operational inputs extend to 2026-09-11. Do not interpret this snapshot as information available at the September 4 forecast origin.",
            "no_sector_probability_conversion": True,
            "shadow_origin_metadata": [{key: row.get(key) for key in ["forecast_id", "origin", "as_of", "knowledge_cutoff", "created_at", "origin_date", "probability_unit", "probability_space"]} for row in shadow]},
        "v13": {"snapshot": v13, "n_approval_receipts": len(approvals), "approval_receipts": approvals,
            "holdout_results": holdout_summary,
            "current_freshness_recomputed": "stale at 2026-10-12; saved fresh was evaluated at 2026-09-14",
            "inference_limit": "Volatility exceedance/touch probabilities measure risk events, not directional stock or sector returns; 63-session cells failed holdout and cannot justify year-end directional certainty."},
        "source_backfill_audits": [{key: row.get(key) for key in ["audit_id", "run_id", "artifact_kind", "knowledge_cutoff", "observed_at", "classification", "added_count", "changed_count", "removed_count", "snapshot_matches_reconstruction", "reconstruction_matches_record"]} for row in backfill],
    }


def scenario_audit():
    scenario = read_json("data/scenarios/nasdaq_latest.json")
    structural = scenario.get("structural_forecast", {})
    dates = structural.get("dates", [])
    year_end_indices = [idx for idx, date in enumerate(dates) if date.startswith("2026-")]
    endpoint = max(year_end_indices) if year_end_indices else None
    paths = {}
    for key, path in structural.get("paths", {}).items():
        values = path.get("values", [])
        paths[key] = {"start": values[0] if values else None,
            "2026_display_endpoint_date": dates[endpoint] if endpoint is not None else None,
            "2026_display_endpoint": values[endpoint] if endpoint is not None else None,
            "conditional_price_return_fraction": values[endpoint] / values[0] - 1 if endpoint is not None and values[0] else None}
    return {"asof": scenario["asof"], "generated_at": scenario["generated_at"], "anchor": scenario["anchor"],
        "revision": scenario["revision"], "snapshot_id": scenario["snapshot_id"],
        "structural_status": structural.get("status"), "path_kind": structural.get("path_kind"),
        "probability_space": structural.get("probability_space"), "paths": paths,
        "year_diagnostics": structural.get("years"), "calibration": structural.get("calibration"),
        "inference_limit": "Scenario-conditional structural shapes with forced endpoint preservation/calibrated historical depth; not calibrated sector-return forecasts, not precise crash-day predictions. Display endpoint is December 29 rather than last trading day."}


def capital_cycle_audit():
    facts = read_json("data/ai_capital_cycle/company_capex_quarterly_latest.json")
    records = facts["records"]
    coverage = read_json("data/ai_capital_cycle/coverage_latest.json")
    selected = []
    for company in sorted({row["company"] for row in records}):
        for metric in sorted({row["metric"] for row in records if row["company"] == company}):
            rows = [row for row in records if row["company"] == company and row["metric"] == metric]
            newest = max(rows, key=lambda row: row["observation_period"])
            selected.append(newest)
    return {"asof": facts["asof"], "generated_at": facts["generated_at"], "status": facts["status"],
        "n_records": len(records), "semantics": facts["semantics"], "latest_as_filed_by_company_metric": selected,
        "coverage": {key: coverage[key] for key in ["asof", "status", "coverage", "coverage_threshold", "reason"]},
        "regime": read_json("data/ai_capital_cycle/ai_regime_latest.json"),
        "source_audit": read_json("data/ai_capital_cycle/d0_source_audit.json"),
        "quarter_alignment_limit": "Rows lack fiscal-period start/duration and explicitly retain standalone or cumulative-YTD values as filed. No quarterly sums/growth or cross-company quarterly capex comparison is computed. Filing vintage/fiscal-year labels must be checked against original statements first.",
        "date_only_available_at_limit": "SEC available_at values contain filing dates without times; earlier-than-cutoff-day rows can be temporally bracketed, but exact intraday availability is not established.",
        "ai_revenue_limit": "Company total capex and cash flow do not establish attributable AI revenue or sector profitability; segment extraction remains pending."}


def public_forecast_projection(content, local_overrides):
    """Reproduce scores from published display-unit metadata, without syncing DB."""
    semantic = content.get("probability_semantics", {})
    unit = semantic.get("display_unit")
    questions = {row["id"]: row for row in content["questions"]}
    forecasts = {row["forecast_id"]: row for rows in content["forecast_history"].values() for row in rows}
    override_status = {row["forecast_id"]: row["status"] for row in local_overrides}
    errors = []
    events = []
    flat = []
    for question, rows in content["resolutions"].items():
        grouped = collections.defaultdict(list)
        for row in rows:
            grouped[row["resolved_date"]].append(row)
        for resolved_date, group in grouped.items():
            observations = []
            for row in group:
                forecast = forecasts.get(row["forecast_id"], {})
                if unit not in ("fraction", "percent"):
                    errors.append({"forecast_id": row["forecast_id"], "reason": "public_display_unit_missing"})
                    continue
                probability = row["probability"] * (0.01 if unit == "percent" else 1.0)
                if not 0 <= probability <= 1:
                    errors.append({"forecast_id": row["forecast_id"], "reason": "public_probability_out_of_bounds"})
                    continue
                brier = (probability - row["outcome"]) ** 2
                if not math.isclose(brier, row["brier"], abs_tol=1e-12):
                    errors.append({"forecast_id": row["forecast_id"], "reason": "public_brier_mismatch"})
                status = override_status.get(row["forecast_id"], forecast.get("research_status"))
                observations.append({"forecast_id": row["forecast_id"], "probability": probability,
                    "outcome": row["outcome"], "brier": brier, "forecast_ts": forecast.get("forecast_ts"),
                    "round": forecast.get("round", 0), "primary_eligible": status != "failed",
                    "effective_research_status": status,
                    "status_provenance": "local_approved_override" if row["forecast_id"] in override_status else "public_forecast_history"})
            ordered = sorted(observations, key=lambda row: (row["forecast_ts"] or "", row["round"]))
            primary = [row for row in ordered if row["primary_eligible"]]
            resolution_end = dt.datetime.combine(dt.date.fromisoformat(resolved_date), dt.time.max)
            def weighted(rows):
                if not rows:
                    return None
                weight_values = []
                for idx, row in enumerate(rows):
                    start = dt.datetime.fromisoformat(row["forecast_ts"])
                    end = dt.datetime.fromisoformat(rows[idx + 1]["forecast_ts"]) if idx + 1 < len(rows) else resolution_end
                    weight_values.append(max(1.0, (end - start).total_seconds()))
                return sum(row["probability"] * weight for row, weight in zip(rows, weight_values)) / sum(weight_values)
            primary_prob = weighted(primary)
            outcome = ordered[0]["outcome"] if ordered else None
            events.append({"question_id": question, "resolved_date": resolved_date,
                "domain": questions.get(question, {}).get("domain"), "n_rows": len(ordered),
                "n_primary_rows": len(primary), "primary_probability_time_weighted": primary_prob,
                "primary_brier_time_weighted": (primary_prob - outcome) ** 2 if primary_prob is not None else None,
                "latest_brier": ordered[-1]["brier"] if ordered else None,
                "rows": ordered})
            flat.extend(ordered)
    primary_rows = [row for row in flat if row["primary_eligible"]]
    independent_primary = mean([row["primary_brier_time_weighted"] for row in events if row["primary_brier_time_weighted"] is not None])
    reported = content["calibration"]
    checks = {
        "all_rows_match": len(flat) == reported["gate_all"]["n_resolved"],
        "primary_rows_match": len(primary_rows) == reported["gate"]["n_resolved"],
        "independent_events_match": len(events) == reported["gate_v2"]["n_events"],
        "all_row_brier_match": math.isclose(mean([row["brier"] for row in flat]), reported["gate_all"]["brier"], abs_tol=1e-12),
        "primary_row_brier_match": math.isclose(mean([row["brier"] for row in primary_rows]), reported["gate"]["brier"], abs_tol=1e-12),
        "independent_time_weighted_brier_match": math.isclose(independent_primary, reported["gate_v2"]["brier"], abs_tol=1e-12),
    }
    return {"evidence_role": "published site read-model, not independently retrieved raw official ledger",
        "display_probability_unit": unit, "unit_metadata_provenance": "public data.json probability_semantics.display_unit; local dashboard.py exports legacy percentage fields directly",
        "canonical_probability_unit": "fraction", "raw_per_record_unit_metadata_available": False,
        "n_forecasts_reported": content["meta"]["n_forecasts"], "n_forecasts_exposed": len(forecasts),
        "n_all_resolution_rows": len(flat), "n_primary_resolution_rows": len(primary_rows),
        "n_independent_events": len(events), "n_excluded_rows": len(flat) - len(primary_rows),
        "all_row_brier_recomputed": mean([row["brier"] for row in flat]),
        "primary_row_brier_recomputed": mean([row["brier"] for row in primary_rows]),
        "independent_event_brier_primary_time_weighted_recomputed": independent_primary,
        "independent_event_brier_latest_recomputed": mean([row["latest_brier"] for row in events]),
        "independent_event_primary_domain": [{"domain": domain, "n_events": len(values), "brier": mean(values)}
            for domain, values in sorted({domain: [row["primary_brier_time_weighted"] for row in events if row["domain"] == domain]
                for domain in {row["domain"] for row in events}}.items())],
        "calibration_reported": reported, "reconciliation_checks": checks, "errors": errors, "events": events,
        "limitations": ["Raw public forecast/resolution append ledgers, approval receipts and input vintages were not separately obtained.",
            "FOMC r2 failed override is evidenced in local override ledger; Adobe r1 failed is explicit in public history.",
            "Scoring time weights replicate local ingest.py using naive timestamps; this does not establish timezone or original-time input eligibility.",
            "Earnings events and macro releases do not increase the two-observation price-direction sample."]}


def public_content_projection(filename, content, local_overrides):
    if filename == "data.json":
        return {"meta": content["meta"], "generated_before_research_cutoff": timely(content["meta"]["generated"]),
            "forecast_calibration": public_forecast_projection(content, local_overrides),
            "timeseries_v8": content["timeseries"], "timeseries_v13_vol": content["timeseries_v13_vol"],
            "market_mood": content.get("market_mood"),
            "scenario_metadata": {key: content["scenario"].get(key) for key in ["asof", "generated_at", "anchor", "revision", "snapshot_id"]},
            "v8_origin_warning": "Public V8 as_of=2026-10-02 with knowledge_cutoff=2026-10-10: observed after origin; not an October 2 tradable forecast or new October 12 signal.",
        "provenance_limit": "Global build generated timestamp is a reported availability upper bound; HTTP capture after research cutoff cannot independently prove deployed contents at cutoff. Public source snapshots are research inputs only and do not replace the local official ledgers."}
    if filename == "statistics.json":
        statistics = content["data"]["statistics_lab"]
        charts = []
        for chart in statistics.get("charts", []):
            latest = []
            for series in chart.get("series", []):
                points = series.get("points", [])
                if points:
                    latest.append({"label": series.get("label"), "era": series.get("era"), "latest": points[-1]})
            for series in latest:
                point = series["latest"]
                if series["era"] == "current" and isinstance(point.get("period"), int):
                    start = dt.date.fromisoformat(statistics["cycle_alignment"]["current_start"])
                    total = start.year * 12 + start.month - 1 + point["period"]
                    year, month = divmod(total, 12)
                    point["calendar_bucket_inferred_from_explicit_cycle_alignment"] = f"{year:04d}-{month + 1:02d}"
                    point["bucket_caveat"] = "A chart alignment bucket; not an exact daily close or release time. Quarterly series are bucketed at their period start."
            charts.append({key: chart.get(key) for key in ["id", "title", "unit", "conclusion", "caveat", "source_ids", "metric_source_ids"]} | {"series_latest": latest})
        return {"metadata": {key: statistics.get(key) for key in ["status", "as_of", "knowledge_cutoff", "generated_at", "observation_through", "probability_space", "model_use", "official_forecast_input", "vintage_warning"]},
            "generated_before_research_cutoff": timely(statistics.get("generated_at")), "sources": statistics.get("sources"),
            "numeric_source_policy": statistics.get("numeric_source_policy"), "charts": charts,
            "input_provenance_limit": "Published chart aggregates with per-series units/dates; latest remote raw receipts and normalized source revisions are not available in the local September store."}
    data = content["data"]
    scenario = data["scenario_v5_2"]
    liquidity = data["liquidity"]
    return {"semantic_reference": content.get("semantic_reference"),
        "scenario_v5_2": {key: scenario.get(key) for key in ["status", "as_of", "banner", "governance", "runtime_gate", "anchor", "weight_spaces", "horizon_windows", "distribution", "first_touch_distribution", "model_content_sha256"]},
        "liquidity": {key: liquidity.get(key) for key in ["asof", "generated_at", "status", "probability_space", "zone", "zone_metric", "lead_lag", "real_m2", "semantics", "warning"]},
        "liquidity_latest_series": {key: values[-1] if values else None for key, values in liquidity.get("series", {}).items()},
        "ai_regime": data.get("ai_regime"),
        "generated_before_research_cutoff": timely(liquidity.get("generated_at")) and timely(scenario.get("as_of")),
        "inference_limit": "Candidate not official/champion; event observations=1 <60, walk-forward not approved and human promotion not issued. Conditional weights are not sector-rise probabilities."}


def public_site_audit(offline, local_overrides):
    local = read_json("_site/data.json")
    output = {"local": {"path": "_site/data.json", "meta": local["meta"],
        "calibration_gate": local["calibration"].get("gate"), "calibration_gate_v2": local["calibration"].get("gate_v2"),
        "comparison_with_db": "Local static site generated 2026-09-09; its forecast/resolution counts and calibration differ from current DB. Local static file must not be represented as current deployed content."}, "remote": []}
    snapshot_directory = OUT.parent / "public_snapshot"
    manifest_path = snapshot_directory / "snapshot_manifest.json"
    prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = dict(prior_manifest)
    for url in PUBLIC_URLS:
        filename = url.rsplit("/", 1)[-1]
        snapshot_path = snapshot_directory / filename
        try:
            if offline:
                capture = prior_manifest[url]
                snapshot_path = ROOT / capture["snapshot_path"]
                payload = snapshot_path.read_bytes()
                if hashlib.sha256(payload).hexdigest() != capture["response_sha256"]:
                    raise ValueError("stored_public_snapshot_hash_mismatch")
                http_status = capture["http_status"]
                fetched_at = capture["fetched_at"]
            else:
                request = urllib.request.Request(url, headers={"User-Agent": "AI-Investing-ReadOnly-ResearchAudit/1.0"}, method="GET")
                with urllib.request.urlopen(request, timeout=12) as response:
                    payload = response.read(24 * 1024 * 1024 + 1)
                    http_status = response.status
                fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
                if len(payload) > 24 * 1024 * 1024:
                    raise ValueError("response_exceeds_24MiB")
                snapshot_directory.mkdir(exist_ok=True)
                if snapshot_path.exists() and snapshot_path.read_bytes() != payload:
                    snapshot_path = snapshot_directory / (filename.removesuffix(".json") + "_" + hashlib.sha256(payload).hexdigest()[:12] + ".json")
                if not snapshot_path.exists():
                    snapshot_path.write_bytes(payload)
            content = json.loads(payload.decode("utf-8-sig"))
            projection = public_content_projection(filename, content, local_overrides)
            capture = {"url": url, "status": "offline_snapshot_replay" if offline else "retrieved", "http_status": http_status,
                "response_sha256": hashlib.sha256(payload).hexdigest(), "response_bytes": len(payload),
                "snapshot_path": str(snapshot_path.relative_to(ROOT)).replace("\\", "/"), "deployed_content_verified": True,
                "fetched_at": fetched_at, "projection": projection,
                "research_cutoff_eligible_by_reported_generated_at": projection.get("generated_before_research_cutoff", False),
                "evidence_role": "Public read-model with reported generated timestamps; source raw append ledgers are not independently obtained."}
            output["remote"].append(capture)
            manifest[url] = {key: capture[key] for key in ["url", "http_status", "response_sha256", "response_bytes", "snapshot_path", "fetched_at"]}
        except Exception as error:
            output["remote"].append({"url": url, "status": "unavailable", "error": type(error).__name__ + ": " + str(error),
                "deployed_content_verified": False, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    if not offline:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    paths = [ROOT / relative for relative in READ_FILES]
    paths += list((ROOT / "forecasts").glob("**/*.md"))
    paths += list((ROOT / "data/statistics/official_store/raw").glob("**/*.bin"))
    for relative in ["db/index.db", "dualdb/db/dualdb.sqlite"]:
        for suffix in ["-wal", "-shm"]:
            sidecar = ROOT / (relative + suffix)
            if sidecar.exists():
                paths.append(sidecar)
    before = fingerprint(paths)
    index = database("db/index.db")
    twin = database("dualdb/db/dualdb.sqlite")
    try:
        index_inventory = inventory(index)
        dual_inventory = inventory(twin)
        forecasts = forecast_audit(index)
        dual_series = query(twin, "SELECT series,COUNT(*) AS n,MIN(date) AS first_date,MAX(date) AS latest_date,MAX(ingested_at) AS latest_ingested_at FROM price_daily GROUP BY series ORDER BY series")
        dual_macro = {table: query(twin, "SELECT " + field + ",COUNT(*) AS n,MIN(date) AS first_date,MAX(date) AS latest_date FROM " + table + " GROUP BY " + field + " ORDER BY " + field)
                      for table, field in [("macro_daily", "series_id"), ("macro_monthly", "series_id"), ("valuation_monthly", "scope")]}
        metadata = query(index, "SELECT * FROM db_meta ORDER BY key")
        sql_views = query(index, "SELECT name,sql FROM sqlite_master WHERE type='view' AND (name LIKE '%brier%' OR name LIKE '%gate%' OR name LIKE '%benchmark%') ORDER BY name")
    finally:
        index.close()
        twin.close()
    stats, series, _ = official_statistics_audit()
    output = {"schema_version": 1, "research_as_of": AS_OF, "canonical_probability_unit": "fraction",
        "execution_policy": {"sqlite_mode": "ro", "pragma_query_only": True, "application_modules_imported": False,
            "allowed_external_calls": "read-only GETs to public static research-site JSON only", "written_output": str(OUT),
            "source_inputs": sorted(before), "sql_read_scope": "SQLite table inventories and explicitly listed SELECT statements in this script; no sync/collect/model/official append commands"},
        "index_db": {"inventory": index_inventory, "metadata": metadata},
        "forecast_calibration": forecasts,
        "dualdb": {"inventory": dual_inventory, "price_series": dual_series, "macro_and_valuation": dual_macro,
            "point_in_time_limit": "Tables preserve observation date and ingested_at but have no available_at/native vintage chain. Current-vintage historical values are usable for descriptive comparison, not proven original-origin backtesting.",
            "coverage_limit": "No complete 11-sector ETF panel or current cross-sector earnings/valuation table. fundamentals_annual and sentiment_weekly empty; 11-sector ranking requires separately sourced external inputs."},
        "official_statistics": stats, "stale_market_facts": stale_market_facts(series),
        "models": model_audit(), "scenario": scenario_audit(), "ai_capital_cycle": capital_cycle_audit(),
        "site": public_site_audit(args.offline, forecasts["research_status_overrides"]), "sql_view_definitions": sql_views,
    }
    after = fingerprint(paths)
    changes = {path: {"before": before.get(path), "after": after.get(path)} for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path)}
    output["source_integrity"] = {"n_original_files_hashed": len(before), "sha256_before": before, "sha256_after": after,
        "unchanged": before == after, "changes": changes}
    if changes:
        raise RuntimeError("Original input hash changed; audit output refused: " + json.dumps(changes))
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "original_files_unchanged": True, "n_originals": len(before),
        "n_resolutions": forecasts["n_resolved_ledger_rows"], "n_events": forecasts["n_independent_events"],
        "raw_hash_failures": len(stats["raw_hash_failures"]), "revision_violations": len(stats["revision_and_cutoff_violations"]),
        "invalid_forecast_rows": len(forecasts["invalid_forecast_rows"]), "brier_mismatches": len(forecasts["brier_mismatches"])}, ensure_ascii=True))


if __name__ == "__main__":
    main()
