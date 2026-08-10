# Scenario V5.2 event-learning ledger

`events.jsonl` is created on the first accepted normalized event. It is append-only.
Corrections append a new `revision_id` with `supersedes`; existing bytes are never
rewritten. CPI, NFP, FOMC and GDP use registered numerical adapters. Earnings
remain reference-only unless an asset mapping is separately approved.

Use `python -m ai_fc scenario-v5-2-learn-event --input <normalized.json>`.
One successful invocation validates PIT/unit/revision gates, appends the event,
rebuilds the research candidate, verifies it, and refreshes the dashboard output.
Every input requires timezone-aware `published_at`, `available_at`, `as_of`, and
`retrieved_at`, with `published_at <= available_at <= as_of <= retrieved_at`.
This is explicit release ingestion, not a background scraper or unconstrained
online learner.
