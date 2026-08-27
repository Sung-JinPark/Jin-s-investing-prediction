"""V8R governance and qualification infrastructure.

This package deliberately contains no collectors, feature builders, model fitting,
or outer-test access.  DV-1 remains unresolved.
"""

from .governance import (
    CandidateRegistry,
    CorrelationDecision,
    RegistryIntegrityError,
    UnregisteredCandidateError,
    evaluate_feature_correlation,
    feature_budget_limit,
)
from .qualification import benjamini_hochberg, cscv_pbo, horizon_mde

__all__ = [
    "CandidateRegistry",
    "CorrelationDecision",
    "RegistryIntegrityError",
    "UnregisteredCandidateError",
    "benjamini_hochberg",
    "cscv_pbo",
    "evaluate_feature_correlation",
    "feature_budget_limit",
    "horizon_mde",
]
