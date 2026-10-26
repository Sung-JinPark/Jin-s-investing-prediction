"""mts_research — 동결 챔피언(V8/PB)을 보존하는 독립 연구 계층.

설계 정본: docs/design/NASDAQ_forecasting_upgrade_design_20261026.md
- 동결 코드(timeseries_v8/**, timeseries_v2 커널, timeseries v1 커널)는 import-only.
- 모든 산출물은 data/mts_research/ + docs/research/mts_upgrade/ 아래에만 쓴다.
- 확률은 fraction [0,1] (AGENTS.md probability contract).
"""

from __future__ import annotations

NAMESPACE = "mts_research"
SCHEMA_VERSION = 1
