# Phase alignment research data

The Korean observation cutoff remains **2026-10-15**, as of 2026-10-16 09:00
KST. This folder reads the frozen original study and does not modify it.

From the repository root:

```powershell
python -X utf8 reports/research/shanghai_2007_kospi_2026/phase_alignment_v1/prices/phase_analysis.py
```

This default command is offline. It regenerates the JSON and CSV outputs from
the original frozen prices plus the retained 2009 Chinese extension. Run the
tests from this folder with `python -X utf8 -m unittest discover -p 'test_*.py' -v`.
No additional dependencies are needed. The optional `--download-2009` refreshes
only public historical HTML documents in this folder; it uses no broker API,
authentication, credentials, or live quote API.

`method_contract.json` records the rules and later explicitly identified
semantic amendments. The prior calendar study already examined Chinese
outcomes, so this is **not** an independently blind preregistration.

- `phase_analysis.json` contains observed peak/rise anchors, all completed
  prepeak underwater excursions, threshold-confirmed turns, current features,
  feature-specific historical candidates and the selected bullish control.
- `phase_aligned_series.csv` aligns the rise start, entire largest completed
  mid-rally correction and observed peak by actual sessions. It does not stretch
  time or add future Korean observations.
- `all_candidates.csv` retains every post-October-2007 Chinese candidate, every
  distance and every126-session outcome. Future outcomes are computed after
  all feature-based selections. The 299 dates per index heavily overlap and
  do not constitute 299 independent historical episodes.
- `nearest_candidates.csv` labels separate rankings as `core_original` and
  `extended_shape`. Each ranking is for one feature; there is no combined score.
- Original core features preserve depth/time and current position relative to
  a running trough. The extended method also measures the preceding confirmed
  rebound's amplitude, loss recovery and duration. Current running-trough
  bounce becomes zero at a new low and cannot substitute for prior rebound
  strength.
- A trough or rebound peak is usable only on its later10/15/20% confirmation
  date. Each historical candidate is calculated using its own price prefix.
  The last confirmed rebound is paired with its immediately preceding trough,
  even if a later trough has since been confirmed.
- Whole underwater excursions run from a running closing high until its first
  recovery. An interim rebound does not split the correction. These retrospective
  completed anchors are distinct from threshold-based zigzag sublegs.
- The July5,2007 false-break control sits outside the post-October candidate
  ranking. It illustrates that an observed high need not be the final cycle
  high. It has no probability or scenario weight.
- The 2009 extension contains244 closes per Chinese index. Each historical
  HTML overlaps63 official2008 closes, all within0.011 index point. Raw HTML,
  SHA256 receipts and extension CSV hash are retained; only historical outcome
  follow-through uses this supplement.

All returns and drawdowns are fractions. The126-session path includes the
candidate close as time zero and exactly126 future closes. Worst return from
the origin includes its initial zero return; the minimum future-only return
is also stored separately. Maximum drawdown uses every subsequent observed
peak, so it differs from loss relative to the original close.

Threshold/tolerance intersections and Pareto sets are descriptive sensitivity
results. They are not statistical confidence regions, crash probabilities,
independent case weights or a Korean return forecast. Missing confirmation
features remain null. Historical outcomes are never copied onto the Korean
future line.
