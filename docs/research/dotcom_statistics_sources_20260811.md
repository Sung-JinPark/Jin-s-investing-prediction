# Dot-com statistics lab — source and design record

Date: 2026-08-11
Status: reference-only; never an official forecast input

## Purpose

The statistics category compares the dot-com cycle beginning 1995-01 with the
current AI cycle beginning 2023-01 on the same elapsed-calendar-month axis.
Alignment is descriptive. It does not force an endpoint, turning date, or
forecast probability.

## Activated public sources

| Metric | Series | Provider | Native frequency | Public chart role |
|---|---|---|---|---|
| M2 | M2SL | Federal Reserve Board via FRED | Monthly | M2 and Nasdaq normalized-cycle comparison |
| Household liquid assets | DABSHNO | Federal Reserve Board Z.1 via FRED | Quarterly, end of period | Nasdaq divided by household/nonprofit currency, deposits, and money-market fund shares |
| Nasdaq Composite | NASDAQCOM | Nasdaq OMX via FRED | Daily close | Existing market-index reference with attribution |
| 10y−2y spread | T10Y2Y | St. Louis Fed / U.S. Treasury | Daily | Yield-curve comparison |
| Federal funds | FEDFUNDS | Federal Reserve Board via FRED | Monthly | Policy-rate comparison |
| Consumer credit | TOTALSL | Federal Reserve Board G.19 via FRED | Monthly | Year-over-year credit growth |
| Debt service | TDSP | Federal Reserve Board via FRED | Quarterly | Source panel; begins after the dot-com window |
| Lending standards | DRTSCILM | Federal Reserve Board SLOOS via FRED | Quarterly | C&I standards comparison |
| Corporate equity value | NCBEILQ027S | Federal Reserve Board Z.1 via FRED | Quarterly | Numerator of valuation proxy |
| After-tax profits | CPATAX | U.S. BEA via FRED | Quarterly | Denominator of valuation proxy and profit growth |
| Broker customer receivables | FL663067003 | Federal Reserve Board Z.1 F4.6.s | Quarterly | Broad margin-credit proxy |

Primary references:

- https://fred.stlouisfed.org/series/M2SL
- https://fred.stlouisfed.org/series/DABSHNO
- https://fred.stlouisfed.org/series/NASDAQCOM
- https://fred.stlouisfed.org/series/T10Y2Y
- https://fred.stlouisfed.org/series/FEDFUNDS
- https://fred.stlouisfed.org/series/TOTALSL
- https://fred.stlouisfed.org/series/TDSP
- https://fred.stlouisfed.org/series/DRTSCILM
- https://fred.stlouisfed.org/series/NCBEILQ027S
- https://fred.stlouisfed.org/series/CPATAX
- https://www.federalreserve.gov/apps/fof/SearchResult.aspx?by=All&in=Table&search=663067003

## Valuation definition

The customer requested a corporate P/E comparison. A reproducible Nasdaq
historical trailing or forward P/E series with suitable public redistribution
rights was not found. The implemented chart therefore uses a plainly labelled
macro valuation proxy:

`nonfinancial corporate equity liability level (billions) / after-tax corporate profits SAAR (billions)`

It must not be labelled Nasdaq P/E, forward P/E, or an earnings forecast.
Robert Shiller's CAPE dataset remains a useful research reference, but is not
substituted into the numerical pipeline because the repository's vintage and
redistribution contract is not active:
https://www.econ.yale.edu/~shiller/data.htm

## Household liquid-assets definition

`DABSHNO` is the Federal Reserve Z.1 level for household and nonprofit holdings
of currency, deposits, and money-market fund shares. It includes checkable
deposits and currency, time and savings deposits, and money-market fund shares.
The dashboard uses `NASDAQCOM / DABSHNO`, indexed to 100 at each cycle start.

It does not add DABSHNO to M2. M2 already contains overlapping deposit and
retail money-market components, so adding the two levels would double count
part of the same liquid-asset stock. The ratio is descriptive and is not a
measure of immediately investable cash, fair value, or a trading signal.

## Exclusions

- FINRA monthly margin statistics: excluded until written permission covers
  automated retrieval, storage, redistribution, and predictive/research use.
  The existing D0 contract remains unchanged.
- Moody's Baa spread: excluded because the FRED series notes prohibit
  redistribution without prior written consent.
- Paid forward-P/E and proprietary constituent histories: excluded because a
  public site cannot reproduce or redistribute them under the current contract.

## Vintage and refresh policy

- The weekly job checks for new source releases every Saturday at 00:20 UTC.
- Daily, monthly, and quarterly native frequencies remain unchanged. A weekly
  check does not create synthetic weekly observations.
- Historical values are from the latest available release and are labelled
  `current_release_reconstructed`; they are not represented as native PIT
  vintages.
- Statistics remain `reference_only`, `model_use=false`, and
  `official_forecast_input=false`.
