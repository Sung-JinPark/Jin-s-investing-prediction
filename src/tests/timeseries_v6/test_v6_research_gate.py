from ai_fc.timeseries_v6.research_gate import evaluate_research_gate


def test_gate_does_not_turn_good_integrity_into_research_pass() -> None:
    rows = []
    for index in range(40):
        for horizon in (1, 5, 21, 63):
            actual = 0.01 if index % 2 else -0.01
            rows.append({"origin": f"2020-{1 + index % 12:02d}-01-{index}", "horizon": horizon, "actual": actual, "model_crps": 1.0, "baseline_crps": 1.0, "p10": -0.02, "p25": -0.01, "p50": 0.0, "p75": 0.01, "p90": 0.02, "baseline_p10": -0.02, "baseline_p90": 0.02, "stress_regime": "pandemic"})
    result = evaluate_research_gate(rows, provenance_rate=1.0, pit_leakage_count=0, contract_runtime_mismatch_count=0, receipt_observation_link_rate=1.0, operational_pass=True)
    assert result["integrity_gate"]["pass"] is True
    assert result["research_gate"]["pass"] is False
    assert result["numbers_visible"] is False
