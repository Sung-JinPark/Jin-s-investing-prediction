# WTI current updates with a separately reviewed historical archive

This is a display-only statistics change. Official forecasts, ALFRED vintages,
probabilities and existing ledger rows remain unchanged.

## What the 620 omissions are

All 620 normalized revisions reproduce their actual retained FRED raw response
`828546b69c140a559527eda2b8514f02f98d44f02d2fd87f3834eefef0f4b62a` exactly.
They were first acquired August 18, 2026, and range from January 6, 1995 to
February 4, 2015. None was manufactured by interpolation or introduced by the
new fallback parser. The August 31 and September 5 official API responses still
contained them. The first retained affected API response, September 18, replaces
exactly these 620 numerical cells with explicit `.` values. All 7,325 overlapping
numerical observations match; nine genuinely later dates were added normally.
Current EIA HTML and XLS independently reproduce the same missing-date set and
all 7,359 current FRED values. This localizes the difference to the published
upstream vintage, rather than API pagination, a query window or a local parser.
It does **not** establish the vendor's internal cause or that the values were
formally withdrawn. No primary-source notice explaining those specific omissions
was identified. Accordingly the retained points are labelled archived values
unavailable in the current release, never current-release observations.

Primary references:
- https://fred.stlouisfed.org/series/DCOILWTICO
- https://www.eia.gov/dnav/pet/hist/RWTCD.htm
- https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls
- https://www.eia.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp

## Narrow admission policy

`data/statistics/reference/wti_reviewed_history_v1.json` pins every reviewed date,
value, original observation ID, raw hash and availability time. Its entire byte
hash is pinned in `wti_history.py`. It is an explicit 620-point review, not a
blanket exception to missingness validation. The source remains FRED DCOILWTICO,
USD/barrel, daily, not seasonally adjusted. EIA is diagnostic corroboration;
no second source or price proxy is silently substituted.

A new FRED response may advance only when its endpoint does not regress, every
non-reviewed prior date remains, and each absent reviewed date is explicitly
`.` in the response. Each absent point must still have its pinned original
revision and reproduce the archived raw bytes. Current rows must reproduce the
received response, be unique and not future dated. Unreviewed omissions retain
the existing quarantine; broken manifest/raw evidence blocks publication.

Only numeric rows actually present in the new FRED response reach normalization.
The canonical ledger read model also selects the original archived revisions,
with their original receipt and availability. Archive values are never inserted
into a new response, newly timestamped or appended with its new receipt. Genuine
current-source corrections append normal superseding revisions. A restored
historical date leaves the archive partition; if its new revision later goes
missing, it requires another review rather than reusing an obsolete exception.

Source metadata separately reports the current receipt/endpoint/count and the
archive manifest/hash/range/count/availability. The chart displays one concise
archive note only while the current source is healthy. A held source keeps its
review notice. Each rerun checks coverage again. No old raw bytes, normalized
observation, immutable snapshot or event is rewritten.


## Final refresh audit: unsupported real M2 status

The existing reference-only liquidity builder hard-coded "ALFRED vintage API key
unavailable" even though that field does not implement a point-in-time M2/CPI
join at all, and actual ALFRED collection now succeeds elsewhere. The producer
and UI now describe that unimplemented lineage correctly. The closed status,
all liquidity numbers and existing captured weekly vintages remain unchanged;
no old snapshot is rewritten or current-vintage M2 substituted into a PIT field.

The header's breadth/regime context still comes from a historical research run
(breadth July 29; NBER observation June 1), independently of the current NASDAQ
and statistics chart. Those header items now explicitly say archived and show
their own observation date. This is a display correction, not an unsupported
claim that the legacy breadth or CAPE research inputs refresh automatically.
