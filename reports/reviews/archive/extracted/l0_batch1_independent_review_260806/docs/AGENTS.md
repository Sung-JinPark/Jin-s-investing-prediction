# AI Investing Repository Instructions

## Scope and system boundaries

- This repository is an investment-research and probabilistic-forecasting system. It is not an automated-trading system.
- Do not place real orders, call live broker or securities APIs, or access secrets, API keys, or tokens without explicit user authorization.
- Keep changes narrowly scoped to the requested work. Do not perform unrelated refactors, broad formatting, or silent data migrations.

## Probability contract

- The canonical stored probability unit is a fraction in the inclusive range `[0, 1]`.
- Percentages may be used only at UI and report-output boundaries. Convert explicitly at those boundaries.
- Never infer a probability unit from magnitude alone. Require explicit unit metadata at ingestion and correction boundaries.
- Never use silent clipping, silent normalization, or data hiding to make validators or tests pass. Reject invalid data with an auditable reason.

## Point-in-time and data-vintage integrity

- A forecast may use only information whose `available_at` is on or before its `as_of` timestamp.
- Never use observations, revisions, filings, or derived values that became available after the forecast `as_of`.
- Future-data leakage and data-vintage leakage are prohibited. Preserve source timestamps and the vintage used by the model.

## Ledger and correction integrity

- Ledgers are append-only. Existing rows must never be updated or deleted.
- Corrections must be recorded as a new revision with an explicit `supersedes` relationship to the prior revision.
- Preserve the original invalid or superseded row for auditability; read models may select an approved latest revision without mutating source history.
- Do not rewrite forecast, calibration, benchmark, cost, or correction history to improve reported results.

## Official forecast gates

- Write an official forecast only for a valid registered question that is in an explicitly allowed state, is not expired, and has an allowed research status.
- A HOLD, invalid, unresolved-preflight, expired, or degraded-research question must not reach the official forecast or benchmark ledger.
- Validate probability bounds, confidence-interval containment, and `anchor + signed adjustments = final probability` before any official append.
- Recheck write-time gates immediately before the append boundary when state or time can change during a run.

## Model and structural-path changes

- Any change to model output, forecast probability, scenario path, calibration, or structural path requires shadow validation against the existing result before promotion.
- Shadow validation must preserve comparable inputs, report changed outputs and tolerances, and must not overwrite the current official snapshot.
- A display-only change must remain semantically distinguishable from a model or probability change.

## Implementation and testing discipline

- Prefer existing test patterns, validators, error types, append helpers, and exception-handling conventions.
- Add the smallest validator or guard at the earliest reliable boundary, with defense-in-depth at the official write boundary where appropriate.
- After a change, run targeted tests first and then the broadest practical full suite.
- Report failures separately as code defects, environment or dependency problems, and missing-data or artifact problems.
- Do not install, remove, or upgrade dependencies unless the user explicitly authorizes it.
- Tests must not mutate durable databases, official snapshots, or ledger rows. Use temporary paths, fixtures, or disposable copies.
