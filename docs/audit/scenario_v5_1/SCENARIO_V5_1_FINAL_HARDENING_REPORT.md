# Scenario V5.1 Final Hardening Report

## Executive verdict

V5.1 is an additive research candidate. Runtime/source/PIT gates pass at build time; current approved numerical evidence count is **0**. V5.1 merge recommendation is **YES**. It is not official and not a champion.

## Phase 0–3 — Safety and baseline

- Official snapshot SHA: `d8754e6a7d1eed4aa46c17625b7ba1e7b1554a4e9799404128d64e3277be75bc`
- Protected manifest before/after: `2e2f879733f4f6bc8d350af9a683917161234dd4ba2f59cbf4a4fef463d712d4` / `2e2f879733f4f6bc8d350af9a683917161234dd4ba2f59cbf4a4fef463d712d4`
- Legacy V5 baseline was independently replayed without overwriting its artifact.
- 10/2 is the five-session dashboard coordinate nearest a sampled member movement, not an exact-date forecast. The baseline S1 daily trough is 2026-10-01.

## Phase A — Runtime integrity

- Exact current snapshot identity and SHA, every evidence source SHA, PIT cutoff, future-build, and one-trading-day freshness are checked.
- Model content SHA: `b3302fcb9dbc54957a65a5df3d0933cd209da1b645ab1f2cb3898bae152fbe68`
- Build receipt SHA: `5f1e75da1a99e488b4ca62b4160bd5a85820c726537f42ee0859487603c9a984`
- Strict validation result: `True`

## Phase B–C — Time alignment, circularity, dependency, evidence

- Numerical views: 0; reference/blocked views: 9.
- 62% ATH and 63% EOY views are `REFERENCE_ONLY_ENDOGENOUS`.
- 57% correction view is `BLOCKED_NEEDS_REFORECAST`; no unconditional started-window reuse or freshness-decay substitute is allowed.
- Dependency caps/dedup are applied before solver input. Current LOO matrices are empty because every prospective numerical view is blocked.
- Options/markets are reference only; events have zero price jumps; liquidity/cross-asset/AI adapters are explicitly NOT USED NUMERICALLY.

## Phase D — Display semantics

- Thick solid: conditional weighted p50.
- Thin dotted: ONE SIMULATED MEMBER / EXACT DATES ARE NOT FORECAST.
- Fans are ESS gated and hidden bands do not enter their mini-panel scale.
- Risk ribbon means `-10%선 누적 터치확률 저/중/고`.
- Correction panel reports any-touch, first-touch density/CDF, and conditional p25/median/p75.

## Phase E — 2027 distinctness

- Gate pass: `False`.
- Disclosure: `2026: scenario-specific conditional distribution; 2027: common-model continuation; scenario-specific starting level only`.
- Three distinct 2027 continuation lines are blocked when the distribution-distance gate fails.

## Phase F — Prior risk

- 252-session sample drift is not promoted as a settled prior.
- Drift retention 0/0.5/1, path counts 40k/100k/200k, and 10 seeds were run.
- Exact-date stability pass: `False`; exact dates remain suppressed.
- PIT-dependent lookbacks 252/504/756/1260, block length, regime threshold, EWMA/GARCH/RCFHS are blocked rather than fabricated.

## Phase G — Verification

- Test status: `PASS`.
- Browser evidence count: 6.

## Final gate

- Protected unchanged: `True`
- Candidate valid: `True`
- Browser evidence present: `True`
- Merge recommendation: **YES — research candidate only, human review required**
- V6 promotion: **BLOCKED**.
