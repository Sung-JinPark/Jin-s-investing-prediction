# PR3A-R4 Review Evidence Package

## 1. Scope

This report closes PR3A-R4 for the Scenario Graph V4 semantic remediation. It packages the R0-R3 implementation evidence without promoting the legacy diagnostic, changing the official snapshot, or claiming that a true RCFHS-SB model exists.

## 2. Gate Summary

**PASS WITH WARNING.** The implementation, persistence, UI semantic, official-data immutability, and regression gates pass. The warning is a documentation allowlist omission: the pre-existing contract test `src/tests/test_scenario_v4_shadow.py` had to change with the explicitly allowed compatibility module `src/ai_fc/scenario_v4_shadow.py`. The change is directly scoped, behavior-based, and included in all test evidence; it is not an unrelated refactor.

True RCFHS-SB remains blocked until an approved point-in-time history contract and data source exist. The active candidate is explicitly `legacy_gbm_actual_member_v1`, shadow-only, not official, not champion, and not RCFHS.

## 3. Evidence Produced

The review package contains:

- the complete source diff, excluding the package's own generated directory and ZIP;
- a name/status changed-path inventory and a scope-gate receipt;
- command receipts with command, exit code, stdout, and stderr;
- targeted and full pytest logs plus JavaScript syntax validation;
- official snapshot before/after hashes;
- retired-artifact byte hash and the new candidate file/canonical hashes;
- independently reproduced no-op refresh and stale-source blocking receipts;
- dashboard semantic evidence;
- all R0-R4 reports and core retirement/candidate artifacts;
- a JSON Lines manifest of every non-manifest package entry.

The ZIP SHA-256 is stored in the adjacent `.zip.sha256` sidecar to avoid a self-referential archive hash.

## 4. Fixed Identities and Hashes

| Item | SHA-256 |
| --- | --- |
| Official snapshot before/after | `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c` |
| Retired misidentified artifact bytes | `cd2bb86b37b2e9cbe6c5c370e3bbd3cc6f21a8953727732c8b4fc27590ee70ca` |
| New candidate file | `922a3c7c2200f2a55f360becdc29c0d190104bc70e1bf80a4de28cb08c843411` |
| New candidate canonical payload | `2b0895ccc58ec44b585305f0afa6b974aa15546d05676af0250e75044c68ed57` |

## 5. Test Results Before Packaging

| Command class | Result |
| --- | --- |
| Scenario/dashboard/read-model/inventory integration | `97 passed` |
| Repository full suite | `393 passed, 30 skipped` |
| R2/R3 focused behavior regression | `40 passed` |
| scoped `git diff --check` | PASS for implementation and generated R0-R4 evidence paths |

The package builder reruns the material reproduction, targeted, full-suite, JavaScript, and scoped diff checks and records their raw outputs and exit codes. Supplied prompt/audit source documents are hash-preserved; their intentional Markdown hard-break spaces are not rewritten merely to satisfy a whitespace linter.

## 6. Independent Review Checklist

1. No active artifact or UI state identifies the candidate as RCFHS.
2. No shadow UI state identifies the candidate as official or champion.
3. Retired bytes are preserved under the shadow archive with their original hash.
4. Full legacy matrix reproduction, exact counts, retained members, and daily cells pass.
5. Conditional quantiles are pointwise and monotone; S2 is p50-only.
6. Representatives are actual cohort rows and pass the multi-metric gates.
7. Canonical hashing ignores receipt time; the second identical refresh is a byte-stable no-op.
8. Stale source blocks price-data display.
9. Dashboard candidate metadata and chart source use one state-driven view model.
10. Conditional and joint unconditional distributions are separate.
11. The diagnostic view contains no official structural baseline or lookup layer.
12. Official snapshot, ledger, calibration, forecast history, and official archive paths remain unchanged.

## 7. Duplicate and Structure Review

The delivery template, delivery README, and delivery-pack manifest were execution inputs rather than implementation outputs and were not retained in this branch. `AGENTS.md` is the single active repository instruction file. The old active misidentified artifact was moved byte-for-byte to one archive location and paired with one retirement receipt; there is no duplicate active copy.

## 8. Verification Command

```powershell
python tools/verify_scenario_shadow_package.py --verify
```

The verifier rejects missing, extra, zero-byte, size-mismatched, or hash-mismatched package entries and validates the ZIP against the same manifest and its SHA-256 sidecar.

## 9. Rollback

Rollback is code-only: remove the diagnostic read-model/UI wiring and candidate builder while retaining the R1 retirement record. No official or historical data rollback is required because those paths were never changed.
