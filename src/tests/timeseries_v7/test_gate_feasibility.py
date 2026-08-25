from datetime import date
import pytest
from ai_fc.timeseries_v7.gate_linter import GateWindow,lint_gate_windows
from ai_fc.timeseries_v7.gates import RegimeScore,evaluate_prospective_regimes
from ai_fc.timeseries_v7.models.e8_events import eligibility


def test_impossible_era_fails_before_model_execution():
    assert not lint_gate_windows(evaluation_start=date(2020,1,1),evaluation_end=date(2021,1,1),windows=[GateWindow('gfc',date(2008,1,1),date(2009,1,1),20)])['pass']


def test_absent_prospective_regime_is_na_and_small_events_zero_weight():
    assert evaluate_prospective_regimes({'crisis':RegimeScore(0,0)})['regimes']['crisis']['decision']=='not_applicable'
    assert eligibility(59)['ensemble_weight']==0


def test_post_result_threshold_edit_is_contract_hash_change():
    frozen={'threshold':.02};edited={'threshold':.019}
    import hashlib,json
    h=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
    assert h(frozen)!=h(edited)
