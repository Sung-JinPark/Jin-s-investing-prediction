# NASDAQ V7 R4 bootstrap execution

- Run: `v7r4-20260826T003326Z`
- Branch: `codex/timeseries-v7-r4`
- Authoritative control plane: PostgreSQL schema `timeseries_v7_r4`
- Current process state: `WAIT_DATA`
- Research Gate: not evaluated and not passed
- Publication/trading: disabled

## Completed

- P0-001/P0-002 review-pack hash and embedded results were independently imported.
- The previously untracked P0 audit source was frozen in commit `5826c80`.
- PostgreSQL task, attempt, lease, fencing, heartbeat, event, receipt, and backlog tables were migrated.
- Research-Gate failure maps to `RESEARCH_GATE_FAILED_REPLAN` with exit code 0.
- The 105-task R3 backlog was imported as a dormant catalog; it was not silently executed.
- P0-003 was recorded as an append-only correction superseding the original baseline without mutating it.
- P0-004 was recorded in versioned runtime manifests after dependency remediation.
- FRED NASDAQCOM was captured with a content-addressed raw object and session-aware receipt.
- The broad suite passed: 607 passed, 30 skipped.
- R4 targeted supervisor tests passed: 33 passed.

## Honest stop boundary

The infrastructure tasks completed. The next D1 research task requires a new isolated Codex child. This side conversation is not authorized to create or interact with sub-agents, so the run stopped normally at `WAIT_DATA`; no model result or Gate success was fabricated.

Resume from an authorized primary session:

```powershell
$env:RALPH_V7_R4_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/v7r4'
$env:R4_ALLOW_CODEX_CHILD='1'
.\.runtime\v7r4\Scripts\python.exe tools\ralph_v7_r4.py resume `
  --run-id v7r4-20260826T003326Z `
  --auto-codex --continuous `
  --until REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK
```

The child still receives one task only. The parent Supervisor validates its result and continues.
