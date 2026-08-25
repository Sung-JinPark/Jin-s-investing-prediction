"""Prepare V5 audit data and delegate XLSX authoring to artifact-tool."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import MODEL_ID, PROBABILITY_SPACE, contract_hash
from .features import load_research_frame
from .pipeline import PRIVATE_DEFAULT, V5_DATA
from .sources import SOURCE_REGISTRY


SHEETS = ("Sources", "Observations", "Vintages", "Features", "Forecasts", "Backtest", "ModelCard", "RunManifest")


def _ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as handle:
        return sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""))


def _rows(root: Path) -> dict[str, list[list[Any]]]:
    pd = __import__("pandas")
    private_root = root / PRIVATE_DEFAULT
    sources = [[row.source_id, row.provider, row.authority_class, row.grade, row.cadence, row.redistribution, row.url] for row in SOURCE_REGISTRY.values()]
    parquet_manifest_path = root / V5_DATA / "manifests/parquet_latest.json"
    parquet_manifest = json.loads(parquet_manifest_path.read_text(encoding="utf-8")) if parquet_manifest_path.is_file() else {"files": []}
    observation_rows: list[list[Any]] = []; vintage_rows: list[list[Any]] = []; total_active = 0; total_revisions = 0
    for item in parquet_manifest.get("files", []):
        source_id = str(item["source_id"]); path = private_root / f"parquet/observations/source_id={source_id}/observations.parquet"
        data = pd.read_parquet(path, columns=["observation_key", "series_id", "observation_time", "available_at", "unit", "data_grade", "revision_seq", "supersedes"])
        active = data.sort_values(["observation_key", "revision_seq"]).drop_duplicates("observation_key", keep="last")
        revision_count = int((data["revision_seq"].astype(int) > 1).sum()); total_active += len(active); total_revisions += revision_count
        observation_rows.append([
            source_id, len(data), len(active), int(data["series_id"].nunique()), str(data["observation_time"].min()), str(data["observation_time"].max()),
            str(data["available_at"].max()), " | ".join(sorted(data["unit"].dropna().astype(str).unique())), " | ".join(sorted(data["data_grade"].dropna().astype(str).unique())),
            item.get("sha256"), item.get("schema_hash"), item.get("uri"),
        ])
        vintage_rows.append([source_id, len(data), len(active), revision_count, int(data["supersedes"].notna().sum()), int(data["revision_seq"].max()), item.get("sha256")])
    _, features, _, _, metadata = load_research_frame(root)
    block_by_feature = {name: block for block, names in metadata.get("feature_blocks", {}).items() for name in names}
    feature_rows: list[list[Any]] = []
    for name in features.columns:
        values = features[name]; valid = values.dropna()
        feature_rows.append([
            name, block_by_feature.get(name, "base_or_missing_indicator"), int(valid.size), None if valid.empty else valid.index[0].date().isoformat(),
            None if valid.empty else valid.index[-1].date().isoformat(), None if valid.empty else float(valid.iloc[-1]),
            None if valid.empty else float(valid.median()), None if valid.empty else float(valid.quantile(.25)), None if valid.empty else float(valid.quantile(.75)),
        ])
    forecasts = _ledger(root / V5_DATA / "ledgers/forecasts.jsonl")
    if not forecasts:
        latest_forecast_path = root / V5_DATA / "multivariate_v5_latest.json"
        if latest_forecast_path.is_file():
            latest = json.loads(latest_forecast_path.read_text(encoding="utf-8"))
            forecasts = [{
                "forecast_id": latest.get("forecast_id") or "latest-hold-artifact",
                "as_of": latest.get("as_of"),
                "status": latest.get("status"),
                "numbers_visible": latest.get("numbers_visible"),
                "backtest_run_id": latest.get("backtest_run_id"),
                "content_hash": latest.get("content_hash"),
            }]
    forecast_rows = [[row.get("forecast_id"), row.get("as_of"), row.get("status"), row.get("numbers_visible"), row.get("backtest_run_id"), row.get("content_hash")] for row in forecasts]
    pointer_path = root / V5_DATA / "runs/backtest_latest.json"; backtest: dict[str, Any] = {}
    if pointer_path.is_file():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8")); backtest = json.loads((root / pointer["path"]).read_text(encoding="utf-8"))
    backtest_rows = [[horizon, row.get("count"), row.get("model_crps"), row.get("baseline_crps"), row.get("improvement"), row.get("p10_p90_coverage"), row.get("p25_p75_coverage"), row.get("lower_miss_share")] for horizon, row in sorted((backtest.get("research_gate", {}).get("by_horizon") or {}).items(), key=lambda pair: int(pair[0]))]
    collection = json.loads((root / V5_DATA / "manifests/collection_latest.json").read_text(encoding="utf-8")) if (root / V5_DATA / "manifests/collection_latest.json").is_file() else {}
    protected = json.loads((root / V5_DATA / "manifests/protected_baseline.json").read_text(encoding="utf-8")) if (root / V5_DATA / "manifests/protected_baseline.json").is_file() else {}
    model_rows = [
        ["Model ID", MODEL_ID], ["Probability space", PROBABILITY_SPACE], ["Contract hash", contract_hash(root)],
        ["Research Gate", bool(backtest.get("research_gate", {}).get("pass"))], ["Gate reasons", " | ".join(backtest.get("research_gate", {}).get("reasons", []))],
        ["Evaluation role", metadata["evaluation_label"]], ["Data grades", "reconstructed_market_archive | reconstructed_official_archive | captured_forward"],
        ["Candidate selected horizons", len(backtest.get("latest_selection_by_horizon", {}))], ["Sealed run ID", backtest.get("run_id")],
        ["Official write", False], ["Scenario combination", False], ["Automatic champion", False],
    ]
    ledgers = private_root / "ledgers"
    manifest_rows = [
        ["Generated at", datetime.now(timezone.utc).isoformat()], ["Source catalog rows", len(sources)], ["Canonical observation rows", sum(int(row[1]) for row in observation_rows)],
        ["Active observation keys", total_active], ["Explicit revision rows", total_revisions], ["Receipt rows", _line_count(ledgers / "raw_receipts.jsonl")],
        ["Receipt-fact link rows", _line_count(ledgers / "receipt_fact_links.jsonl")], ["Normalization corrections", _line_count(ledgers / "normalization_corrections.jsonl")],
        ["Labels", _line_count(ledgers / "labels.jsonl")], ["Parquet content hash", parquet_manifest.get("content_hash")],
        ["Lineage pass", bool((parquet_manifest.get("lineage") or {}).get("ok"))], ["Observation linkage", (parquet_manifest.get("lineage") or {}).get("observation_linkage")],
        ["Collection run", collection.get("run_id")], ["Protected baseline hash", protected.get("manifest_hash")], ["Feature definitions", len(feature_rows)],
        ["Forecasts", len(forecast_rows)], ["Backtest rows", len(backtest_rows)], ["Sheet count", len(SHEETS)],
    ]
    return {
        "Sources": [["source_id", "provider", "authority_class", "data_grade", "cadence", "redistribution", "source_url"], *sources],
        "Observations": [["source_id", "canonical_rows", "active_keys", "series_count", "first_observation", "last_observation", "latest_available_at", "units", "data_grades", "parquet_sha256", "schema_hash", "private_uri"], *observation_rows],
        "Vintages": [["source_id", "canonical_rows", "active_keys", "revision_rows", "supersedes_rows", "max_revision_seq", "parquet_sha256"], *vintage_rows],
        "Features": [["feature", "block", "nonmissing_sessions", "first_session", "latest_session", "latest_value", "median", "q25", "q75"], *feature_rows],
        "Forecasts": [["forecast_id", "as_of", "status", "numbers_visible", "backtest_run_id", "content_hash"], *forecast_rows],
        "Backtest": [["horizon", "origins", "model_crps", "baseline_crps", "improvement", "p10_p90_coverage", "p25_p75_coverage", "lower_miss_share"], *backtest_rows],
        "ModelCard": [["field", "value"], *model_rows],
        "RunManifest": [["item", "value"], *manifest_rows],
    }


def export_timeseries_v5_workbook(root: Path) -> tuple[Path, dict[str, Any]]:
    output_dir = root / "outputs" / f"timeseries-v5-audit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    output_dir.mkdir(parents=True, exist_ok=True); input_path = output_dir / "workbook_input.json"
    input_path.write_text(json.dumps({"sheets": _rows(root)}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    node = os.environ.get("TSV5_ARTIFACT_NODE"); modules = os.environ.get("TSV5_ARTIFACT_NODE_MODULES")
    if not node or not modules: raise RuntimeError("artifact-tool runtime is not configured for V5 workbook export")
    target = output_dir / "NASDAQ_TIMESERIES_V5_AUDIT.xlsx"; render_dir = output_dir / "rendered"
    environment = {**os.environ, "NODE_PATH": modules}
    completed = subprocess.run(
        [node, str(root / "tools/timeseries_v5_workbook.mjs"), str(input_path), str(target), str(render_dir)],
        cwd=root,
        env=environment,
        check=False,
    )
    rendered = [render_dir / f"{sheet}.png" for sheet in SHEETS]
    inspection = render_dir / "inspection.ndjson"
    export_complete = target.is_file() and all(path.is_file() for path in rendered) and inspection.is_file()
    if completed.returncode and not export_complete:
        raise subprocess.CalledProcessError(completed.returncode, completed.args)
    inspection_text = inspection.read_text(encoding="utf-8")
    if "Cell search matched 0 entries." not in inspection_text:
        raise RuntimeError("artifact-tool formula error scan did not complete cleanly")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, {
        "sheets": len(SHEETS),
        "sha256": digest,
        "render_dir": render_dir.as_posix(),
        "artifact_runtime_exit_code": completed.returncode,
    }
