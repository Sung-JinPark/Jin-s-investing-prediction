"""Fixed v1 selection/evaluation knobs cannot silently diverge from code."""
from pathlib import Path

import pytest
import yaml

from ai_fc.market_context import contracts as C


@pytest.mark.parametrize("section,key,replacement", [
    ("model", "ridge_candidates", [1., 10.]),
    ("model", "inner_purge_sessions", 21),
    ("model", "inner_embargo_sessions", 0),
    ("model", "lookback_sessions", 126),
    ("model", "primary_horizon", 63),
    ("model", "additional_daily_residual_noise", True),
    ("representative", "eligible_percentile_ranges", [[0., 1.]] * 5),
    ("representative", "relaxation", "allowed"),
    ("representative", "smoothing", "spline"),
    ("evaluation", "minimum_relative_crps_improvement", 0.),
    ("evaluation", "minimum_matured_pit_origins", 30),
    ("evaluation", "one_sided_confidence", .9),
])
def test_fixed_numerical_selection_and_evaluation_contract_is_enforced(tmp_path, section, key, replacement):
    source = Path(__file__).resolve().parents[2] / C.CONTRACT_RELATIVE
    destination = tmp_path / C.CONTRACT_RELATIVE
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())
    contract = C.load_contract(tmp_path)
    contract[section][key] = replacement
    destination.write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(C.MarketContextError, match="contract differs"):
        C.load_contract(tmp_path)
