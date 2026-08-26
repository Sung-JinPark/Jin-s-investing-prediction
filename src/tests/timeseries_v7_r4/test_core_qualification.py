from __future__ import annotations

from pathlib import Path

from ai_fc.timeseries_v7_r4.core_qualification import (
    GATE_NAMES,
    QualificationAlreadyConsumed,
    compute_gate_evidence,
    qualify_once,
)


def test_frozen_score_matrix_uses_registered_v7_gate_method():
    import pyarrow.parquet as pq

    rows = pq.read_table(
        "outputs/timeseries_v7_r4/R4-M3-008/score_matrix.parquet"
    ).to_pylist()
    evidence = compute_gate_evidence(rows)

    assert evidence["gate_methodology"] == {
        "method": "moving_block_bootstrap",
        "seed": 20260825,
        "replications": 1000,
        "block_length": 13,
        "upper_quantile": 0.90,
    }
    assert evidence["metrics"]["paired_ci_upper"] == 0.0006826855070338302
    assert {
        name: (value["count"], value["coverage80"])
        for name, value in evidence["metrics"]["historical_stress"].items()
    } == {
        "gfc": (416, 0.7668269230769231),
        "pandemic": (84, 0.4523809523809524),
        "tightening_2022": (208, 0.6394230769230769),
        "rebound_2009": (224, 0.8660714285714286),
        "rebound_2020": (192, 0.7552083333333334),
        "bull_2023": (208, 0.8942307692307693),
    }


def test_qualification_is_once_only_complete_and_routes_gate_failure(tmp_path):
    rows = [
        {"origin_session": "2020-01-03", "horizon": 21, "actual": -0.02,
         "model_crps": 0.03, "baseline_crps": 0.02, "p10": -0.01,
         "p25": -0.005, "p50": 0.001, "p75": 0.005, "p90": 0.01,
         "probability_up": 0.8},
        {"origin_session": "2020-01-10", "horizon": 63, "actual": 0.02,
         "model_crps": 0.03, "baseline_crps": 0.02, "p10": -0.01,
         "p25": -0.005, "p50": -0.001, "p75": 0.005, "p90": 0.01,
         "probability_up": 0.2},
    ]
    rows.extend([{**rows[0], "horizon": horizon} for horizon in (1, 5)])
    result = qualify_once(
        rows, checkpoint_dir=tmp_path, generation_key="frozen-generation",
        identity={"r4_snapshot_hash": "a" * 64, "e0_artifact_sha256": "b" * 64,
                  "g1_artifact_sha256": "c" * 64, "g2_artifact_sha256": "d" * 64},
        screening_qualification_rows=0,
        router_path=Path("data/timeseries_v7_r4/ralph/spec/"
                         "NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml"),
    )

    assert result["qualification_count"] == 1
    assert result["screening_qualification_rows"] == 0
    assert set(result["gate_results"]) == set(GATE_NAMES)
    assert set(result["gate_deficit_vector"]) == set(GATE_NAMES) - {"coverage50_high"}
    assert result["decision"] == "HOLD_RESEARCH_GATE"
    assert result["reason"] == "RESEARCH_GATE_FAILED_REPLAN"
    assert result["process_exit_code"] == 0
    assert result["routed_tasks"]
    try:
        qualify_once(rows, checkpoint_dir=tmp_path, generation_key="frozen-generation",
                     identity=result["identity"], screening_qualification_rows=0,
                     router_path=Path("data/timeseries_v7_r4/ralph/spec/"
                                      "NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml"))
    except QualificationAlreadyConsumed:
        pass
    else:
        raise AssertionError("qualification exposure was silently reused")
