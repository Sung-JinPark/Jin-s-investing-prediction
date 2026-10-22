# Current statistics: free native-source fallback audit (2026-10-22)

Scope: display-only dotcom/current statistics. Neither official forecasts nor
ALFRED point-in-time model archives may consume this fallback.

## Verified substitutes

The FRB's published XML/CSV downloads were acquired directly, with no credential
or access-control workaround. The Board permits copying/distribution of its own
public-domain information with attribution:
https://www.federalreserve.gov/disclaimer.htm

| FRED identifier | Native identity | Unit | Compared observations | Differences |
| --- | --- | --- | ---: | ---: |
| M2SL | H.6 M2.M, seasonally adjusted monthly | USD billions | 380 | 0 |
| FEDFUNDS | H.15 RIFSPFF_N.M, monthly | percent | 381 | 0 |
| GS10 | H.15 RIFLGFCY10_N.M, monthly | percent | 381 | 0 |
| BOGZ1LM153064475Q | Z.1 LM153064475.Q | USD millions | 126 | 0 |
| BOGZ1LM893064105Q | Z.1 LM893064105.Q | USD millions | 126 | 0 |

Total: 1,394 overlapping observations. Observed endpoints were August 2026 for
M2, September for monthly rates, and 2026 Q2 for Z.1; these native publication
frequencies must not be relabelled October daily observations. Native period-end
labels become the same period's start label used by FRED, without averaging,
interpolation, scaling or changing values. Publisher series IDs, units, frequency
and M2 seasonal adjustment are pinned in the contract and parser.

On an API availability failure, or when a valid API response ends before the
native publication, each candidate must retain every stored
observation date, match the entire overlap within max(1e-8, abs(value)*1e-12), and
have at least 24 overlapping observations. Any revision disagreement, truncation,
duplicate, nonfinite value, wrong unit or missing identity rejects the candidate.
Monetary/equity levels must be positive; interest rates may be negative.
The old source remains dated and explicitly waiting. This is a conservative
promotion gate, not a claim that genuine future publisher revisions are errors.

Sources:
- https://www.federalreserve.gov/releases/h6/current/default.htm
- https://www.federalreserve.gov/releases/h15/
- https://www.federalreserve.gov/releases/z1/

## Held alternatives

- Chicago Fed NFCI free direct CSV is reachable and goes through October 16.
  Against the old FRED vintage, 1,604 of 1,658 overlaps differ at the publisher's
  three-decimal precision (maximum absolute difference 0.065). After the actual
  FRED recovery, all 1,659 overlaps match the new official vintage exactly,
  confirming that the earlier difference was a published-vintage mismatch.
  Direct collection remains **not promoted**: the source-specific legal/D0
  review in `data/contracts/fred_nfci_d0.yaml` remains closed. This change does
  not infer broader distribution permission from free download availability.
  https://www.chicagofed.org/research/data/nfci/current-data
  https://www.chicagofed.org/utilities/legal-notices
- Nasdaq's free website endpoints do not establish permission for this automated
  public-data use. No Nasdaq endpoint, Yahoo proxy or ETF replacement is enabled:
  https://www.nasdaq.com/legal
- Coinbase's direct API is not a verified equivalent of FRED CBBTCUSD's daily fix,
  and its direct market-data terms restrict public redistribution/derived works:
  https://www.coinbase.com/legal/market_data
- No credit-spread proxy is substituted for ICE series in cross-asset analytics.

## Outage and recovery behavior

The five native releases are also checked when FRED returns valid data. An
equivalent native release can advance the read model if its endpoint is newer.
Otherwise FRED remains the selected source; an unavailable or incompatible
optional native download cannot suppress a healthy FRED series. This also
handles a lagging API after a previous native promotion without moving dates
backwards. Complete current FRED observations are used as the overlap comparator;
if their coverage regresses, the previously approved view remains the comparator.

Two consecutive availability failures for different series open a circuit for
the remaining FRED requests in that batch. A successful response resets the
failure count, so one failed series cannot suppress healthy series. Five
individually verified native series can still refresh. Other inputs
may retain only their approved ledger observations, original availability times
and intact raw receipts. A raw/lineage failure blocks publication. Per-series
waiting state is shown in the UI and makes the scheduled workflow report failure
**after** any valid partial update is committed and published. No synthetic new
observation is written for a retained series.

Fresh native observations use the actual acquisition time, separate Board source
identity, exact ZIP bytes, SHA receipts and append-only revisions. Shared Z.1
responses declare all extracted series in the receipt. A same-input rerun does
not duplicate observations or publish a clock-only snapshot. Each later batch
probes the official API again; it can recover to FRED only with non-regressed
coverage. Existing source revisions and raw files remain preserved.

## Actual production recheck

The FRED home page and API recovered at different times. The API was confirmed by
successful operational source steps, not by a home-page HTTP 200:

- Statistics: https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/39723981228
- Cross-asset: https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/runs/39723984376

Both datasets advanced to the US October 21 session. NFCI also advanced to October
16 through the recovered official API. Cross-asset current prices continue using
their existing approved FRED definitions; no unverified free substitute is
claimed as operational. A six-hour thread heartbeat separately checks actual API
results and public propagation, notifying only on meaningful changes.
