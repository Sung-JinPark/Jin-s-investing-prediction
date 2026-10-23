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

The ten exact Yahoo instruments are `000660.KS`, `SOXX`, `^IXIC`, `^GSPC`,
`BTC-USD`, `^DJI`, `^KS11` (KOSPI), `005930.KS` (Samsung Electronics), `NVDA`
and `MU`. The four later instruments use calendars the companion already
replays (XKRX, XNAS). An upgraded companion copies the new registry entries into
its private root; captured definitions must stay byte-identical, otherwise the
refresh stops instead of redefining them. The requested Solactive Magnificent Seven index remains
HOLD without its exact source. Collection attempts do not imply that every
source succeeded: errors retain the last verified personal chart and are shown
with its original acquisition date and current missing-session status.

Opening the trendline page on the published website or the companion's local
preview automatically checks `http://127.0.0.1:8878`. Select an asset to see its
available price, date, chart and nearest upper and lower boundaries. There is
no separate connection button or file-opening step. Source metadata is available
under **자료 정보**. The distance percentages compare a boundary with the
displayed observation price; they are not forecast probabilities.

Each asset has two graphs. **전체 추세선** uses every validated daily candle in
the available capture and shows its actual first and last dates and candle
count. **현재 상·하방 추세선** keeps the 3-month, 1-year and 3-year choices
(63, 252 and 756 candles). Those period buttons change only the current graph;
the linear/logarithmic axis selection applies to both. The full graph describes
the captured history, without claiming lifetime coverage or relabeling it as
three years. Missing or rejected daily rows remain gaps.

The full graph loads independently. If it is still loading or its verification
fails, the current graph remains usable. An already validated full graph may be
retained with its original source date; incomplete or mismatched chunks never
replace it. The full supplement does not rewrite the current graph's stored
analysis or the original price evidence.
Its manifest is bound to the current chart's exact source snapshot and capture
time. Each full-graph chunk must match that manifest; files from different
captures are never combined. A supplemental calculation failure does not mark
a successful current-chart update as failed. A broken original source lineage
still prevents either result from passing verification.

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
python tools/run_private_trendlines.py --port 8878 --assets sk-hynix soxx nasdaq sp500 bitcoin dow kospi samsung nvidia micron
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

### Audit cost inside the worker

A refresh runs the whole-store audit at every write boundary: before selection,
inside capture, after capture, before export, and inside the full, critical,
representative and long-boundary steps, then once more before publication. No
pass was removed. Each pass, cached or not, still reads and SHA-256 hashes every
raw original, receipt and archive in every store it checks. What the worker no
longer repeats for unchanged bytes:

- **Canonical decoding of an unchanged archive.** The cache also keeps an
  evidence memo: the bindings decoded from an archive whose canonical JSON,
  content hash, identity and contract fields a *successful* audit checked. It is
  keyed by the SHA-256 of the exact bytes read and hashed in the current audit,
  together with the file name and the checking functions. A hit therefore means
  "these bytes are identical to bytes this process already decoded and checked";
  changed bytes, a renamed file, or a replaced validator are decoded and checked
  again in full. For the full, critical, representative and long-boundary
  archives, a hit also compares the digest of every file the archive depends on
  (source archive, receipt, raw original, full snapshot, manifest, candle chunks,
  exports, and the critical snapshot used as the representative shadow), as
  read in the current audit. It compares today's registry definition and
  calculation contract, and rechecks the read cutoff. Any difference sends the
  archive through its full check, which reports its own error.
- **HTML reparse in the representative and long-boundary audits.** These
  audits reuse the research audit's proof for exactly the same archive, receipt
  and raw bytes and the same parser functions. Without such a proof, including
  every audit outside the worker, they reparse the original HTML as before.
- **A second read of the same file in one audit.** An audit reads and hashes
  each file once. The critical audit runs the full audit, which runs the
  research audit; these nested audits, and later checks in the same audit (the
  original behind a receipt, an archive's dependencies, a latest pointer), use
  the digest of the bytes the audit already read at exactly that path. This
  record exists only while the outermost audit runs; the next audit reads every
  file again. A file changed after this audit read it is reported by the next
  audit, just as a change after an audit's last read always was. The research
  audit therefore reads each original once and rebuilds its receipt from that
  read's digest and length. It reads the original again only to reparse it.
- **Other assets' chains in a refresh's representative and long-boundary
  audits.** These two audits check only the refreshed asset. They used to reread
  every other asset's dependency chain and then skip that snapshot whatever the
  result. They now see whose snapshot it is first. The research, full and
  critical audits still check every asset.
- **Waiting for one file at a time, and per-file lookups.** Each audit loop
  reads and hashes the next four files on worker threads while it checks the
  current one. The same files are read and hashed. Each digest is of the bytes
  checked with it, and a failed read is reported at its place in file order,
  after every earlier file's checks. Dependency paths are still resolved one by
  one and must lie inside the store's root, which each audit resolves once. A
  root that resolves elsewhere later can only make more paths fail. The asset
  registry is read and validated once per audit, and every caller still gets
  its own copy of an asset. A registry edited during an audit is reported by
  the next one, as with files.

Relaxed guarantee, stated explicitly: within one worker process, an archive is
not decoded and re-canonicalized again when its bytes hash to bytes the same
process already checked. This relies on SHA-256 collision resistance, which the
store already assumes for raw-original names and every binding hash. Proofs and
evidence stay process-local, are never persisted or caller-supplied, and only a
completely successful audit adds them.

The calendar lookup behind each candle's session check and the contract YAML
parse are now shared within the process. They return exactly the previous values
and do not skip any check. Candle validation previously recomputed a one-day
exchange schedule for every candle.

Measured on 2026-10-22 against a copy of the 174-capture store (1.0 GB). Each
refresh replayed the same saved public pages; other processes were running on
the machine. Both versions wrote byte-identical artifacts.

| Refresh | Before | After |
|---|---|---|
| New asset (micron), first after restart | 1,250.6 s | 295.0 s |
| Same asset again (warm) | 391.7 s | 51.3 s |
| Next asset (nvidia) in the same process | 479.8 s | 85.8 s |
| Old asset (sk-hynix, 22 captures), first after restart | 1,321.0 s | 430.1 s |
| Same old asset again (warm) | 396.7 s | 40.5 s |

The first refresh after a restart still has to decode and replay every archive
once, because proofs are never persisted; for an old asset this includes the
numerical replay of each of its full-geometry snapshots. Warm refreshes still
grow linearly with stored bytes, because every original is hashed on every pass.
The local browser shell also starts from the public HOLD projection. It obtains
personal prices only through the validated private import interface, rather
than copying them into the shell's dashboard data or static chart sidecars.

#### Cache bound

Every pass walks the whole store, so the cache's working set is the whole store,
not the recent captures, and a restart does not shrink it: the first cycle after
a restart refills it. Each capture adds one proof and one evidence entry per
layer (research, full, critical, representative, long boundaries), so five to
each store. A full research proof replaces the metadata-only proof for the same
bytes; before, those twins made the proof store fill first.

Measured on 2026-10-22 on a copy of the 182-capture store after one ten-asset
cycle, with a second cycle adding nothing:

| Entry | Count | Bytes each |
|---|---:|---:|
| Proof (research / full / critical / representative / long) | 813 | 744 (505–1,187) |
| Evidence (same layers) | 813 | 3,122 (1,382–4,569) |
| Dict and ordering overhead, per entry | | about 98 |

Sizes come from a `sys.getsizeof` walk of each store, skipping the shared
function objects. On entries of the same shape, the walk agreed with
`tracemalloc` within 3%. One shared copy of the checking functions' ID tuple
per key brought these down from 1,524 and 4,407 bytes. That is about 20 KB per
capture, 3 MB today and about 212 MB a year at ten assets three times a day.
Full and critical evidence grows a little as the candle history adds chunks.

Each store holds up to 262,144 entries (`max_entries`; the constructor accepts
up to 1,048,576). At 150 entries per store per day, the stores fill around
2031-07-30, holding about 1.0 GB; the whole store stays resident until then.
The previous 16,384 would have filled around 2027-01-16. The worker logs both
counts after every refresh (`Private replay cache` in `local-service.log`).

A full store does not evict by recency. Under LRU, each asset's own full,
critical, representative and long-boundary proofs, used once per ten-asset
cycle, were exactly the entries evicted before their next use. A full store
keeps what it holds and gives up only an entry that no successful audit has
used in 2,048 audits (about five days of refreshes). A new entry that finds no
such slot is not kept; that archive is decoded and replayed in full on each
pass, so cost grows with the overflow. A simulation of the worker's pass order,
weighted with measured per-archive costs, gave about 310 s of extra work per
refresh at the bound (LRU: 550 s) and about the same as LRU at twice the bound.
No eviction order makes an overflowing store warm.

Hashing binds long before the bound. The store grows about 5.5 MB a capture,
about 5 GB a month at this rate, and every refresh reads it several times.

#### What a warm refresh reads

Measured on 2026-10-22 on a copy of the 182-capture store (1.0 GB, 2,427 files).
Every asset's evidence was already cached, as in the worker after one cycle.
Each refresh was a changed micron capture replayed from saved bytes. The two
versions ran interleaved in one process on the same copy, so load on the machine
affected both; they wrote byte-identical stores.

| Per warm refresh | Before | After |
|---|---:|---:|
| Bytes read | 10.85 GB | 5.58 GB |
| Six research audits, each | 812 MB | 583 MB |
| Full audit, with its research audit | 1.63 GB | 0.85 GB |
| Critical audit, with its full and research audits | 2.53 GB | 0.99 GB |
| Representative and long-boundary audits, each | 0.81 GB | 0.03 GB |
| Wall clock, five audits only (median of 8) | 16.2 s | 6.9 s |
| Wall clock, refresh (median of 3) | 56.4 s | 50.0 s |

SHA-256 itself takes about 0.5 s per GB here; reading the bytes takes 1–1.6 s
per GB, so reads, not hashing, set the cost. About 25–35 s of a refresh is the
refreshed asset's own calculation and the replay of its previous snapshots,
which does not depend on the store's size.

What still grows with the store: each refresh reads about 5.6 times the stored
bytes, because six research audits read the whole research store and the full
and critical audits read it once more with their own stores. Per-file work grows
too. Resolving a path costs about 0.4 ms on this machine. The dependency checks
of one refresh make about 5,300 path checks; before the root was resolved once
per audit, each check resolved it again. Archive checks also read the asset
registry about 3,500 times a refresh. At 1.0 GB that came to about 7.5 s of
serial reading and hashing and 6 s of per-file work a refresh, against about
23 s before the change above.

Reading four files ahead on threads, resolving the root once per audit and
reading the registry once per audit were then measured the same way: the
version with and the version without them alternated in one process on a copy
taken at 16:59 (1.1 GB, 2,476 files). Both read the same bytes.

| Warm, same bytes read (medians) | Without | With |
|---|---:|---:|
| Five audits only: 12 pairs in two runs, every pair faster (0.34–0.70×) | 9.6 s | 5.2 s |
| Refresh: 5 pairs, every pair faster (by 0.5–11.1 s) | 37.2 s | 29.8 s |

The machine was busy with other work, so single runs varied by up to three
times; each pair ran back to back.

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
- The full graph uses the separate `trendlines_private_full_geometry_v1`
  contract and a shadow comparison on the same complete captured input. Its
  confirmed pivots use 10 sessions on each side and a minimum anchor separation
  of 60 sessions. The original 63/252/756 analyses remain unchanged. Full
  geometry requires at least 771 candles; shorter captures keep their candles
  with the line analysis on HOLD. A capture above the 4,096-candle limit is
  rejected rather than silently shortened. Manifest and candle chunks retain
  their exact hashes, with at most 512 candles and 256 KiB of payload per chunk.
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
