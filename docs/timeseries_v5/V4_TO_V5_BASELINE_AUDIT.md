# V4 → V5 baseline reproduction audit

- Task: `V5-P0-001`
- Scope: V4 immutable benchmark reproduction only
- Reproduction: **PASS**
- V4 benchmark decision: **shadow_gate_hold**
- V5 model/controller/storage implementation: not started in this task

## Immutable identities

| Coordinate | Recomputed value | Match |
|---|---|---|
| V4 run | `tsv4-research-bd2ac04e8f0a985d22628a2a` | yes |
| V4 content hash | `a22782051c21fd5f3ded735ae8edf03cb2837efc8886ad528e1ebd35799115eb` | yes |
| V4 contract hash | `1a4d8df3ad513f4b229b5df147786cdcabc573c58dfe385b8f60c93ba595c5a0` | yes |
| V4 model-code hash | `eaffd249815f3c2dab5ae8d0f070403aa675c312b3573d6baf508d2c75741662` | yes |
| V3 predecessor content hash | `74591b18cc845459f2572a301c7686cd7e6fc565ac46a0f813b00eeb785ad2b4` | yes |
| Review ZIP | `58911b7b042c34e25075a8933350c8d2699b26e6795d4c80d29d42f1454f1f2c` | yes |

## Recomputed scores

| Horizon | V4 CRPS | Fixed comparator | Improvement | p10–p90 coverage | actual below median |
|---:|---:|---:|---:|---:|---:|
| 1 | 0.007152582660 | 0.007204831088 | 0.725186% | 82.866044% | 49.013499% |
| 5 | 0.014968283096 | 0.015113823780 | 0.962964% | 83.385254% | 48.494289% |
| 21 | 0.029962846693 | 0.030049342246 | 0.287845% | 84.319834% | 44.755971% |
| 63 | 0.050939543438 | 0.051817597656 | 1.694510% | 84.215992% | 42.263759% |

- Complete grid: 963 origins × 4 horizons = 3852 rows.
- Duplicate origin/horizon: 0.
- Quantile monotonicity violations: 0.
- 21/63 mean CRPS improvement: 0.991177%; frozen Gate: 2.000000%.
- Paired overlap-aware 90% CI: `[-0.0008818872507811194, -0.00011310706618509497]`.
- Gate reasons: 21/63 fixed-baseline mean CRPS improvement is below 2%, extreme-move Q4 coverage gate failed, a required stress regime coverage is below 70%.

## Source and PIT findings

- Receipts: 72; observations: 113615; fact→receipt linkage: 100.000000%.
- Receipts with facts: 35; without fact links: 37.
- Explicit terminal parse outcomes: 0/72. V4 has no terminal-outcome ledger, so this is not 100% terminal coverage.
- Revision distribution: `{'1': 113615}`; supersedes: 0.
- Observations available after 16:00 ET: 57973.
- Fed-rate rows: 30; independent snapshots: 2; snapshot×meeting identities: 6.
- NFP consensus pre-release eligibility: **False** — consensus and actual share the same availability timestamp.
- V4 feature alignment converts `available_at` to a New York date, so the 16:00 boundary cannot be proven by the current feature view.

## Model proof

The V4 code applies `median + scale × (samples − median)` using scales 0.85/1.10/1.60. The synthetic median-preservation error is 0.0e+00. It changes scale only; it does not learn location, direction, or regime transition.

## Pack comparison and safety

- Pack numeric mismatches: 0.
- Review-pack manifest errors: 0.
- The separately supplied V5 blueprint delivery is verified by `input_blueprint_verification.json`.
- Protected baseline: 4951 files, 259763052 bytes, manifest `d25bb1ec803c387057b8892dbc790a47a124871dfbd780129bce6d34ab5a66e1`.
- V4 remains `shadow_gate_hold`; customer numbers, automatic promotion, publication, and trading remain disabled.
- No provider credential is needed or read by this reproducer.

## Tests

- Focused V3/V4/P0-001 results are recorded in `outputs/timeseries_v5/audit/test_report.json`.
- Full-suite environment status is recorded separately and does not change the V4 HOLD decision.
- Secret non-exposure and protected before/after evidence are separate machine-readable artifacts.

## Unresolved blockers

1. V4 lacks receipt terminal-outcome accounting: 72/72 receipts have no explicit terminal outcome row.
2. All 113,615 observations are revision sequence 1; no real revision chain is demonstrated.
3. 57,973 availability timestamps are after 16:00 ET while the V4 feature join discards time-of-day.
4. Fed history is two independent snapshots, not six independent events.
5. The single NFP consensus row is timestamped exactly with the actual and is not a proven pre-release snapshot.

These are V5 backlog inputs, not changes authorized by task V5-P0-001.
