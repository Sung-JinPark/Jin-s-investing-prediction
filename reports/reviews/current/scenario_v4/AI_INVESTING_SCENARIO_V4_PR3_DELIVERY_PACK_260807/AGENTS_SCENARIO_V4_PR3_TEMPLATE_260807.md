# AGENTS.md — AI Investing Repository Working Rules

## Scope

These instructions apply to the repository root and every nested path unless a more specific nested `AGENTS.md` adds stricter rules.

## System boundary

- This repository is an investment-research and probabilistic-forecasting system.
- It is not an autonomous trading system.
- Do not place trades, call broker order endpoints, or represent outputs as personalized investment advice.
- Do not access, print, or commit secrets, API keys, tokens, credentials, or private account data.

## Official artifacts and ledgers

- `data/scenarios/nasdaq_latest.json` is an official legacy scenario snapshot. Do not modify it during shadow-model work unless the user explicitly authorizes a separately reviewed official refresh.
- Preserve official probabilities, snapshot id, revision, correction lineage, archive, and legacy replay behavior.
- Forecast and calibration ledgers are append-only.
- Do not update or delete existing ledger rows.
- Corrections must be new revisions with an explicit `supersedes` relationship.
- Probability canonical storage unit is a fraction in `[0,1]`; percentage conversion occurs only at UI/report boundaries.
- Do not silently clip invalid probabilities or alter historical rows to make tests pass.

## Point-in-time and lineage

- A forecast may use only information available at or before its registered `as_of`/`available_at` boundary.
- Future-data leakage, vintage leakage, and retrospective source substitution are prohibited.
- Every model input used for a reproducible artifact must have source id, as-of/vintage information, and content hash.
- Do not create an official or shadow forecast from unapproved live market data merely because a network source is reachable.
- External network calls are prohibited unless the user explicitly authorizes the exact source and task.

## Scenario model identity

- A candidate name must match its actual implementation.
- Do not label a legacy GBM wrapper as RCFHS, FHS, GARCH, regime-switching, or any other engine that is not implemented.
- `RCFHS-SB` requires approved PIT history, observable regime calculation, state-conditioned drift, conditional-volatility filtering, standardized empirical residuals, stationary block bootstrap, source-block lineage, continuous path recursion, conditional distributions, and deterministic receipts.
- Static self-declared booleans are not sufficient evidence of a capability.
- A shadow model is never `official` or `champion`.
- Champion promotion requires completed rolling-origin validation and explicit human approval.
- Official scenario weights and shadow candidate implied weights must remain separate.

## Path and distribution integrity

- Do not introduce scenario-specific manual drift, noise, fixed dip dates, endpoint forcing, target-MDD forcing, common residual templates, or year-boundary path splicing merely to make lines look different.
- Year views must be slices of one continuous path process; January 1 is not a model reset.
- A displayed representative line must be an actual ensemble member unless explicitly labelled otherwise.
- Pointwise medians or smoothed composites must not be described as actual paths.
- A scenario fan must be computed from pointwise quantiles of that scenario's conditional ensemble.
- Do not use terminal-percentile sample paths as p25/p50/p75 fan boundaries.
- Enforce preregistered conditional sample-size gates. Never substitute an unconditional fan for a missing conditional fan.
- Quantiles must be monotone at every displayed time point.
- Mixture quantiles must be calculated from mixture samples, not by averaging conditional quantiles.

## Determinism and persistence

- Same input bytes, config, seed, and code version must produce the same canonical payload hash.
- Wall-clock fields such as `generated_at` must not affect the canonical content hash.
- A no-op rebuild must not rewrite `latest`.
- Store and validate source snapshot id, source SHA-256, config SHA-256, and canonical payload SHA-256.
- A candidate built from a stale source must not be displayed as current.
- Validate in memory before atomic write.
- Preserve immutable receipts and archive lineage for replaced or retired shadow artifacts.

## Change discipline

- Use a dedicated branch or permanent worktree for each major effort.
- Do not work directly on `main`.
- Never reset, restore, checkout, clean, stash, delete, or overwrite unrelated user changes.
- Keep changes minimal and within the task's allowed path list.
- Do not mix unrelated monitoring, generated-data, formatting, or refactoring changes into a scenario-model PR.
- Do not add, remove, or upgrade dependencies without explicit approval.
- Do not auto-commit, push, open a PR, or merge unless explicitly requested.

## Batch execution

- Execute only the requested batch.
- Stop after its tests and report.
- Do not continue automatically to the next batch.
- A failed or blocked gate prohibits the next batch.
- Missing required specifications are a hard stop; do not invent a reduced implementation under the requested model name.

## Testing and reporting

- Run targeted tests before and after each change.
- Run the broadest existing suite that the environment supports.
- Classify failures as code failure, environment blocker, data blocker, or pre-existing failure.
- Never weaken or bypass validation to obtain a passing test.
- Report exact commands, exit codes, changed files, symbols, and hashes.
- Verify official snapshot, ledgers, archive, and replay are unchanged after shadow work.
- Review `git diff` and changed-file scope before recommending merge.
