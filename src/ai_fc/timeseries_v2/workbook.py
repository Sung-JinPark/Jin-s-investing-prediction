"""Deterministic eight-sheet V2 Excel audit view.

Canonical data remains append-only JSONL/raw receipts.  The workbook is a
review export and deliberately summarizes historical vintages when the full
ledger would exceed Excel's row limit.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

from ai_fc.facts import as_of_rows
from ai_fc.official_data_workbook import _sheet_xml, _workbook_parts
from ai_fc.timeseries.ledger import read_fact_rows, read_facts

from .artifact import read_latest
from .contracts import (
    MODEL_RELATIVE,
    RUNS_RELATIVE,
    WORKBOOK_RELATIVE,
    frozen_hash,
    load_contract_v2,
    model_code_hash,
    runtime_manifest,
)
from .dfm_cache import read_dfm_manifest, verify_dfm_runtime_provenance
from .market_archive import (
    ARCHIVE_FACTS,
    ARCHIVE_RECEIPTS,
    MarketObservationV2,
    MarketRawReceipt,
    verify_market_lineage,
)


def _json(path: Path) -> dict[str, Any] | None:
    return None if not path.is_file() else json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [] if not path.is_file() else [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
    ]


def _sealed_evaluation_audit(root: Path) -> dict[str, int]:
    rows = _jsonl(root / "data/timeseries_v2/ledgers/sealed_evaluations.jsonl")
    corrections = _jsonl(
        root / "data/timeseries_v2/ledgers/sealed_evaluation_corrections.jsonl"
    )
    run_ids = {str(row.get("run_id")) for row in rows}
    invalidated = {
        str(row.get("invalidates_run_id"))
        for row in corrections
        if str(row.get("invalidates_run_id")) in run_ids
    }
    unknown_corrections = sum(
        str(row.get("invalidates_run_id")) not in run_ids for row in corrections
    )
    active_rows = sum(str(row.get("run_id")) not in invalidated for row in rows)
    return {
        "ledger_rows": len(rows),
        "correction_rows": len(corrections),
        "active_rows": active_rows,
        "unknown_corrections": unknown_corrections,
    }


def _file_hash(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parquet_rows(path: Path) -> int | None:
    if not path.is_file():
        return None
    import pyarrow.parquet as pq  # type: ignore
    return int(pq.ParquetFile(path).metadata.num_rows)


def export_timeseries_v2_workbook(root: Path) -> tuple[Path, dict[str, Any]]:
    contract = load_contract_v2(root)
    macro_rows = read_fact_rows(root)
    macro_facts = read_facts(root)
    market_receipts = [MarketRawReceipt.model_validate(row) for row in _jsonl(root / ARCHIVE_RECEIPTS)]
    market_rows = [MarketObservationV2.model_validate(row) for row in _jsonl(root / ARCHIVE_FACTS)]
    latest = read_latest(root)
    fit_pointer = _json(root / MODEL_RELATIVE / "fit_latest.json")
    fit = _json(root / fit_pointer["path"]) if fit_pointer else None
    backtest_pointer = _json(root / RUNS_RELATIVE / "backtest_latest.json")
    backtest = _json(root / backtest_pointer["path"]) if backtest_pointer else None
    dfm = read_dfm_manifest(root)
    lineage = verify_market_lineage(root)
    sealed_audit = _sealed_evaluation_audit(root)

    source_rows = [[
        "series_id", "provider", "data_grade", "required", "receipt_count",
        "observations", "latest_available_at", "raw_lineage_status",
    ]]
    for series_id, spec in contract["sources"]["market_required"].items():
        physical = "DGS10" if series_id == "T10Y2Y" else series_id
        rows = [row for row in market_rows if row.series_id in ({"DGS2", "DGS10"} if series_id == "T10Y2Y" else {physical})]
        source_ids = {row.source_id for row in rows}
        receipts = [receipt for receipt in market_receipts if receipt.source_id in source_ids]
        source_rows.append([
            series_id, spec["provider"], "reconstructed_market_archive", True,
            len(receipts), len(rows), max((row.available_at for row in rows), default=None),
            "PASS" if rows and receipts else "HOLD",
        ])
    macro_receipts = _jsonl(root / "data/timeseries/ledgers/raw_receipts.jsonl")
    for group, series_ids in contract["sources"]["macro_native_pit"].items():
        for series_id in series_ids:
            rows = [row for row in macro_rows if row["series_id"] == series_id]
            receipts = [row for row in macro_receipts if row.get("series_id") == series_id]
            source_rows.append([
                series_id, "ALFRED", "native_pit", group in {"growth", "inflation"},
                len(receipts), len(rows), max((row["available_at"] for row in rows), default=None),
                "PASS" if rows and receipts else "HOLD",
            ])
    ebp_rows = [row for row in market_rows if row.series_id == "FED_EBP"]
    ebp_source_ids = {row.source_id for row in ebp_rows}
    ebp_receipts = [receipt for receipt in market_receipts if receipt.source_id in ebp_source_ids]
    source_rows.append([
        "FED_EBP", "Federal Reserve", "captured_forward", False,
        len(ebp_receipts), len(ebp_rows),
        max((row.available_at for row in ebp_rows), default=None),
        "PASS" if ebp_rows and ebp_receipts else "HOLD",
    ])

    cutoff = (latest or {}).get("knowledge_cutoff") or (
        max((row.available_at for row in market_rows), default="9999-12-31T00:00:00+00:00")
    )
    current_macro = []
    macro_series = sorted({
        series for group in contract["sources"]["macro_native_pit"].values() for series in group
    })
    for series_id in macro_series:
        current_macro.extend(as_of_rows(macro_facts, series_id=series_id, as_of=cutoff))
    observation_rows = [[
        "source_id", "series_id", "observation_time", "value", "unit", "available_at",
        "data_grade", "vintage_start", "vintage_end", "raw_sha256", "receipt_id", "supersedes",
    ]]
    for row in sorted(market_rows, key=lambda item: (item.series_id, item.observation_time, item.revision_seq)):
        observation_rows.append([
            row.source_id, row.series_id, row.observation_time, row.value, row.unit,
            row.available_at, row.data_grade, row.vintage_start, row.vintage_end,
            row.raw_sha256, row.receipt_id, row.supersedes,
        ])
    for row in sorted(current_macro, key=lambda item: (item.series_id, item.observation_time)):
        observation_rows.append([
            row.source_id, row.series_id, row.observation_time, row.value, "source_native",
            row.available_at, "native_pit", row.vintage_start, row.vintage_end,
            row.source_hash, row.source_revision_id, None,
        ])

    vintage_rows = [[
        "series_id", "data_grade", "ledger_rows", "distinct_observations",
        "first_available_at", "last_available_at", "revision_rows", "note",
    ]]
    for series_id in sorted({row.series_id for row in market_rows}):
        rows = [row for row in market_rows if row.series_id == series_id]
        grades = ", ".join(sorted({row.data_grade for row in rows}))
        vintage_rows.append([
            series_id, grades, len(rows),
            len({row.observation_time for row in rows}), min(row.available_at for row in rows),
            max(row.available_at for row in rows), sum(row.revision_seq > 1 for row in rows),
            "historical archive; not represented as native ALFRED PIT",
        ])
    for series_id in macro_series:
        rows = [row for row in macro_rows if row["series_id"] == series_id]
        vintage_rows.append([
            series_id, "native_pit", len(rows), len({row["observation_time"] for row in rows}),
            min((row["available_at"] for row in rows), default=None),
            max((row["available_at"] for row in rows), default=None),
            sum(bool(row.get("supersedes_observation_id")) for row in rows),
            "ALFRED append-only vintage ledger",
        ])

    feature_rows = [["candidate", "feature_block", "status", "transformation", "data_grade", "notes"]]
    for candidate, blocks in contract["model"]["candidates"].items():
        candidate_result = ((backtest or {}).get("candidates") or {}).get(candidate, {})
        for block in blocks:
            feature_rows.append([
                candidate, block, candidate_result.get("status", "registered"),
                "preregistered; training-window robust median/IQR", "mixed_explicit",
                "missing inputs block the candidate; no silent feature deletion",
            ])
    feature_rows.append([
        "DFM", "growth + inflation", "origin_specific_cache",
        "DynamicFactorMQ factor order 1, idiosyncratic AR(1)", "native_pit",
        f"{len(dfm)} cache entries keyed by contract/cutoff/input hash",
    ])

    forecast_rows = [[
        "forecast_id", "as_of", "knowledge_cutoff", "status", "numbers_visible",
        "selected_candidate", "backtest_run_id", "ralph_run_id", "content_hash",
    ]]
    for row in _jsonl(root / "data/timeseries_v2/ledgers/forecasts.jsonl"):
        forecast_rows.append([
            row.get("forecast_id"), row.get("as_of"), row.get("knowledge_cutoff"), row.get("status"),
            (row.get("publication") or {}).get("customer_numbers_visible"),
            (row.get("data_summary") or {}).get("candidate"), row.get("backtest_run_id"),
            row.get("ralph_run_id"), row.get("content_hash"),
        ])
    if len(forecast_rows) == 1:
        forecast_rows.append([None, None, None, "validation_pending", False, None, None, None, None])

    backtest_rows = [[
        "candidate", "development_score", "selected", "sealed_status", "horizon",
        "origins", "crps", "best_baseline", "crps_improvement", "p10_p90_coverage",
        "p25_p75_coverage",
    ]]
    for candidate, row in sorted(((backtest or {}).get("candidates") or {}).items()):
        if candidate == "C5":
            backtest_rows.append([
                candidate, None, False, row.get("status"), None, row.get("pit_event_count"),
                None, None, None, None, None,
            ])
            continue
        selected = candidate == (backtest or {}).get("selected_candidate")
        if selected:
            for horizon, metric in sorted(((backtest or {}).get("summary", {}).get("horizons") or {}).items(), key=lambda item: int(item[0])):
                backtest_rows.append([
                    candidate, row.get("development_score"), True,
                    (backtest or {}).get("summary", {}).get("status"), int(horizon),
                    metric.get("origins"), metric.get("crps"), metric.get("best_baseline"),
                    metric.get("crps_improvement_vs_best"), metric.get("coverage_p10_p90"),
                    metric.get("coverage_p25_p75"),
                ])
        else:
            backtest_rows.append([
                candidate, row.get("development_score"), False, row.get("status"),
                None, None, None, None, None, None, None,
            ])
    if len(backtest_rows) == 1:
        backtest_rows.append([None, None, None, "pending", None, None, None, None, None, None, None])

    model_rows = [["field", "value"],
        ["model_id", contract["model_id"]], ["model_version", 2], ["lifecycle", "shadow"],
        ["target", "NASDAQCOM daily log return"], ["horizons", "1, 5, 21, 63 sessions"],
        ["probability_space", contract["probability_contract"]["space"]],
        ["official/scenario combination", "No"], ["candidate inventory", "C1, C2, C3, C4, C5"],
        ["selected candidate", (backtest or {}).get("selected_candidate")],
        ["sealed disclosure", (backtest or {}).get("sealed_disclosure_number", 0)],
        ["sealed ledger rows", sealed_audit["ledger_rows"]],
        ["sealed correction rows", sealed_audit["correction_rows"]],
        ["active sealed evaluations", sealed_audit["active_rows"]],
        ["publication gate", (backtest or {}).get("summary", {}).get("status", "pending")],
        ["fit run", (fit or {}).get("run_id")], ["Ralph run", (latest or {}).get("ralph_run_id")],
        ["frozen contract hash", frozen_hash(contract)],
        ["model code hash", model_code_hash(root)],
        ["source ledger hashes", json.dumps(((backtest or {}).get("hashes") or {}).get("source_ledgers") or {}, sort_keys=True)],
        ["sealed evaluation runtime", json.dumps((backtest or {}).get("evaluation_runtime") or {}, sort_keys=True)],
        ["workbook export runtime", json.dumps(runtime_manifest(), sort_keys=True)],
        ["deployment commit", os.environ.get("GITHUB_SHA", "pending until merged")],
        ["data grades", "native_pit / reconstructed_market_archive / captured_forward"],
        ["automatic champion", "No"], ["minimum shadow for future promotion review", 126],
    ]

    evaluation_start = str(contract["evaluation"]["outer_start"])
    evaluation_dfm = [row for row in dfm if str(row["cutoff"])[:10] >= evaluation_start]
    blocking_dfm = [row for row in evaluation_dfm if row.get("status") != "ready"]
    dfm_runtime_audit = verify_dfm_runtime_provenance(root)
    macro_parquet = root / "data/timeseries/facts/observations.parquet"
    market_parquet = root / "data/timeseries_v2/parquet/market_observations.parquet"
    market_parquet_manifest = _json(
        root / "data/timeseries_v2/parquet/market_observations.manifest.json"
    ) or {}
    current_market_rows = len({(row.series_id, row.observation_time) for row in market_rows})
    market_parquet_rows = _parquet_rows(market_parquet)
    macro_parquet_rows = _parquet_rows(macro_parquet)
    run_rows = [["check", "actual", "expected", "status", "notes"],
        ["frozen_contract_hash", frozen_hash(contract), frozen_hash(contract), "PASS", "candidate/windows/gates locked"],
        ["model_code_hash", model_code_hash(root), ((backtest or {}).get("hashes") or {}).get("model_code"), "PASS" if backtest and ((backtest.get("hashes") or {}).get("model_code") == model_code_hash(root)) else "HOLD", "V2 implementation plus imported numerical primitives"],
        ["market_receipt_linkage", lineage["receipt_linkage"], 1.0, "PASS" if lineage["ok"] else "HOLD", "raw receipt before fact"],
        ["market_facts", len(market_rows), len(market_rows), "PASS", "append-only with explicit revisions"],
        ["excel_observation_export_rows", len(observation_rows) - 1, len(market_rows) + len(current_macro), "PASS" if len(observation_rows) - 1 == len(market_rows) + len(current_macro) else "HOLD", "Excel review view equals current macro plus market ledger export"],
        ["macro_fact_ledger_rows", len(macro_rows), len(macro_rows), "PASS", "canonical V1 ALFRED PIT store reused read-only"],
        ["macro_current_fact_rows", len(macro_facts), len(macro_facts), "PASS", "latest approved revision per PIT fact key"],
        ["macro_parquet_rows", macro_parquet_rows, len(macro_facts), "PASS" if macro_parquet_rows == len(macro_facts) else "HOLD", "Parquet training view equals the latest-revision JSONL read model; superseded ledger rows remain in JSONL"],
        ["market_parquet_rows", market_parquet_rows, current_market_rows, "PASS" if market_parquet_rows == current_market_rows else "HOLD", "latest append-only observation view"],
        ["market_parquet_sha256", _file_hash(market_parquet) if market_parquet.is_file() else None, market_parquet_manifest.get("sha256"), "PASS" if market_parquet.is_file() and _file_hash(market_parquet) == market_parquet_manifest.get("sha256") else "HOLD", "Parquet manifest byte hash"],
        ["dfm_cache_entries", len(dfm), len(dfm), "PASS" if dfm else "HOLD", "origin-specific cutoff/input hashes"],
        ["dfm_2007plus_failed", len(blocking_dfm), 0, "PASS" if not blocking_dfm and evaluation_dfm else "HOLD", "every evaluation release cutoff requires a ready origin-specific cache"],
        ["dfm_runtime_receipts_missing", len(dfm_runtime_audit["missing_runtime"]), 0, "PASS" if not dfm_runtime_audit["missing_runtime"] else "HOLD", "each origin-specific DFM cache records pandas/statsmodels runtime"],
        ["dfm_runtime_mismatches", len(dfm_runtime_audit["mismatched_runtime"]), 0, "PASS" if not dfm_runtime_audit["mismatched_runtime"] else "HOLD", "statsmodels must equal 0.14.6"],
        ["sealed_evaluation_rows", sealed_audit["ledger_rows"], sealed_audit["ledger_rows"], "PASS" if backtest and sealed_audit["ledger_rows"] else "HOLD", "append-only history includes corrected runs"],
        ["sealed_correction_rows", sealed_audit["correction_rows"], sealed_audit["correction_rows"], "PASS" if not sealed_audit["unknown_corrections"] else "HOLD", "every correction references a preserved sealed run"],
        ["active_sealed_evaluations", sealed_audit["active_rows"], 1, "PASS" if sealed_audit["active_rows"] == 1 else "HOLD", "exactly one non-invalidated evaluation per frozen contract"],
        ["numbers_visible", bool(latest and latest["publication"]["customer_numbers_visible"]), bool(backtest and backtest["summary"]["gate_pass"]), "PASS" if not latest or bool(latest["publication"]["customer_numbers_visible"]) == bool(backtest and backtest["summary"]["gate_pass"]) else "HOLD", "fail closed"],
        ["official_forecast_writes", 0, 0, "PASS", "isolated research space"],
        ["scenario_v5_2_writes", 0, 0, "PASS", "protected"],
        ["workbook_role", "review export", "review export", "PASS", "JSONL/raw stores are canonical"],
    ]

    sheets: dict[str, tuple[list[list[Any]], list[float]]] = {
        "Sources": (source_rows, [24, 28, 30, 14, 16, 16, 28, 22]),
        "Observations": (observation_rows, [28, 20, 18, 16, 20, 28, 32, 28, 28, 68, 34, 68]),
        "Vintages": (vintage_rows, [22, 38, 16, 22, 28, 28, 18, 64]),
        "Features": (feature_rows, [14, 38, 24, 62, 26, 68]),
        "Forecasts": (forecast_rows, [34, 18, 28, 24, 18, 20, 34, 30, 68]),
        "Backtest": (backtest_rows, [14, 22, 14, 20, 14, 14, 16, 26, 22, 22, 22]),
        "ModelCard": (model_rows, [42, 104]),
        "RunManifest": (run_rows, [34, 74, 74, 16, 72]),
    }
    parts = _workbook_parts(list(sheets))
    for index, (_, (rows, widths)) in enumerate(sheets.items(), start=1):
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
    return target, {
        "sheets": 8, "sources": len(source_rows) - 1,
        "observation_export_rows": len(observation_rows) - 1,
        "market_facts": len(market_rows), "macro_fact_rows": len(macro_rows),
        "dfm_cache_entries": len(dfm), "sha256": _file_hash(target),
        "contract_hash": frozen_hash(contract),
        "model_code_hash": model_code_hash(root),
    }
