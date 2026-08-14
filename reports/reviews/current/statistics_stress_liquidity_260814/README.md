# Statistics / stress / liquidity render evidence — 2026-08-14

- Static build: `_site/`
- Capture backend: bundled Chromium via Playwright
- Routes: 15
- Viewports: 1280×900 and 390×844
- Screenshots: 30
- Render failures: 0
- Horizontal-overflow gate: PASS

Key evidence:

- `screenshots/statistics__1280.png`, `statistics__390.png`
- `screenshots/future-cross-asset__1280.png`, `future-cross-asset__390.png`
- `screenshots/future-liquidity__1280.png`, `future-liquidity__390.png`
- `render_proof.json`
- `screenshots/render_manifest.json`

The multi-year chart is a single log-scale view. Historical episodes, observed NASDAQ/Realty Income, and the user-directed Bitcoin liquidity-rotation assumption retain separate labels. The liquidity chart uses one plot with an explicit left z-score axis and right return axis. No official forecast, probability, calibration, ledger, or champion artifact is modified by these display/reference-only outputs.
