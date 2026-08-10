from ai_fc.logical_constraints import detect_constraints


def test_constraints_warn_without_modifying_probabilities() -> None:
    probabilities = {"narrow": .7, "broad": .6, "a": .4, "b": .5}
    original = probabilities.copy()
    warnings = detect_constraints(probabilities, [
        {"type": "subset_of", "questions": ["narrow", "broad"]},
        {"type": "mutually_exclusive_exhaustive", "questions": ["a", "b"]},
    ])
    assert {warning.kind for warning in warnings} == {"subset_of", "mutually_exclusive_exhaustive"}
    assert probabilities == original


def test_mixed_probability_spaces_are_not_combined() -> None:
    warnings = detect_constraints(
        {"physical": .5, "rnd": .6},
        [{"type": "subset_of", "questions": ["physical", "rnd"]}],
        probability_spaces={"physical": "physical_event", "rnd": "risk_neutral_terminal"},
    )
    assert warnings[0].kind == "probability_space_mismatch"
