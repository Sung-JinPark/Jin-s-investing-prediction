"""Scenario shadow contracts and deterministic legacy diagnostics."""

from .contracts import (
    RCFHS_REQUIRED_CAPABILITIES,
    ScenarioShadowContractError,
    validate_candidate_payload,
    validate_model_identity,
)

__all__ = [
    "RCFHS_REQUIRED_CAPABILITIES",
    "ScenarioShadowContractError",
    "validate_candidate_payload",
    "validate_model_identity",
]
