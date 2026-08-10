# Phase B — Macro and market data provenance

Gate: **PASS**

- BLS release `BLS_EMPSIT_2026_07_2026_08_07`: payroll -23,000, unemployment 4.10%, participation 61.40%.
- May/June revisions: -66,000 / -37,000; combined -103,000.
- Every normalized rate distribution has explicit unit `fraction` and sums to one.
- Aggregate hike probability: Sep 55.10% → 43.40%; Oct 68.60% → 59.10%; Dec 84.00% → 76.80%.
- The prompt's approximate values are retained in `spec_example_comparison`; source-exact values drive the model.
- Yahoo ^IXIC PIT history: 2,664 closes, 2016-01-04 through 2026-08-07; raw hash `193e84ada6cbcbcab519c98cd8cd523a158b32ad02531ed3deb1b729f539e7cc`.
