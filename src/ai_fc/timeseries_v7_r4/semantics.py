"""Fail-closed R4 process semantics.

Research underperformance is evidence, not an infrastructure crash.  Only the
enumerated integrity failures terminate the supervisor with a non-zero status.
"""

from __future__ import annotations

HARD_STOPS = {
    "BLOCKED_INPUT_INTEGRITY",
    "BLOCKED_SECURITY",
    "BLOCKED_SECRET_LEAK",
    "BLOCKED_PROTECTED_SCOPE",
    "BLOCKED_GOVERNANCE",
    "CONTROLLER_BUG",
    "DATABASE_CORRUPTION",
    "UNAUTHORIZED_PUBLICATION",
    "UNAUTHORIZED_TRADING",
}

NORMAL_TERMINAL = {
    "REVIEW_PROPOSAL",
    "WAIT_DATA",
    "WAIT_EXECUTION_PERMISSION",
    "WAIT_HUMAN_REVIEW",
}
CONTINUE_STATES = {
    "REPLAN",
    "RETRY_WAIT",
    "DATA_REFRESH",
    "ENGINEERING_FIX",
    "RESEARCH_SCREEN",
    "NEW_GENERATION",
    "RESEARCH_GATE_FAILED_REPLAN",
}


def classify_outcome(state: str) -> tuple[str, int, bool]:
    """Return ``(normalized_state, exit_code, supervisor_should_continue)``."""
    normalized = state.strip().upper()
    if normalized in {"HOLD_RESEARCH_GATE", "RESEARCH_GATE_FAILED", "GATE_FAILED"}:
        return "RESEARCH_GATE_FAILED_REPLAN", 0, True
    if normalized in HARD_STOPS:
        return normalized, 2, False
    if normalized in NORMAL_TERMINAL:
        return normalized, 0, False
    if normalized in CONTINUE_STATES or normalized == "SUCCEEDED":
        return normalized, 0, True
    return "CONTROLLER_BUG", 2, False
