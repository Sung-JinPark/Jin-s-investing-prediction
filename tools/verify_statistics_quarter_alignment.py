"""Offline, same-input shadow for quarterly/monthly statistics alignment.

Rebuilds a frozen implementation and the candidate from one ledger read model.
Writes review artifacts only; never calls a collector or publishes a snapshot.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch


BASELINE_REF = "258a3c5e1dd4441f5f92ec146953de0aabe6c55a"
EXPECTED_CHARTS = {
    "nasdaq_per_household_liquid_assets",
    "spx_per_federal_debt",
    "spx_per_federal_debt_full_history",
}
EXPECTED_INDICATORS = {"nasdaq_per_household_liquid_assets", "spx_per_federal_debt"}
ABS_TOLERANCE = 0.0
REL_TOLERANCE = 0.0
BASELINE_REPLAY_ABS_TOLERANCE = 1e-12
BASELINE_REPLAY_REL_TOLERANCE = 1e-12
PROTECTED = (
    "forecasts", "calibration", "questions", "data/contracts",
    "data/statistics/official_store", "data/statistics/archive",
    "data/statistics/workbooks", "data/statistics/ipo",
    "data/statistics/dotcom_statistics_latest.json",
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def differences(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    """Complete recursive differences; no metadata or numeric fields are hidden."""
    if (isinstance(before, (int, float)) and not isinstance(before, bool)
            and isinstance(after, (int, float)) and not isinstance(after, bool)):
        if not math.isfinite(before) or not math.isfinite(after):
            raise ValueError(f"non-finite shadow value at {path}")
        if math.isclose(before, after, abs_tol=ABS_TOLERANCE, rel_tol=REL_TOLERANCE):
            return []
        return [{"path": path, "kind": "number", "before": before, "after": after,
                 "delta": after - before}]
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            child = f"{path}.{key}"
            if key not in before:
                result.append({"path": child, "kind": "added", "after": after[key]})
            elif key not in after:
                result.append({"path": child, "kind": "removed", "before": before[key]})
            else:
                result.extend(differences(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = []
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            if index >= len(before):
                result.append({"path": child, "kind": "added", "after": after[index]})
            elif index >= len(after):
                result.append({"path": child, "kind": "removed", "before": before[index]})
            else:
                result.extend(differences(before[index], after[index], child))
        return result
    if type(before) is type(after) and before == after:
        return []
    return [{"path": path, "kind": "value", "before": before, "after": after}]


def git_bytes(root: Path, spec: str) -> bytes:
    return subprocess.run(["git", "show", spec], cwd=root, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def frozen_module(root: Path, ref: str, filename: str, name: str) -> types.ModuleType:
    source = git_bytes(root, f"{ref}:src/ai_fc/{filename}.py")
    module = types.ModuleType(f"ai_fc.{name}")
    module.__package__ = "ai_fc"
    # Existing policy readers resolve repository-local files from __file__.
    # Source bytes still come exclusively from the pinned Git object above.
    module.__file__ = str(root / "src/ai_fc" / f"{filename}.py")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{ref}:src/ai_fc/{filename}.py", "exec"), module.__dict__)
    return module


def protected_hashes(root: Path) -> dict[str, str]:
    result = {}
    for relative in PROTECTED:
        path = root / relative
        paths = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
        for child in paths:
            if child.is_file():
                result[child.relative_to(root).as_posix()] = file_digest(child)
    return result


def series_comparison(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old_points, new_points = before.get("points") or [], after.get("points") or []
    paired = []
    for index in range(max(len(old_points), len(new_points))):
        left = old_points[index] if index < len(old_points) else None
        right = new_points[index] if index < len(new_points) else None
        if differences(left, right):
            entry = {"ordinal": index, "before": left, "after": right}
            if (left and right and isinstance(left.get("value"), (int, float))
                    and isinstance(right.get("value"), (int, float))):
                entry["value_delta"] = right["value"] - left["value"]
            paired.append(entry)
    numeric = [abs(row["value_delta"]) for row in paired if "value_delta" in row]
    return {
        "label": after.get("label", before.get("label")),
        "era": after.get("era", before.get("era")),
        "before_count": len(old_points), "after_count": len(new_points),
        "before_first": old_points[0] if old_points else None,
        "after_first": new_points[0] if new_points else None,
        "before_last": old_points[-1] if old_points else None,
        "after_last": new_points[-1] if new_points else None,
        "changed_ordinals": len(paired), "max_abs_value_delta": max(numeric, default=0.0),
        "point_comparison_rule": "ordinal within the same labelled era; complete before/after points retained",
        "changed_points": paired,
        "metadata_changes": differences(
            {k: v for k, v in before.items() if k != "points"},
            {k: v for k, v in after.items() if k != "points"},
        ),
    }


def chart_comparisons(before: dict, after: dict) -> list[dict]:
    old = {chart["id"]: chart for chart in before["charts"]}
    new = {chart["id"]: chart for chart in after["charts"]}
    result = []
    for chart_id in sorted(old.keys() | new.keys()):
        left, right = old.get(chart_id, {}), new.get(chart_id, {})
        delta = differences(left, right)
        old_series, new_series = left.get("series") or [], right.get("series") or []
        result.append({
            "id": chart_id, "changed": bool(delta), "difference_count": len(delta),
            "before_sha256": digest(left), "after_sha256": digest(right),
            "series": [series_comparison(
                old_series[index] if index < len(old_series) else {},
                new_series[index] if index < len(new_series) else {},
            ) for index in range(max(len(old_series), len(new_series)))],
            "non_series_changes": differences(
                {k: v for k, v in left.items() if k != "series"},
                {k: v for k, v in right.items() if k != "series"},
            ),
        })
    return result


def index_from_payload(root: Path, payload: dict, module: types.ModuleType,
                       contract: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="statistics-quarter-index-") as temporary:
        target = Path(temporary)
        snapshot = target / module.STATISTICS_RELATIVE
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        contract_path = target / module.CONTRACT_RELATIVE
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_bytes(contract)
        for relative in (
            "data/statistics/official_store/ledgers/raw_receipts.jsonl",
            "data/statistics/ipo/monthly_counts_status.json",
            "data/statistics/ipo/theme_listing_watch.json",
        ):
            source = root / relative
            if source.is_file():
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        return module.compute_index(target)


def projection_from_payload(payload: dict, module: types.ModuleType) -> dict:
    with tempfile.TemporaryDirectory(prefix="statistics-quarter-projection-") as temporary:
        target = Path(temporary)
        snapshot = target / module.LATEST_RELATIVE
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        projection = module.statistics_dashboard_projection(target)
        module.validate_statistics_lab(projection, projected=True)
        return projection


def index_comparison(before: dict, after: dict) -> dict:
    old = {row["id"]: row for row in before.get("indicators") or []}
    new = {row["id"]: row for row in after.get("indicators") or []}
    rows = []
    for indicator_id in sorted(old.keys() | new.keys()):
        left, right = old.get(indicator_id, {}), new.get(indicator_id, {})
        rows.append({"id": indicator_id, "changed": bool(differences(left, right)),
                     "before": left, "after": right,
                     "pct_delta": right.get("pct", 0) - left.get("pct", 0),
                     "differences": differences(left, right)})
    return {
        "indicators": rows,
        "aggregate_changes": differences(
            {k: v for k, v in before.items() if k != "indicators"},
            {k: v for k, v in after.items() if k != "indicators"},
        ),
        "before_overall": before.get("overheat_pct"), "after_overall": after.get("overheat_pct"),
        "before_categories": before.get("category_medians"),
        "after_categories": after.get("category_medians"),
    }


def markdown(report: dict) -> str:
    lines = ["# 분기·월간 정렬 동일 입력 그림자 검증", "",
             f"- 기준 코드: `{report['baseline_commit']}`",
             f"- 원천 관측·영수증 공통 입력 SHA256: `{report['inputs_sha256']}`",
             f"- 수치 허용오차: 절대 {ABS_TOLERANCE}, 상대 {REL_TOLERANCE} (정확 비교)",
             f"- 결과: **{report['status']}**; 공식 파일 보존: {report['protected_unchanged']}",
             f"- 기존 스냅샷 재현의 정확 차이: {len(report['baseline_replay_differences'])}개 "
             f"(명시적 재현 오차 이내 {len(report['baseline_replay_tolerated_numeric_differences'])}개)",
             f"- 플랫폼 재현에만 적용한 허용오차: 절대 {BASELINE_REPLAY_ABS_TOLERANCE}, "
             f"상대 {BASELINE_REPLAY_REL_TOLERANCE}; 구조·문자열 차이는 허용하지 않음",
             "", "| 차트 | 변경 | 이전/이후 점 수 (계열별) |", "|---|---|---|"]
    for chart in report["charts"]:
        counts = "; ".join(f"{series['era'] or series['label']}: {series['before_count']} → {series['after_count']}"
                           for series in chart["series"])
        lines.append(f"| {chart['id']} | {chart['changed']} | {counts} |")
    index = report["overheat"]
    lines.extend(["", f"과열도 전체: **{index['before_overall']} → {index['after_overall']}**", "",
                  "| 지표 | 이전 | 이후 | 차이(%p) | 이전/이후 자료일 |", "|---|---:|---:|---:|---|"])
    for row in index["indicators"]:
        left, right = row["before"], row["after"]
        lines.append(f"| {row['id']} | {left.get('pct')} | {right.get('pct')} | {row['pct_delta']:+.1f} | "
                     f"{left.get('current_date')} → {right.get('current_date')} |")
    lines.extend(["", f"부문 이전: `{index['before_categories']}`",
                  f"부문 이후: `{index['after_categories']}`", "",
                  "모든 차트의 과거·현재 관측점 변경, 전체 필드 차이, 입력·보호 파일 해시는 "
                  "shadow_report.json 및 baseline/candidate 산출물에 보존합니다. "
                  "이 도구는 공식 스냅샷·원장을 쓰거나 자동 승격하지 않습니다."])
    return "\n".join(lines) + "\n"


def verify(root: Path, baseline_ref: str, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    for protected in PROTECTED:
        target = (root / protected).resolve()
        if output == target or output.is_relative_to(target):
            raise ValueError("shadow output must not be inside a protected data path")
    sys.path.insert(0, str(root / "src"))
    candidate_code_before = file_digest(root / "src/ai_fc/statistics_lab.py")
    from ai_fc import dashboard, dotcom_overheat, statistics_lab
    from ai_fc.ipo_monthly_counts import load_ipo_monthly_tables

    baseline_commit = subprocess.run(
        ["git", "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"], cwd=root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    old_lab = frozen_module(root, baseline_commit, "statistics_lab", "_quarter_alignment_baseline")
    old_index = frozen_module(root, baseline_commit, "dotcom_overheat", "_quarter_index_baseline")
    protected_before = protected_hashes(root)
    snapshot = json.loads((root / statistics_lab.LATEST_RELATIVE).read_text(encoding="utf-8"))
    receipts = {row["series_id"]: copy.deepcopy(row) for row in snapshot["sources"]}
    preferences = {sid: row.get("policy_source_id", "fred_market_signals")
                   for sid, row in receipts.items() if sid in old_lab.FRED_SERIES}
    source_rows = old_lab._load_authoritative_current_rows(root, source_preferences=preferences)
    inputs = {"source_rows": source_rows, "generated_at": snapshot["generated_at"],
              "receipts": receipts, "ipo_reference": old_lab.load_ipo_reference(root),
              "ipo_monthly": load_ipo_monthly_tables(root)}
    inputs_sha256 = digest(inputs)
    with patch("urllib.request.urlopen", side_effect=RuntimeError("shadow HTTP access forbidden")), \
            patch("socket.create_connection", side_effect=RuntimeError("shadow network access forbidden")):
        baseline = old_lab.build_statistics_lab(**copy.deepcopy(inputs))
        candidate = statistics_lab.build_statistics_lab(**copy.deepcopy(inputs))
        baseline_overheat = index_from_payload(
            root, baseline, old_index,
            git_bytes(root, f"{baseline_commit}:{old_index.CONTRACT_RELATIVE.as_posix()}"),
        )
        candidate_overheat = index_from_payload(
            root, candidate, dotcom_overheat, (root / dotcom_overheat.CONTRACT_RELATIVE).read_bytes(),
        )
        candidate_projection = projection_from_payload(candidate, statistics_lab)
        _, sidecar = dashboard.split_statistics_data({"statistics_lab": candidate_projection})
        sidecar_bytes = json.dumps(sidecar, ensure_ascii=False, default=str,
                                   separators=(",", ":")).encode("utf-8")
    protected_after = protected_hashes(root)
    chart_rows = chart_comparisons(baseline, candidate)
    changed_charts = {row["id"] for row in chart_rows if row["changed"]}
    overheat = index_comparison(baseline_overheat, candidate_overheat)
    changed_indicators = {row["id"] for row in overheat["indicators"] if row["changed"]}
    outside_charts = differences({k: v for k, v in baseline.items() if k != "charts"},
                                 {k: v for k, v in candidate.items() if k != "charts"})
    debt_source_index = next(index for index, row in enumerate(baseline["sources"])
                             if row["series_id"] == "GFDEBTN")
    reviewed_metadata = [row for row in outside_charts
                         if row["path"] == f"$.sources[{debt_source_index}].native_frequency"
                         and row.get("before") == "quarterly"
                         and row.get("after") == "quarterly_end_of_period"]
    unreviewed_outside_changes = [row for row in outside_charts if row not in reviewed_metadata]
    replay = differences(snapshot, baseline)
    tolerated_replay = [row for row in replay if row["kind"] == "number"
                        and math.isclose(row["before"], row["after"],
                                         abs_tol=BASELINE_REPLAY_ABS_TOLERANCE,
                                         rel_tol=BASELINE_REPLAY_REL_TOLERANCE)]
    material_replay = [row for row in replay if row not in tolerated_replay]
    candidate_code_after = file_digest(root / "src/ai_fc/statistics_lab.py")
    gates = {
        "baseline_replays_official_snapshot_with_declared_platform_tolerance": not material_replay,
        "candidate_code_unchanged_during_shadow": candidate_code_before == candidate_code_after,
        "candidate_canonical_and_projection_validated": candidate_projection.get("display_projection") is True,
        "candidate_statistics_sidecar_within_budget": len(sidecar_bytes) <= dashboard.STATISTICS_DATA_BUDGET_BYTES,
        "expected_three_changed_charts": changed_charts == EXPECTED_CHARTS,
        "only_reviewed_source_frequency_metadata_changed": len(reviewed_metadata) == 1,
        "all_other_payload_fields_unchanged": not unreviewed_outside_changes,
        "fourteen_indicators_in_both": len(baseline_overheat.get("indicators", [])) == 14
            and len(candidate_overheat.get("indicators", [])) == 14,
        "only_expected_overheat_indicators_changed": changed_indicators == EXPECTED_INDICATORS,
        "source_rows_not_mutated": digest(inputs) == inputs_sha256,
        "protected_files_unchanged": protected_before == protected_after,
        "reference_only_both": all(value.get("probability_space") == "reference_only"
                                    and value.get("model_use") is False
                                    and value.get("official_forecast_input") is False
                                    for value in (baseline, candidate, baseline_overheat, candidate_overheat)),
    }
    report = {
        "schema_version": 1, "status": "pass" if all(gates.values()) else "fail",
        "baseline_commit": baseline_commit,
        "candidate_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                             check=True, capture_output=True, text=True).stdout.strip(),
        "candidate_statistics_code_sha256": candidate_code_before,
        "candidate_statistics_code_sha256_after": candidate_code_after,
        "baseline_statistics_code_sha256": hashlib.sha256(git_bytes(
            root, f"{baseline_commit}:src/ai_fc/statistics_lab.py")).hexdigest(),
        "inputs_sha256": inputs_sha256, "generated_at_frozen": snapshot["generated_at"],
        "candidate_statistics_sidecar": {
            "bytes": len(sidecar_bytes), "budget_bytes": dashboard.STATISTICS_DATA_BUDGET_BYTES,
            "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
            "serialization": "actual dashboard.split_statistics_data compact UTF-8 JSON",
        },
        "numerical_tolerance": {"absolute": ABS_TOLERANCE, "relative": REL_TOLERANCE},
        "baseline_replay_tolerance": {"absolute": BASELINE_REPLAY_ABS_TOLERANCE,
                                      "relative": BASELINE_REPLAY_REL_TOLERANCE,
                                      "scope": "frozen baseline vs stored snapshot numeric reconstruction only"},
        "network_access": "forbidden during both builds and index calculations",
        "official_writes": False, "promotion": "review required; no automatic promotion",
        "gates": gates, "protected_unchanged": protected_before == protected_after,
        "protected_before": protected_before, "protected_after": protected_after,
        "native_inputs": {sid: {"rows": len(rows), "first": rows[0]["date"],
                               "last": rows[-1]["date"], "sha256": digest(rows)}
                          for sid, rows in sorted(source_rows.items())},
        "baseline_replay_differences": replay,
        "baseline_replay_tolerated_numeric_differences": tolerated_replay,
        "baseline_replay_material_differences": material_replay,
        "charts": chart_rows,
        "all_payload_differences": differences(baseline, candidate),
        "outside_chart_differences": outside_charts,
        "reviewed_source_metadata_corrections": reviewed_metadata,
        "unreviewed_outside_chart_differences": unreviewed_outside_changes,
        "overheat": overheat,
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("shadow_inputs.json", inputs), ("official_snapshot.json", snapshot),
                        ("baseline_statistics.json", baseline), ("candidate_statistics.json", candidate),
                        ("candidate_projection.json", candidate_projection),
                        ("baseline_overheat.json", baseline_overheat), ("candidate_overheat.json", candidate_overheat),
                        ("shadow_report.json", report)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                             allow_nan=False) + "\n", encoding="utf-8")
    (output / "shadow_summary.md").write_text(markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    output = args.out_dir or args.root / "outputs/statistics_quarter_alignment/20261029"
    report = verify(args.root, args.baseline_ref, output)
    print(json.dumps({"status": report["status"], "gates": report["gates"],
                      "artifacts": str(output.resolve())}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
