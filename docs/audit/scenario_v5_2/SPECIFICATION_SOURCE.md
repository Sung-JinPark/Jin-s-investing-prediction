# Scenario V5.2 specification source

The implementation and audit were performed against the user-supplied Korean
specification `AI Investing Scenario V5.2 — Macro-Actualized Historical-Shape
Forecast Engine`, attached to the Codex task as:

`C:/Users/91ssj/.codex/attachments/115bfb40-b8f0-42c5-9360-e790ceba3b6b/pasted-text.txt`

The source was read as UTF-8. Its governing constraints were:

- execute Phase A through Phase H in gate order;
- prove that the July 2026 employment actual was absent from V5.1;
- ingest BLS actuals/revisions and full pre/post Fed target-range distributions;
- separate growth-risk and policy-relief effects;
- block event-day price-reaction double counting;
- compare prior-only, labor-only, labor+rate, and full-evidence outputs;
- show the total mixture in the main chart and S1/S2/S3 only as conditional
  small multiples;
- keep p50 free of artificial wiggles and show actual central members;
- treat October 2 as an ordinary first-touch CDF coordinate, not an exact-date
  forecast;
- preserve official snapshot, ledger, and archive bytes.

The 2026-08-10 owner instruction added a bounded, scenario-specific dotcom
analog view and a validated append-only event update boundary. The approved
dotcom strengths are S1 0.28, S2 0.04, and S3 0.06, with the single-cycle
dependency limitation disclosed and capped at 0.35.

This copy is a scope/provenance summary, not a replacement for the original
attached specification.
