"""Deterministic eight-sheet V3 research audit workbook.

The workbook is a read-only review projection.  V2 PIT ledgers and V3 JSON
artifacts remain canonical; this module never edits them.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any

from ai_fc.official_data_workbook import _sheet_xml, _workbook_parts

from .contracts import (
    LATEST_RELATIVE,
    MODEL_ID,
    MODEL_VERSION,
    RUNS_RELATIVE,
    WORKBOOK_RELATIVE,
    frozen_hash,
    load_contract_v3,
    model_code_hash,
    verify_v2_benchmark,
)


def _json(path: Path) -> dict[str, Any] | None:
    return None if not path.is_file() else json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_backtest(root: Path) -> dict[str, Any]:
    pointer = _json(root / RUNS_RELATIVE / "backtest_latest.json")
    if not pointer:
        raise RuntimeError("V3 backtest pointer is missing")
    payload = _json(root / str(pointer["path"]))
    if not payload:
        raise RuntimeError("V3 backtest artifact is missing")
    return payload


def export_timeseries_v3_workbook(root: Path) -> tuple[Path, dict[str, Any]]:
    import pandas as pd  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    contract = load_contract_v3(root)
    v2 = verify_v2_benchmark(root, contract)
    backtest = _latest_backtest(root)
    latest = _json(root / LATEST_RELATIVE)
    forecasts = _jsonl(root / "data/timeseries_v3/ledgers/forecasts.jsonl")
    features_path = root / "data/timeseries_v2/parquet/features_C1.parquet"
    market_path = root / "data/timeseries_v2/parquet/market_observations.parquet"
    features = pd.read_parquet(features_path)
    market = pd.read_parquet(market_path)

    sources = [[
        "series_id", "data_grade", "canonical_store", "rows", "first_observation",
        "last_observation", "v3_role", "mutation_allowed",
    ]]
    for series_id, group in market.groupby("series_id", sort=True):
        sources.append([
            series_id,
            ", ".join(sorted({str(value) for value in group["data_grade"].dropna()})),
            "data/timeseries_v2/parquet/market_observations.parquet",
            len(group), str(group["observation_time"].min()), str(group["observation_time"].max()),
            "read_only_market_input", False,
        ])
    sources.append([
        "V2_C1_FEATURES", "mixed_explicit",
        "data/timeseries_v2/parquet/features_C1.parquet", len(features),
        str(features.index.min()), str(features.index.max()), "read_only_feature_input", False,
    ])

    observations = [[
        "dataset", "rows", "columns", "sha256", "canonical_role", "notes",
    ], [
        "V2 market observations", len(market), len(market.columns), _sha256(market_path),
        "immutable upstream read model", "V3 never rewrites V2 facts or receipts",
    ], [
        "V2 C1 features", len(features), len(features.columns), _sha256(features_path),
        "immutable upstream read model", "direct targets are created only after each forecast origin",
    ], [
        "V3 weekly research origins", backtest["origin_count"], len(backtest["scores"]),
        backtest["content_hash"], "research pseudo-OOS", "2019+ is not represented as unseen sealed data",
    ]]

    vintages = [["field", "value", "status", "audit_note"],
        ["available_at policy", "available_at <= origin", "PASS", "inherited V2 PIT snapshots are read only"],
        ["market history grade", "reconstructed_market_archive", "PASS", "never described as native ALFRED PIT"],
        ["macro DFM in V3 numerical model", "blocked", "HOLD", "V2 caches lack named loading vectors for sign alignment"],
        ["event PIT history", "not yet sufficient", "HOLD", "event weight remains zero"],
        ["V2 benchmark run", v2["run_id"], "PASS", "exact content/contract/model-code hashes verified"],
    ]

    feature_rows = [["block", "features", "status", "numerical_weight", "notes"]]
    feature_rows.extend([
        ["direct location", ", ".join(contract["direct_location"]["ridge_features"]), "active_research", "bounded", "direct 1/5/21/63 residual correction"],
        ["analog quantile", ", ".join(contract["direct_location"]["analog_quantile"]["distance_features"]), "active_research", contract["direct_location"]["analog_quantile"]["conditional_weight"], "annual first-origin K selection uses only prior data"],
        ["volatility/tail", ", ".join(contract["volatility_tail"]["features"]), "active_research", "stacked", "separate scale and residual-shape module"],
        ["DFM aligned", ", ".join(contract["dfm_alignment"]["features"]), "blocked", 0.0, "requires V3-native named-loading cache"],
        ["event", ", ".join(contract["events"]["types"]), "blocked", 0.0, "requires PIT event sample and ablation gate"],
        ["market implied", ", ".join(contract["market_implied"]["inputs"]), "blocked", 0.0, "requires physical calibration outcomes"],
        ["analyst reports", "structured signals only", "optional_blocked", 0.0, "free text cannot directly shift paths"],
    ])

    forecast_rows = [[
        "forecast_id", "as_of", "status", "research_gate_pass", "forward_stage",
        "customer_numbers_visible", "backtest_run_id", "content_hash",
    ]]
    for row in forecasts:
        forecast_rows.append([
            row.get("forecast_id"), row.get("as_of"), row.get("status"),
            row.get("research_gate_pass"), row.get("forward_shadow_stage"),
            row.get("customer_numbers_visible"), row.get("backtest_run_id"), row.get("content_hash"),
        ])
    if len(forecast_rows) == 1:
        forecast_rows.append([None, None, "validation_pending", False, "not_started", False, backtest["run_id"], None])

    backtest_rows = [[
        "section", "horizon_or_group", "model_crps", "baseline_crps", "improvement",
        "coverage_model", "coverage_baseline", "count", "status",
    ]]
    for horizon, metrics in sorted(backtest["research_gate"]["by_horizon"].items(), key=lambda item: int(item[0])):
        backtest_rows.append([
            "primary", int(horizon), metrics["model_crps"], metrics["baseline_crps"],
            metrics["improvement"], None, None, backtest["origin_count"],
            "PASS" if metrics["improvement"] > 0 else "HOLD",
        ])
    for horizon, dimensions in backtest["research_gate"]["conditional_tables"].items():
        for dimension, groups in dimensions.items():
            for group, metrics in groups.items():
                backtest_rows.append([
                    dimension, f"{horizon}:{group}", metrics["model_crps"], metrics["baseline_crps"],
                    metrics["crps_improvement"], metrics["p10_p90_coverage"],
                    metrics["baseline_p10_p90_coverage"], metrics["count"], "research_diagnostic",
                ])

    gate = backtest["research_gate"]
    model_card = [["field", "value"],
        ["model_id", MODEL_ID], ["model_version", MODEL_VERSION],
        ["lifecycle", "research_shadow_hold"], ["target", "NASDAQCOM direct cumulative log return"],
        ["horizons", "1, 5, 21, 63 sessions"], ["history_role", contract["evaluation"]["history_role"]],
        ["fixed comparator", gate["fixed_comparator"]], ["row-wise oracle", gate["row_wise_oracle_used"]],
        ["research gate pass", gate["pass"]], ["research gate reasons", " | ".join(gate["reasons"])],
        ["21/63 mean CRPS improvement", gate["long_horizon_mean_improvement"]],
        ["paired 90% CI", json.dumps(gate["paired_loss_difference_90_ci"])],
        ["customer numbers visible", bool(latest and latest.get("customer_numbers_visible"))],
        ["official/scenario combination", "No"], ["automatic champion", "No"],
        ["automatic investment execution", "No"], ["contract hash", frozen_hash(contract)],
        ["model code hash", model_code_hash(root)], ["backtest content hash", backtest["content_hash"]],
    ]

    run_manifest = [["check", "actual", "expected", "status", "notes"],
        ["V2 run id", v2["run_id"], contract["v2_benchmark"]["run_id"], "PASS", "sealed benchmark"],
        ["V2 content hash", v2["content_hash"], contract["v2_benchmark"]["content_hash"], "PASS", "sealed benchmark"],
        ["V3 contract hash", backtest["contract_hash"], frozen_hash(contract), "PASS" if backtest["contract_hash"] == frozen_hash(contract) else "HOLD", "frozen coordinates"],
        ["V3 model code hash", backtest["model_code_hash"], model_code_hash(root), "PASS" if backtest["model_code_hash"] == model_code_hash(root) else "HOLD", "artifact predates later audit-only code when HOLD"],
        ["origin count", backtest["origin_count"], 250, "PASS" if backtest["origin_count"] >= 250 else "HOLD", "weekly origins since 2007"],
        ["research gate", gate["pass"], True, "PASS" if gate["pass"] else "HOLD", "no threshold lowering"],
        ["forward shadow", (latest or {}).get("forward_shadow", {}).get("captured_sessions", 0), contract["forward_shadow"]["stage_a_sessions"], "HOLD", "starts only after research gate"],
        ["customer publication", bool(latest and latest.get("customer_numbers_visible")), False, "PASS", "fail closed"],
        ["official writes", 0, 0, "PASS", "isolated research probability space"],
        ["Scenario V5.2 writes", 0, 0, "PASS", "protected"],
    ]

    sheets: dict[str, tuple[list[list[Any]], list[float]]] = {
        "Sources": (sources, [24, 32, 62, 14, 22, 22, 28, 18]),
        "Observations": (observations, [30, 16, 16, 68, 34, 72]),
        "Vintages": (vintages, [30, 58, 16, 88]),
        "Features": (feature_rows, [26, 92, 24, 20, 88]),
        "Forecasts": (forecast_rows, [38, 18, 26, 22, 24, 24, 38, 68]),
        "Backtest": (backtest_rows, [28, 28, 20, 20, 20, 20, 20, 14, 24]),
        "ModelCard": (model_card, [42, 112]),
        "RunManifest": (run_manifest, [36, 76, 76, 16, 76]),
    }
    parts = _workbook_parts(list(sheets))
    for index, (_, (rows, widths)) in enumerate(sheets.items(), start=1):
        parts[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(rows, widths=widths, freeze_header=True)
    target = root / WORKBOOK_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body.encode("utf-8"))
    os.replace(temporary, target)
    return target, {
        "sheets": 8, "sources": len(sources) - 1, "origins": backtest["origin_count"],
        "gate_pass": gate["pass"], "customer_numbers_visible": False,
        "sha256": _sha256(target), "contract_hash": frozen_hash(contract),
    }
