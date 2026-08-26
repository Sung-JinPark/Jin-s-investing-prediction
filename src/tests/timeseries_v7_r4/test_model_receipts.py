import pytest

from ai_fc.timeseries_v7_r4.model_receipts import (
    emit_model_receipts,
    verify_model_receipts,
)


def _row(origin="2026-08-25", horizon=5):
    return {
        "origin_session": origin,
        "horizon_sessions": horizon,
        "selection_hash": "1" * 64,
        "stacking_hash": "2" * 64,
        "calibration_hash": "3" * 64,
        "sample_set_hash": "4" * 64,
    }


def test_receipt_binds_every_origin_horizon_and_all_lineage_hashes():
    receipt = emit_model_receipts(
        [_row(), _row("2026-08-26", 10)],
        contract_hash="a" * 64, code_hash="b" * 64,
        runtime_hash="c" * 64, data_hash="d" * 64,
    )
    assert len(receipt["origin_horizon_receipts"]) == 2
    assert receipt["binding_hash"]
    assert verify_model_receipts(receipt) == receipt

    receipt["contract_hash"] = "e" * 64
    with pytest.raises(ValueError, match="binding hash"):
        verify_model_receipts(receipt)


def test_missing_or_duplicate_origin_horizon_receipt_fails_closed():
    with pytest.raises(ValueError, match="receipt is required"):
        emit_model_receipts([], contract_hash="a" * 64, code_hash="b" * 64,
                            runtime_hash="c" * 64, data_hash="d" * 64)
    with pytest.raises(ValueError, match="selection_hash"):
        emit_model_receipts([{k: v for k, v in _row().items() if k != "selection_hash"}],
                            contract_hash="a" * 64, code_hash="b" * 64,
                            runtime_hash="c" * 64, data_hash="d" * 64)
    with pytest.raises(ValueError, match="duplicate"):
        emit_model_receipts([_row(), _row()], contract_hash="a" * 64,
                            code_hash="b" * 64, runtime_hash="c" * 64,
                            data_hash="d" * 64)
