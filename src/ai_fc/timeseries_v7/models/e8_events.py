"""Event local-projection eligibility."""

def eligibility(independent_resolved_events: int) -> dict[str, object]:
    eligible=independent_resolved_events>=60
    return {"independent_resolved_events":independent_resolved_events,"eligible":eligible,"ensemble_weight":None if eligible else 0.0}
