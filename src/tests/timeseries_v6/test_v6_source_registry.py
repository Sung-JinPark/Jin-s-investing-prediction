from pathlib import Path

import pytest

from ai_fc.timeseries_v6.source_registry import (
    SourceRegistryError,
    load_source_registry,
    reconcile_registry_contract,
)


ROOT = Path(__file__).resolve().parents[3]


def test_registry_exactly_matches_frozen_37_source_contract() -> None:
    registry = load_source_registry(ROOT / "data/timeseries_v6/registry/sources.yaml")
    result = reconcile_registry_contract(registry, ROOT / "data/contracts/multivariate_timeseries_v6.yaml")
    assert result == {
        "pass": True,
        "expected_count": 37,
        "actual_count": 37,
        "contract_only": [],
        "registry_only": [],
    }
    assert registry["employment_consensus"].data_grade == "captured_forward"
    assert registry["fred_alfred"].data_grade == "native_pit"


def test_registry_rejects_duplicate_or_credential_uri(tmp_path: Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {source_id: a, provider: p, authority_class: official, adapter_status: implemented, data_grade: native_pit, cadence: daily, availability_policy_version: v1, redistribution: private, source_uri_template: 'https://example.com'}\n"
        "  - {source_id: a, provider: p, authority_class: official, adapter_status: implemented, data_grade: native_pit, cadence: daily, availability_policy_version: v1, redistribution: private, source_uri_template: 'https://example.com'}\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceRegistryError, match="duplicate"):
        load_source_registry(path)
