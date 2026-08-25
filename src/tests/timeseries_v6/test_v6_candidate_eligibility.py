import json

from ai_fc.timeseries_v6.candidate_eligibility import evaluate_deferred_candidates


def test_deferred_candidates_remain_zero_weight_without_receipts(tmp_path) -> None:
    result = evaluate_deferred_candidates(tmp_path)
    assert result["all_ineligible_zero_weight"] is True
    assert result["candidates"]["E8"]["resolved_independent_event_count"] == 0
    assert result["candidates"]["E9"]["weight"] == 0.0
    assert result["candidates"]["E10"]["weight"] == 0.0


def test_event_candidate_only_becomes_eligible_at_sixty_independent_receipts(tmp_path) -> None:
    path = tmp_path / "data/timeseries_v6/events/resolved_events.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {
            "independent_event_id": f"event-{index}",
            "resolved": True,
            "pre_event_snapshot_receipt_id": f"receipt-{index}",
        }
        for index in range(60)
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = evaluate_deferred_candidates(tmp_path)
    assert result["candidates"]["E8"]["eligible"] is True
    # Eligibility does not autonomously assign model weight.
    assert result["candidates"]["E8"]["weight"] == 0.0
