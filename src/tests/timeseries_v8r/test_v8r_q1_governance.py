from __future__ import annotations

import json

import pytest

from ai_fc.timeseries_v8r.governance import (
    CandidateRegistry,
    RegistryIntegrityError,
    UnregisteredCandidateError,
    evaluate_feature_correlation,
    feature_budget_limit,
)


def test_registry_is_append_only_hash_chained_and_blocks_unregistered(tmp_path):
    path = tmp_path / "registry.jsonl"
    registry = CandidateRegistry(path)
    first = registry.register(
        candidate_id="VRP_t",
        hypothesis="VRP improves conditional scale",
        expected_effect="positive CRPS advantage at h1/h5",
        feature_ids=["VRP_t"],
        registered_at="2026-08-27T00:00:00Z",
    )
    second = registry.register(
        candidate_id="TS_t",
        hypothesis="term structure identifies stress scale",
        expected_effect="improved lower-tail coverage",
        feature_ids=["TS_t"],
        registered_at="2026-08-27T00:01:00Z",
    )
    assert second["previous_record_sha256"] == first["record_sha256"]
    assert registry.require_registered("VRP_t")["status"] == "REGISTERED_NOT_EVALUATED"
    with pytest.raises(UnregisteredCandidateError):
        registry.require_registered("POST_HOC_WINNER")
    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            candidate_id="VRP_t", hypothesis="duplicate", expected_effect="duplicate",
            registered_at="2026-08-27T00:02:00Z",
        )

    rows = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[0])
    tampered["hypothesis"] = "tampered after evaluation"
    rows[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(RegistryIntegrityError):
        registry.rows()


def test_feature_budget_uses_effective_sample_and_hard_cap():
    assert feature_budget_limit(origins=1025, horizon=63) == 3
    assert feature_budget_limit(origins=2400, horizon=1) == 8
    with pytest.raises(ValueError):
        feature_budget_limit(origins=0, horizon=1)


def test_correlation_check_is_train_only_and_rejects_absolute_rho_above_contract():
    candidate = [1.0, 2.0, 3.0, 4.0, 5.0]
    rejected = evaluate_feature_correlation(
        candidate, {"existing": [2.0, 4.0, 6.0, 8.0, 10.0]},
        role="research_train",
    )
    assert rejected.accepted is False
    assert rejected.conflicting_feature == "existing"
    accepted = evaluate_feature_correlation(
        candidate, {"existing": [1.0, -2.0, 3.0, -4.0, 5.0]},
        role="research_train",
    )
    assert accepted.accepted is True
    with pytest.raises(ValueError, match="research_train"):
        evaluate_feature_correlation(candidate, {"x": candidate}, role="outer_test")
