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

## Automatic personal refresh and browser connection

From the repository root, install the companion for the current Windows user:

```powershell
powershell -NoProfile -File tools/install_private_trendlines.ps1
```

The installer places the application and minimal contracts beneath
`%USERPROFILE%/.jins-investing/trendlines/app`. This directory is also visible to
Windows Task Scheduler outside a packaged app's virtualized AppData view. Its research originals and exports
stay beneath that application's `outputs/trendlines/private-research-view`.
This permanent application directory is separate from the Git worktree.
Existing captures remain immutable; updating the application does not rewrite
their acquisition times or prices. No dependency installation, administrator
password, browser security flag, or execution-policy bypass is required by this
workflow.

The companion evaluates the **Asia/Seoul** schedule at **07:17, 09:17 and 16:17**.
It catches up after startup or sleep without inventing historical acquisitions.
Missed collection is performed at the actual later acquisition time. Windows
Task Scheduler starts the current-user task `JinsInvesting-PrivateTrendlines`
at logon and uses the daily triggers as a watchdog; duplicate instances are
ignored. If task registration is unavailable, the installer uses the current
user's Startup folder instead. The existing Python environment runs the
companion in the background.

The six exact Yahoo instruments are `000660.KS`, `SOXX`, `^IXIC`, `^GSPC`,
`BTC-USD`, and `^DJI`. The requested Solactive Magnificent Seven index remains
HOLD without its exact source. Collection attempts do not imply that every
source succeeded: errors retain the last verified personal chart and are shown
with its original acquisition date and current missing-session status.

Opening the trendline page on the published website or the companion's local
preview automatically checks `http://127.0.0.1:8878`. Select an asset to see its
available price, date, chart and nearest upper and lower boundaries. There is
no separate connection button or file-opening step. Source metadata is available
under **자료 정보**. The distance percentages compare a boundary with the
displayed observation price; they are not forecast probabilities.

Prices remain in memory and are not uploaded to GitHub, the public site, or
another server. The page does not store chart data or a connection preference
in browser storage. Leaving the trendline page stops its polling, and a hidden
page pauses checks until it becomes visible again. The browser may show its
normal local/loopback-network permission prompt. Grant it for the intended
website if you want the connection. If access is denied or the companion is
unavailable, the page shows a loading or unavailable state, or retains the last
validated chart with its original date when one has already been loaded.

For foreground operation, or to start from existing files without an immediate
acquisition:

```powershell
python tools/run_private_trendlines.py --port 8878 --assets sk-hynix soxx nasdaq sp500 bitcoin dow
python tools/run_private_trendlines.py --port 8878 --no-startup-refresh
```

`--no-startup-refresh` skips that initial acquisition; later scheduled slots
still refresh normally.

The loopback interface provides fixed read routes for chart files and status.
It binds only to `127.0.0.1` and checks the exact Host. CORS allows
`https://sung-jinpark.github.io` and the companion's own loopback origin;
ordinary local navigation is also supported. It has no command or write API. HTTP requests
do not start a source collection or replay all historical archives. The refresh
worker verifies original bytes, receipts and numerical replay before atomically
replacing a personal export. Status reports current calendar freshness and
collection failures separately from the unchanged hashed chart payload.
The daemon explicitly enables a bounded replay cache in its worker context.
Every audit still hashes the originals and receipts and checks canonical
archives, instrument identity, revisions, latest pointers and rejected captures.
Only previously successful mathematics for exactly the same archive, receipt,
raw bytes and validator functions is reused in that process. New or changed
evidence is recalculated; failed audits never mint a proof. The cache has no
file, source-approval flag, or effect on ordinary CLI verification, and starts
empty when the process restarts.
The local browser shell also starts from the public HOLD projection. It obtains
personal prices only through the validated private import interface, rather
than copying them into the shell's dashboard data or static chart sidecars.

## Browser compatibility

Chrome's [official Local Network Access notice](https://developer.chrome.com/blog/local-network-access)
describes normal permission-gated access from HTTPS sites to local services.
The permission launched in Chrome 142; the
[Chrome 145 release notes](https://developer.chrome.com/release-notes/145)
document the separate `loopback-network` and `local-network` permissions and
the older `local-network-access` alias. The browser must grant its normal
permission; successful CORS headers alone do not grant it.

The client uses a normal CORS request to the literal loopback address, with
credentials omitted. Supporting browsers can use the
[`targetAddressSpace: "loopback"` request hint](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access).
Support and permission names vary by browser version. Unsupported or denied
connections show an actionable connection error; the implementation does not
disable mixed-content checks, install a certificate exception, use `no-cors`,
or change browser security settings.

The older [Private Network Access preflight mechanism](https://developer.chrome.com/blog/private-network-access-preflight)
uses `Access-Control-Request-Private-Network` and
`Access-Control-Allow-Private-Network`. The companion handles a valid preflight
for its allowed origin as compatibility support. These headers do not replace
the current browser permission mechanism. Neither the old preflight nor a
loopback HTTP test proves that an HTTPS browser has granted access.

## Manual refresh and display locally

Run from the repository root with the existing Python environment:

```powershell
python tools/refresh_private_trendlines.py --fetch --allow-rejected-rows
python tools/run_private_trendlines.py --port 8878 --no-startup-refresh
```

Open `http://127.0.0.1:8878/#future/trendlines/sk-hynix`; the page checks the
companion automatically. The companion schedules subsequent refreshes; a plain
static HTTP server does not collect or refresh sources. The updater also writes
`outputs/trendlines/private-research-view/sk-hynix.trendlines.json` as a local
transport file. The companion validates that file and serves it through its
fixed read-only route. The browser hashes the exact payload before rendering
and holds the resulting chart only in memory. Reloading begins with the
official public state and checks for validated personal data again. The local
updater can be rerun after market close without changing the approved-source
publisher.

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
- Current display freshness is checked against the market calendar. If another
  session has closed since the capture and its candle is missing, the chart is
  marked stale. This changes its display status, not the frozen `as_of`, first
  acquisition, candles, line equations or source history. No-op captures and
  successful connections do not make an old candle fresh.
- Linear and logarithmic geometry are independently checked. Future points are
  trendline extensions. Quote-date reference levels and confirmed-candle levels
  have distinct dates and labels.
- Import hashes bind the exact UTF-8 `payload_json` before browser parsing.
  Python floating point encoding is not replaced with `JSON.stringify`.
  Payloads are limited to 256 KiB and envelopes to 512 KiB. Invalid, oversized,
  or foreign-instrument files are rejected without replacing a valid view.
  Existing `trendlines_private_import_v1` files remain supported. When their
  original chart body exceeds 256 KiB, `trendlines_private_import_v2` packs only
  the repeated candle field names into fixed columns and row arrays; dates,
  calendar indices, OHLC, bar identities, line equations and events are retained
  without rounding or truncation. A fixed `bar_id_prefix: "research-bar-"` can
  hold the shared prefix once; each row retains its complete SHA256 suffix and
  reconstructs the same bar identity. Earlier V2 files with full bar identities
  and no prefix field remain readable. Its `payload_sha256` binds the packed wire
  string. Its separately named `original_detail_sha256` binds the original
  canonical chart body and appears both inside and outside the hashed payload.
  Python verifies that hash after reconstruction; the browser verifies the
  exact wire hash and retains the original detail hash as its separate identity.
  Packing does not modify the original capture, receipt, archive or replay.
- Magnificent Seven is not substituted with MAGS or a different index. This
  private HTML adapter does not claim the user's requested Solactive index.

Public deployment delivers the importer and rendering code. It does **not**
deliver vendor OHLC or claim seven automatic public charts are operating.
