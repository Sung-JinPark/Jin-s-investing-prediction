# Phase G — Dashboard contract

Gate: **PASS WITH BROWSER-ENVIRONMENT LIMITATION**

`scenario_v5_2_dashboard.html` is self-contained. The first chart includes 60 historical actual sessions, a forecast boundary, total-mixture p50, p5/p95, p10/p90 and p25/p75 bands. It overlays seven actual central members and a dotted actual medoid. S1/S2/S3 appear only as conditional small multiples, and each panel also contains an actual member bundle and medoid. Stored probabilities remain fractions; the dashboard alone converts them to percent. October 2 is labelled an ordinary CDF coordinate and `exact-date forecast=false`.

The in-app Browser refused the local `file:` URL under its URL security policy. No policy bypass was attempted. DOM contract, SVG geometry, responsive CSS, finite-value, and semantic tests are automated; the self-contained HTML is included for manual visual inspection.
