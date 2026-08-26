import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v7_r4.open_data_challenger import (
    OpenDataChallengerContract,
    SourceQualification,
)


CONTRACT_PATH = Path("data/timeseries_v7_r4/contracts/open_data_challenger_v1.json")


def test_contract_keeps_every_new_source_out_of_official_gate() -> None:
    contract = OpenDataChallengerContract.from_path(CONTRACT_PATH)

    assert contract.lane == "research_only"
    assert contract.sources
    assert all(source.weight == 0.0 for source in contract.sources)
    assert all(not source.official_gate_eligible for source in contract.sources)
    assert all(not source.preregistered or not source.validated for source in contract.sources)


def test_source_cannot_receive_weight_without_both_approvals() -> None:
    base = dict(source_id="fred_gdp", pit_grade="ALFRED_VINTAGE", license_receipt="receipt", terms_receipt="receipt")

    with pytest.raises(ValueError, match="preregistered and validated"):
        SourceQualification(**base, preregistered=True, validated=False, weight=0.1)
    with pytest.raises(ValueError, match="preregistered and validated"):
        SourceQualification(**base, preregistered=False, validated=True, weight=0.1)


def test_contract_has_pit_and_legal_receipts_and_v8_proposal() -> None:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract = OpenDataChallengerContract.from_mapping(raw)

    assert all(source.pit_grade and source.license_receipt and source.terms_receipt for source in contract.sources)
    assert contract.v8_proposal_required is True
    proposal = Path(contract.v8_proposal_path)
    assert proposal.is_file()
    assert "PROPOSED_NOT_APPROVED" in proposal.read_text(encoding="utf-8")
