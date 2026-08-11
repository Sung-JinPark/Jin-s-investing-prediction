# Scenario V5.2 distinct-path diagnostic

Generated `2026-08-11T07:30:58+00:00`.

- Baseline model: `5ae4dfe981712b35f97b01b023b1e64138cf7adc9a4ebfb34a5b4565afcf5846`
- Candidate model: `d8beb7e8b413e3073913264913f0a328ac48b548d0285346a219c384f08214df`
- Protected manifest unchanged: `True`
- Gate A contradiction: `false`
- Threshold gate: `report_only` until 30 approved trading-day observations
- Requested promotion origin counts are 15/20/12; actual selected counts are 63/99/7, so S3 remains promotion-blocking
- Above-cap A/B 0.70 and 0.80 rows are shadow-only and never active
- Five-as-of output is explicitly a structural stability audit because five independent PIT vintages do not exist
