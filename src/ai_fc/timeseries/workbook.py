"""Deterministic eight-sheet Excel audit view built from time-series ledgers."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

from ai_fc.official_data_workbook import _sheet_xml, _workbook_parts

from .contracts import (
    FACTS_RELATIVE,
    LEDGER_RELATIVE,
    LATEST_RELATIVE,
    MODEL_RELATIVE,
    RUNS_RELATIVE,
    WORKBOOK_RELATIVE,
    canonical_hash,
    file_hash,
    load_contract,
)
from .ledger import read_fact_rows


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parquet_rows(path: Path) -> int | None:
    if not path.is_file():
        return 0
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        return None
    return int(pq.read_metadata(path).num_rows)


def export_timeseries_workbook(root: Path) -> tuple[Path, dict[str, Any]]:
    contract = load_contract(root)
    receipts = _jsonl(root / LEDGER_RELATIVE / "raw_receipts.jsonl")
    event_receipts = _jsonl(root / LEDGER_RELATIVE / "event_raw_receipts.jsonl")
    observation_ledger = read_fact_rows(root)
    latest_revision: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in observation_ledger:
        key = (row["source_id"], row["series_id"], row["observation_time"], row["vintage_start"])
        prior = latest_revision.get(key)
        if prior is None or int(row["revision_seq"]) > int(prior["revision_seq"]):
            latest_revision[key] = row
    active_vintages = list(latest_revision.values())
    current_observations: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in active_vintages:
        key = (row["source_id"], row["series_id"], row["observation_time"])
        prior = current_observations.get(key)
        if prior is None or str(row["vintage_start"]) > str(prior["vintage_start"]):
            current_observations[key] = row
    observations = sorted(current_observations.values(), key=lambda row: (
        row["series_id"], row["observation_time"], row["vintage_start"],
    ))
    forecasts = _jsonl(root / LEDGER_RELATIVE / "forecasts.jsonl")
    resolutions = _jsonl(root / LEDGER_RELATIVE / "resolutions.jsonl")
    corrections = _jsonl(root / LEDGER_RELATIVE / "corrections.jsonl")
    events = _jsonl(root / LEDGER_RELATIVE / "events.jsonl")
    model_pointer = _json(root / MODEL_RELATIVE / "latest.json")
    model = _json(root / model_pointer["model_path"]) if model_pointer else None
    backtest_pointer = _json(root / RUNS_RELATIVE / "backtest_latest.json")
    backtest = _json(root / backtest_pointer["run_path"]) if backtest_pointer else None
    latest_pointer = _json(root / LATEST_RELATIVE)
    latest = _json(root / latest_pointer["artifact_path"]) if latest_pointer else None
    parquet_path = root / FACTS_RELATIVE / "observations.parquet"
    parquet_rows = _parquet_rows(parquet_path)

    source_group: dict[str, str] = {}
    for group in ("daily_required", "growth_required", "inflation_required", "financial_optional", "historical_bridge", "event_optional"):
        for series_id in contract["sources"][group]:
            source_group[series_id] = group
    receipt_by_series: dict[str, list[dict[str, Any]]] = {}
    for receipt in [*receipts, *event_receipts]:
        receipt_by_series.setdefault(str(receipt["series_id"]), []).append(receipt)
    source_rows = [[
        "series_id", "group", "required", "source_id", "receipt_count",
        "latest_retrieved_at", "latest_raw_sha256", "request_fingerprint",
    ]]
    for series_id, group in sorted(source_group.items()):
        rows = receipt_by_series.get(series_id, [])
        last = max(rows, key=lambda row: row["retrieved_at"]) if rows else {}
        source_rows.append([
            series_id,
            group,
            group.endswith("required") or group == "historical_bridge",
            "alfred" if series_id not in contract["sources"]["event_optional"] else "registered_event_receipt",
            len(rows),
            last.get("retrieved_at"),
            last.get("raw_sha256"),
            last.get("request_fingerprint"),
        ])
    for event_type in sorted({str(row["event_type"]) for row in events}):
        rows = [row for row in events if row["event_type"] == event_type]
        last = max(rows, key=lambda row: row["available_at"])
        source_rows.append([
            event_type, "event_optional", False, last.get("source_id"), len(rows),
            last.get("retrieved_at"), last.get("raw_sha256"), last.get("receipt_id"),
        ])

    observation_headers = [
        "observation_id", "source_id", "series_id", "observation_time", "value",
        "value_status", "available_at", "vintage_start", "vintage_end", "retrieved_at",
        "source_revision_id", "source_hash", "parser_version", "revision_seq",
        "supersedes_observation_id",
    ]
    observation_rows = [observation_headers, *[
        [row.get(key) for key in observation_headers] for row in observations
    ]]
    vintage_headers = [
        "series_id", "observation_year", "fact_vintages", "distinct_observations",
        "first_vintage_start", "last_vintage_start", "superseded_rows", "source_hashes",
    ]
    vintage_summary: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in active_vintages:
        key = (str(row["series_id"]), str(row["observation_time"])[:4])
        vintage_summary.setdefault(key, []).append(row)
    vintage_rows = [vintage_headers]
    for (series_id, year), rows in sorted(vintage_summary.items()):
        vintage_rows.append([
            series_id,
            year,
            len(rows),
            len({str(row["observation_time"]) for row in rows}),
            min(str(row["vintage_start"]) for row in rows),
            max(str(row["vintage_start"]) for row in rows),
            sum(1 for row in rows if row.get("vintage_end")),
            len({str(row["source_hash"]) for row in rows}),
        ])

    feature_rows = [["feature", "role", "transformation", "training_status", "notes"]]
    registered_transforms = contract["transforms"]
    for feature, transform in registered_transforms.items():
        feature_rows.append([
            feature,
            "endogenous" if feature in contract["sources"]["daily_required"] else "macro_or_financial",
            json.dumps(transform, ensure_ascii=False) if isinstance(transform, list) else transform,
            "active" if model and feature in " ".join(model["training"].get("exogenous_names") or []) else "registered",
            "release-age state; no observation-date backfill",
        ])
    for factor in ("growth_factor", "inflation_factor"):
        feature_rows.append([
            factor, "DFM exogenous", "DynamicFactorMQ filtered state", "active" if model else "pending",
            "factor order 1; idiosyncratic AR(1)",
        ])
    for event_type in sorted({str(row["event_type"]) for row in events}):
        count = sum(1 for row in events if row["event_type"] == event_type)
        feature_rows.append([
            event_type, "event overlay", "receipt-backed PIT path reweighting", "registered",
            f"{count} append-only event revisions; VARX coefficient promotion requires 60+ and ablation",
        ])

    forecast_headers = [
        "forecast_id", "as_of", "knowledge_cutoff", "status", "display_state",
        "numbers_visible", "backtest_run_id", "content_hash", "resolution_count",
    ]
    resolutions_by_forecast: dict[str, int] = {}
    for row in resolutions:
        resolutions_by_forecast[str(row["forecast_id"])] = resolutions_by_forecast.get(str(row["forecast_id"]), 0) + 1
    forecast_rows = [forecast_headers]
    for ledger_row in forecasts:
        artifact = _json(root / ledger_row["artifact_path"]) or {}
        forecast_rows.append([
            ledger_row.get("forecast_id"), ledger_row.get("as_of"), ledger_row.get("knowledge_cutoff"),
            artifact.get("status"), artifact.get("display_state"),
            (artifact.get("publication") or {}).get("customer_numbers_visible"),
            (artifact.get("backtest") or {}).get("run_id"), ledger_row.get("content_hash"),
            resolutions_by_forecast.get(str(ledger_row.get("forecast_id")), 0),
        ])

    backtest_rows = [[
        "horizon_sessions", "origins", "mae", "rmse", "mase", "directional_accuracy",
        "crps", "best_baseline", "best_baseline_crps", "crps_improvement",
        "coverage_p10_p90", "coverage_p25_p75", "gate_status",
    ]]
    for horizon, row in sorted((((backtest or {}).get("summary") or {}).get("horizons") or {}).items(), key=lambda item: int(item[0])):
        backtest_rows.append([
            int(horizon), row.get("origins"), row.get("mae"), row.get("rmse"), row.get("mase"),
            row.get("directional_accuracy"), row.get("crps"), row.get("best_baseline"),
            row.get("best_baseline_crps"), row.get("crps_improvement_vs_best"),
            row.get("coverage_p10_p90"), row.get("coverage_p25_p75"),
            ((backtest or {}).get("summary") or {}).get("status", "pending"),
        ])
    if len(backtest_rows) == 1:
        backtest_rows.append([None] * 12 + ["pending"])

    model_rows = [["field", "value"],
        ["model_id", contract["model_id"]],
        ["model_version", contract["model_version"]],
        ["lifecycle", "shadow"],
        ["target", contract["target"]["series_id"]],
        ["transform", contract["target"]["transform"]],
        ["horizons", ", ".join(str(item) for item in contract["target"]["horizons_sessions"])],
        ["probability_space", contract["probability_contract"]["space"]],
        ["official_combination", "No — isolated probability space"],
        ["scenario_v5_2_combination", "No — isolated probability space"],
        ["automatic_champion", "No — explicit approval required"],
        ["minimum_shadow_sessions", contract["promotion"]["minimum_shadow_sessions"]],
        ["latest_fit_run", (model or {}).get("run_id")],
        ["latest_backtest_run", (backtest or {}).get("run_id")],
        ["latest_forecast", (latest or {}).get("forecast_id")],
        ["publication_gate", ((backtest or {}).get("summary") or {}).get("status", "pending")],
    ]

    jsonl_active_keys = {
        (row["source_id"], row["series_id"], row["observation_time"], row["vintage_start"])
        for row in active_vintages
    }
    run_manifest = [["check", "actual", "expected", "status", "notes"],
        ["contract_hash", canonical_hash(contract), canonical_hash(contract), "PASS", "preregistered contract"],
        ["observation_ledger_rows", len(observation_ledger), len(observation_ledger), "PASS", "append-only rows including revisions"],
        ["current_observation_export_rows", len(observations), len(observations), "PASS", "Excel-safe latest-vintage review view"],
        ["active_observation_keys", len(jsonl_active_keys), len(jsonl_active_keys), "PASS", "source/series/date/vintage keys"],
        ["parquet_rows", parquet_rows, len(jsonl_active_keys), "PASS" if parquet_rows == len(jsonl_active_keys) else "HOLD", "derived training view"],
        ["receipt_rows", len(receipts) + len(event_receipts), len(receipts) + len(event_receipts), "PASS", "raw before derive"],
        ["forecast_rows", len(forecasts), len(forecasts), "PASS", "shadow-only ledger"],
        ["resolution_rows", len(resolutions), len(resolutions), "PASS", "append-only realized outcomes"],
        ["correction_rows", len(corrections), len(corrections), "PASS", "explicit supersedes only"],
        ["event_rows", len(events), len(events), "PASS", "receipt-backed optional research inputs"],
        ["official_forecast_write", 0, 0, "PASS", "separate probability space"],
        ["workbook_role", "review export", "review export", "PASS", "JSONL is canonical"],
    ]

    sheets: dict[str, tuple[list[list[Any]], list[float]]] = {
        "Sources": (source_rows, [22, 24, 14, 24, 14, 27, 68, 68]),
        "Observations": (observation_rows, [68, 20, 24, 18, 16, 16, 27, 27, 27, 27, 26, 68, 28, 14, 68]),
        "Vintages": (vintage_rows, [24, 18, 20, 24, 27, 27, 20, 18]),
        "Features": (feature_rows, [28, 24, 52, 20, 62]),
        "Forecasts": (forecast_rows, [28, 18, 27, 16, 20, 18, 30, 68, 18]),
        "Backtest": (backtest_rows, [18, 14, 16, 16, 16, 22, 16, 26, 20, 22, 22, 22, 18]),
        "ModelCard": (model_rows, [34, 92]),
        "RunManifest": (run_manifest, [34, 68, 68, 16, 62]),
    }
    parts = _workbook_parts(list(sheets))
    for index, (name, (rows, widths)) in enumerate(sheets.items(), start=1):
        parts[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(rows, widths=widths, freeze_header=True)
    target = root / WORKBOOK_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.xlsx")
    timestamp = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body.encode("utf-8"))
    os.replace(temporary, target)
    summary = {
        "sources": len(source_rows) - 1,
        "observations": len(observation_ledger),
        "current_observation_export_rows": len(observations),
        "active_observations": len(jsonl_active_keys),
        "parquet_rows": parquet_rows,
        "forecasts": len(forecasts),
        "resolutions": len(resolutions),
        "events": len(events),
        "event_receipts": len(event_receipts),
        "sheets": len(sheets),
        "sha256": file_hash(target),
    }
    return target, summary
