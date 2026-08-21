"""NASDAQ multivariate time-series V2 research system.

V2 is deliberately isolated from the official forecast and Scenario V5.2
probability spaces.  It may publish customer-facing research numbers only after
its preregistered PIT and sealed evaluation gates pass.
"""

from .contracts import TimeSeriesV2ContractError, load_contract_v2

__all__ = ["TimeSeriesV2ContractError", "load_contract_v2"]
