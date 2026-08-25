from __future__ import annotations

import argparse
import os
import json
import subprocess
import sys
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Set deterministic numerical controls before importing NumPy/SciPy/sklearn
# through the V6 modules below.  The Atlas worker applies the same contract,
# while this guard also covers direct CLI and offline replay execution.
for _name, _value in {
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
}.items():
    os.environ[_name] = _value

from ai_fc.timeseries_v6.research_backtest import (
    CANDIDATE_IMPLEMENTATION_VERSION,
    sealed_backtest,
    select_candidate,
)
from ai_fc.timeseries_v6.research_dataset import build_research_dataset
from ai_fc.timeseries_v6.research_gate import evaluate_research_gate
from ai_fc.timeseries_v6.research_verify import verify_research_run
from ai_fc.timeseries_v6.candidate_eligibility import evaluate_deferred_candidates


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"immutable run artifact collision: {path}")
        return
    path.write_text(content, encoding="utf-8")


def append_once(path: Path, row: dict) -> None:
    identity = row["invalidation_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = [] if not path.exists() else [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if any(item.get("invalidation_id") == identity for item in existing):
        return
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["select", "select-parallel", "eligibility", "sealed", "replay", "gate"])
    parser.add_argument("--candidate", choices=["E1", "E2", "E3", "E4", "E5", "E6", "E7"])
    parser.add_argument("--horizon", type=int, choices=[1, 5, 21, 63])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "outputs/timeseries_v6/research"
    dataset = build_research_dataset(root, root / "data/timeseries_v6/manifests/public_archive_latest.json")
    if args.phase == "eligibility":
        result = evaluate_deferred_candidates(root)
        write_json(output / "deferred_candidate_eligibility.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.phase == "select-parallel":
        if not args.candidate:
            parser.error("--candidate is required for select-parallel")
        supported = {"E1": (1, 5, 21, 63), "E2": (1, 5, 21, 63), "E3": (1, 5, 21, 63), "E4": (1, 5, 21, 63), "E5": (1, 5, 21, 63), "E6": (5, 21, 63), "E7": (21, 63)}[args.candidate]
        # Reconcile any checkpoints written by the earlier sequential worker
        # into horizon-isolated ledgers before starting parallel workers.
        combined_path = output / f"{args.candidate.lower()}_experiments.jsonl"
        combined_rows = [] if not combined_path.exists() else [json.loads(line) for line in combined_path.read_text(encoding="utf-8").splitlines() if line]
        for horizon in supported:
            split_path = output / f"{args.candidate.lower()}_h{horizon}_experiments.jsonl"
            existing = set()
            if split_path.exists():
                existing = {json.loads(line)["experiment_id"] for line in split_path.read_text(encoding="utf-8").splitlines() if line}
            rows = [row for row in combined_rows if row.get("dataset_hash") == dataset.content_hash and row.get("horizon") == horizon and row["experiment_id"] not in existing]
            if rows:
                with split_path.open("a", encoding="utf-8", newline="\n") as handle:
                    for row in rows:
                        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")

        def run_horizon(horizon: int) -> None:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "select", "--candidate", args.candidate, "--horizon", str(horizon)],
                cwd=root,
                check=False,
                text=True,
                capture_output=True,
            )
            if completed.returncode:
                raise RuntimeError(f"{args.candidate} h{horizon} failed: {completed.stderr[-2000:]}")

        with ThreadPoolExecutor(max_workers=len(supported), thread_name_prefix=f"tsv6-parallel-{args.candidate}") as executor:
            list(executor.map(run_horizon, supported))
        partials = [json.loads((output / f"{args.candidate.lower()}_selection_h{horizon}.json").read_text(encoding="utf-8")) for horizon in supported]
        merged = dict(partials[0])
        merged["implementation_version"] = CANDIDATE_IMPLEMENTATION_VERSION[args.candidate]
        merged["selection"] = {key: value for partial in partials for key, value in partial["selection"].items()}
        merged["selection_hash"] = __import__("hashlib").sha256(json.dumps(merged["selection"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        write_json(output / f"{args.candidate.lower()}_selection.json", merged)
        print(json.dumps({"candidate": args.candidate, "selection_hash": merged["selection_hash"], "parallel_horizons": list(supported)}))
        return 0
    if args.phase == "select":
        if not args.candidate: parser.error("--candidate is required for select")
        suffix = f"_h{args.horizon}" if args.horizon else ""
        result = select_candidate(
            dataset,
            args.candidate,
            output / f"{args.candidate.lower()}{suffix}_experiments.jsonl",
            horizons=(args.horizon,) if args.horizon else None,
            max_workers=3 if args.horizon else 8,
        )
        write_json(output / f"{args.candidate.lower()}_selection{suffix}.json", result)
        print(json.dumps({"candidate": args.candidate, "selection_hash": result["selection_hash"]}))
        return 0
    selections = [
        json.loads(path.read_text(encoding="utf-8"))
        for candidate in ("E1", "E2", "E3", "E4", "E5", "E6", "E7")
        if (path := output / f"{candidate.lower()}_selection.json").exists()
    ]
    choices = {}
    for horizon in (1, 5, 21, 63):
        candidates = [
            {
                "candidate_id": item["candidate_id"],
                "implementation_version": item.get(
                    "implementation_version",
                    CANDIDATE_IMPLEMENTATION_VERSION[item["candidate_id"]],
                ),
                "feature_profile": item["feature_profile"],
                "feature_profile_hash": item["feature_profile_hash"],
                **item["selection"][str(horizon)],
            }
            for item in selections
            if str(horizon) in item["selection"]
        ]
        choices[str(horizon)] = min(candidates, key=lambda row: (row["mean_inner_crps"], row["candidate_id"], row["spec_hash"]))
    if args.phase == "sealed":
        rows = sealed_backtest(dataset, choices)
        selection_payload = {
            "dataset_hash": dataset.content_hash,
            "choices": choices,
            "algorithm_version": "sealed_v6_direct_v3_deterministic_runtime",
            "numeric_runtime": {
                "MKL_NUM_THREADS": 1,
                "NUMEXPR_NUM_THREADS": 1,
                "OMP_NUM_THREADS": 1,
                "OPENBLAS_NUM_THREADS": 1,
                "PYTHONHASHSEED": 0,
            },
        }
        identity = hashlib.sha256(json.dumps(selection_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        run_id = f"tsv6-sealed-{identity[:24]}"
        run_dir = output / "sealed_runs" / run_id
        scores_content = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
        write_immutable(run_dir / "scores.jsonl", scores_content)
        write_immutable(run_dir / "selection.json", json.dumps(selection_payload, ensure_ascii=False, indent=2) + "\n")
        write_immutable(run_dir / "run.json", json.dumps({"schema_version": 1, "run_id": run_id, "status": "sealed_research_evaluation", "row_count": len(rows), "scores_sha256": hashlib.sha256(scores_content.encode()).hexdigest(), **selection_payload}, ensure_ascii=False, indent=2) + "\n")
        legacy = output / "sealed_scores.jsonl"
        if legacy.exists():
            legacy_sha = hashlib.sha256(legacy.read_bytes()).hexdigest()
            append_once(output / "preliminary_run_invalidations.jsonl", {
                "invalidation_id": f"invalidate-{legacy_sha[:24]}",
                "artifact": legacy.relative_to(root).as_posix(),
                "artifact_sha256": legacy_sha,
                "status": "invalid_preliminary_not_sealed",
                "reasons": ["candidate_bundle_E4_E7_incomplete", "integrity_and_operational_coordinates_self_asserted", "initial_training_segment_absent", "target_forward_fill_not_fail_closed"],
            })
        write_json(output / "sealed_latest.json", {"schema_version": 1, "run_id": run_id, "run_path": run_dir.relative_to(root).as_posix(), "scores_path": (run_dir / "scores.jsonl").relative_to(root).as_posix()})
        print(json.dumps({"run_id": run_id, "rows": len(rows), "choices": {key: value["candidate_id"] for key, value in choices.items()}}))
        return 0
    if args.phase == "replay":
        sealed_pointer = json.loads((output / "sealed_latest.json").read_text(encoding="utf-8"))
        run_dir = root / sealed_pointer["run_path"]
        recorded = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        replay_rows = sealed_backtest(dataset, recorded["choices"])
        replay_content = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in replay_rows
        )
        replay_sha = hashlib.sha256(replay_content.encode()).hexdigest()
        expected_sha = recorded["scores_sha256"]
        result = {
            "schema_version": 1,
            "run_id": recorded["run_id"],
            "status": "pass" if replay_sha == expected_sha else "fail",
            "row_count": len(replay_rows),
            "expected_scores_sha256": expected_sha,
            "replayed_scores_sha256": replay_sha,
            "exact_match": replay_sha == expected_sha,
            "numeric_runtime": recorded.get("numeric_runtime"),
        }
        write_json(output / "deterministic_replay.json", result)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["exact_match"] else 1
    sealed_pointer = json.loads((output / "sealed_latest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (root / sealed_pointer["scores_path"]).read_text(encoding="utf-8").splitlines() if line]
    verification = verify_research_run(
        root,
        dataset,
        selections,
        manifest_path=root / "data/timeseries_v6/manifests/public_archive_latest.json",
    )
    write_json(output / "verification_result.json", verification)
    gate = evaluate_research_gate(rows, verification=verification)
    write_json(output / "gate_result.json", gate)
    print(json.dumps({"status": gate["status"], "numbers_visible": gate["numbers_visible"], "reasons": gate["research_gate"]["reasons"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
