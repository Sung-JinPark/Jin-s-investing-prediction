# Personal research trendline charts

The earlier SK Hynix illustration read Yahoo's public history HTML, used its
embedded daily OHLC, and showed a separately timestamped quote. This workflow
can reproduce an actual chart without approving that source for official or
publicly distributed prices.

Yahoo's [official data notice](https://uk.help.yahoo.com/kb/finance/article-data-availability-yahoo-finance-sln2310.html)
prohibits redistribution of information displayed or provided by Yahoo Finance.
Accordingly, this implementation keeps the originals, receipts, prices, charts,
and import files in the user's ignored `outputs/` directory. Standard dashboard
and Pages writers reject research price payloads. The approved-source batch and
its empty approved-source policy remain separate.

## Refresh and display locally

Run from the repository root with the existing Python environment:

```powershell
python tools/refresh_private_trendlines.py --fetch --allow-rejected-rows
python tools/preview_trendlines.py --research-root outputs/trendlines/private-research-view
python -m http.server 8878 --bind 127.0.0.1 --directory outputs/trendlines/private-research-view/site
```

Open `http://127.0.0.1:8878/#future/trendlines/sk-hynix`. The updater also writes
`outputs/trendlines/private-research-view/sk-hynix.trendlines.json`, which the
public site's **개인 연구 차트 열기** control reads locally using the browser's
File API. File contents are held in memory; they are not uploaded or persisted.
Reloading or resetting returns to the official public state. The local updater
can be rerun after market close without changing the approved-source publisher.

An existing HTML capture is independently replayable:

```powershell
python tools/refresh_private_trendlines.py --raw <original.html> --receipt <receipt.json> --allow-rejected-rows
```

The receipt must contain its actual `url`, `retrieved_at`, SHA256 `sha256`, byte
count `bytes`, and successful `http_status`. No availability timestamp is
backdated. Identical acquisitions preserve their first acquisition time.

## Boundaries and inspection

- Raw bytes are saved before price validation. Revisions preserve prior captures
  and their explicit supersedes relationship. Independent replay reparses the
  original HTML and checks the numerical geometry.
- O/H/L/C come from one daily response. Adjusted close is never used to create
  highs or lows. The current provider vintage has no certified split-adjustment
  guarantee and is displayed as personal research.
- Default ingestion rejects invalid prices. `--allow-rejected-rows` explicitly
  leaves invalid OHLC rows as gaps with the original values and exact error.
  Other identity, time, calendar, or lineage failures remain fatal. Nothing is
  clipped, repaired, filled, or combined with another source.
- A same-day candle is excluded until the exchange close, settlement buffer,
  and source quote watermark permit it. A separate earlier quote is a point,
  not a candle. Missing sessions break ATR, pivot confirmation, and formation
  continuity. Historical current-vintage geometry does not create historical
  issuance or break/reentry events.
- Linear and logarithmic geometry are independently checked. Future points are
  trendline extensions. Quote-date reference levels and confirmed-candle levels
  have distinct dates and labels.
- Import hashes bind the exact UTF-8 `payload_json` before browser parsing.
  Python floating point encoding is not replaced with `JSON.stringify`.
  Payloads are limited to 256 KiB and envelopes to 512 KiB. Invalid, oversized,
  or foreign-instrument files are rejected without replacing a valid view.
- Magnificent Seven is not substituted with MAGS or a different index. This
  private HTML adapter does not claim the user's requested Solactive index.

Public deployment delivers the importer and rendering code. It does **not**
deliver vendor OHLC or claim seven automatic public charts are operating.
