# S0 D0 source follow-up — 2026-08-05

## Outcome

The active D0 monitoring set is capped at exactly three candidates: CFTC Bitcoin TFF, the Federal Reserve Z.1 margin-credit proxy, and STLFSI4. All remain disabled, unregistered, absent from collectors, and prohibited from model use.

| Candidate | D0 state | What is monitored | Activation blocker |
|---|---|---|---|
| CFTC Bitcoin TFF | monitoring through 2026-08-17 | dataset/code, Friday availability, schema, delays | complete the existing 14-day gate |
| Fed Z.1 `FL663067003` | monitoring through 2026-08-18 | official ZIP, series/table mapping, quarterly release, revisions, dot-com coverage | separate S1 approval and PIT/proxy-label implementation |
| FRED `STLFSI4` | monitoring through 2026-08-18 | ephemeral CSV schema, Wednesday publication, revisions, terms changes | source-specific rights clarification before storage/display/model use |

FINRA margin statistics remains `blocked_legal_terms`; the operator action is to request written permission for automated retrieval, local storage, public redistribution, and predictive use through FINRA's permission form. If permission is granted, a separately reviewed migration replaces the Z.1 proxy. The Z.1 series is quarterly broker-dealer customer receivables including margin loans and other receivables, so it must never be presented as monthly FINRA margin debt.

NFCI remains `legal_review_required`; the operator action is to continue the Chicago Fed/FRED rights inquiry. STLFSI4 starts D0 as the operational alternative, but the official FRED page labels it `Copyrighted: Citation Required` and current FRED terms separately restrict storage and use in software or machine-learning systems. Therefore D0 is limited to ephemeral transport/release monitoring and commits no raw payload.

## Official-source observations

- Federal Reserve Z.1 series guide identifies `FL663067003` as broker-dealer receivables due from customers (margin loans and other receivables), level, NSA, table L.216 line 36.
- The direct Federal Reserve current-release ZIP returned HTTP 200, 8,075,952 bytes, ETag `f9bf6262bbf9dc1:0`, last modified `2026-06-11T16:00:11Z`. The next official Z.1 release is scheduled for 2026-09-11 at 12:00 ET.
- The Federal Reserve Board states Board-produced website information is public domain unless otherwise marked, with source citation requested.
- The STLFSI4 official page defines a weekly Friday-ending index, shows the 2026-07-24 observation at -0.8263, and records the 2026-07-29 10:04 CDT update. Its direct CSV endpoint returned HTTP 200 with 31,724 bytes during the D0 probe.

## Scope guard

No source-registry entry, collector, archive, data row, dashboard number, probability-space change, or H1-H6 implementation was added. D0 contracts are design-and-monitoring artifacts only.
