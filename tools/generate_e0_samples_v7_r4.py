"""Generate and replay frozen E0 samples from an authoritative PIT evidence pack."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_fc.timeseries_v7_r4.e0_empirical_samples import (
    E0_BLOCK_BOOTSTRAP_CONTRACT,
    EvaluationPath,
    generate_e0_samples,
)
from ai_fc.timeseries_v7_r4.integrity import canonical_json, sha256_bytes

SNAPSHOT_SUFFIX = "/pit_snapshot.parquet"
LABEL_SUFFIX = "/direct_labels.parquet"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _only_name(names: list[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {suffix} member")
    return matches[0]


def generate(pack_path: Path, nested_member: str, *, expected_sha256: str,
             sample_count: int, root_seed: int) -> dict[str, object]:
    observed_hash = file_sha256(pack_path)
    if observed_hash != expected_sha256:
        raise ValueError("evidence-pack hash mismatch")
    with zipfile.ZipFile(pack_path) as outer:
        nested_bytes = outer.read(nested_member)
    nested_hash = hashlib.sha256(nested_bytes).hexdigest()
    with zipfile.ZipFile(io.BytesIO(nested_bytes)) as evidence:
        names = evidence.namelist()
        snapshot = pd.read_parquet(io.BytesIO(evidence.read(_only_name(names, SNAPSHOT_SUFFIX))))
        labels = pd.read_parquet(io.BytesIO(evidence.read(_only_name(names, LABEL_SUFFIX))))

    required_snapshot = {"origin_session", "origin_cutoff_at", "max_available_at", "pit_pass", "ret_1"}
    if not required_snapshot.issubset(snapshot.columns):
        raise ValueError("PIT snapshot lacks required E0 columns")
    snapshot = snapshot.sort_values("origin_session", kind="stable")
    if snapshot["origin_session"].astype(str).duplicated().any():
        raise ValueError("PIT snapshot contains duplicate origins")
    pit_valid = (
        snapshot["pit_pass"].eq(True)
        & (pd.to_datetime(snapshot["max_available_at"], utc=True)
           <= pd.to_datetime(snapshot["origin_cutoff_at"], utc=True))
    )
    if not bool(pit_valid.all()):
        raise ValueError("PIT snapshot violates available_at at an E0 input origin")

    labels = labels.copy()
    labels["origin_session"] = labels["origin_session"].astype(str)
    snapshot_sessions = snapshot["origin_session"].astype(str)
    finite_returns = snapshot["ret_1"].notna()
    return_sessions = snapshot_sessions[finite_returns].tolist()
    return_values = snapshot.loc[finite_returns, "ret_1"].astype(float).tolist()
    coordinates: list[dict[str, object]] = []
    for horizon in (1, 5, 21, 63):
        value_column = f"h{horizon}"
        end_column = f"h{horizon}_label_end_session"
        mature = labels[value_column].notna() & labels[end_column].notna()
        row = labels.loc[mature].iloc[-1]
        origin = str(row["origin_session"])
        samples = generate_e0_samples(
            origin_session=origin,
            horizon_sessions=horizon,
            sessions=return_sessions,
            one_session_returns=return_values,
            sample_count=sample_count,
            root_seed=root_seed,
        )
        path = EvaluationPath.bind(samples)
        actual = float(row[value_column])
        artifacts = [
            path.score(actual=actual), path.stacking_input(),
            path.calibration_input(), path.forecast(),
        ]
        if len({item.sample_set_hash for item in artifacts}) != 1:
            raise AssertionError("evaluation stages did not preserve sample identity")
        coordinates.append({
            "origin_session": origin,
            "horizon_sessions": horizon,
            "label_end_session": str(row[end_column]),
            "actual": actual,
            "sample_set": samples.receipt(),
            "stage_sample_set_hashes": {
                item.stage: item.sample_set_hash for item in artifacts
            },
            "empirical_crps": artifacts[0].value,
        })

    payload: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "e0_sample_matrix",
        "contract": dict(E0_BLOCK_BOOTSTRAP_CONTRACT),
        "source": {
            "evidence_pack": str(pack_path),
            "evidence_pack_sha256": observed_hash,
            "nested_member": nested_member,
            "nested_member_sha256": nested_hash,
            "pit_row_count": int(len(snapshot)),
            "mature_label_count": int(sum(labels[f"h{h}"].notna().sum() for h in (1, 5, 21, 63))),
        },
        "sample_count_per_coordinate": sample_count,
        "root_seed": root_seed,
        "coordinates": coordinates,
    }
    payload["matrix_hash"] = sha256_bytes(canonical_json(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--pack-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=20_000)
    parser.add_argument("--root-seed", type=int, default=7_002)
    args = parser.parse_args()
    payload = generate(
        args.pack, args.nested_member, expected_sha256=args.pack_sha256,
        sample_count=args.sample_count, root_seed=args.root_seed,
    )
    output = args.output_root / f"{payload['matrix_hash']}.json"
    encoded = canonical_json(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise ValueError("content-addressed artifact collision")
    else:
        output.write_bytes(encoded)
    json.dump({
        "artifact": output.as_posix(),
        "matrix_hash": payload["matrix_hash"],
        "coordinates": len(payload["coordinates"]),
        "sample_count_per_coordinate": payload["sample_count_per_coordinate"],
    }, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
