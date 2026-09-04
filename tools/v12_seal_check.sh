#!/usr/bin/env bash
# tools/v12_seal_check.sh — V12 루프 봉인 대사 (읽기 전용). 정본 해시 e3ff2fdb… 재현.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
V2_SEALED="src/ai_fc/timeseries_v2/contracts.py src/ai_fc/timeseries_v2/market_archive.py src/ai_fc/timeseries_v2/dfm_cache.py src/ai_fc/timeseries_v2/features.py src/ai_fc/timeseries_v2/model.py src/ai_fc/timeseries_v2/backtest.py src/ai_fc/timeseries_v2/pipeline.py src/ai_fc/timeseries_v2/artifact.py"
SEALED=$( { find src/ai_fc/timeseries_v8 -type f -name '*.py' -exec sha256sum {} \; ; sha256sum $V2_SEALED ; } 2>/dev/null | sort | sha256sum | cut -d' ' -f1 )
LEDGER=$( cat data/timeseries_v8/ledgers/*.jsonl 2>/dev/null | sha256sum | cut -d' ' -f1 )
echo "sealed=$SEALED"
echo "ledger=$LEDGER"
BASE=$(cat outputs/timeseries_v12/loop/sealed_baseline.hash 2>/dev/null || echo "")
LBASE=$(cat outputs/timeseries_v12/loop/ledger_baseline.hash 2>/dev/null || echo "")
[ "$SEALED" = "$BASE" ] && echo "sealed_match=OK" || echo "sealed_match=FAIL"
[ "$LEDGER" = "$LBASE" ] && echo "ledger_match=OK" || echo "ledger_match=FAIL"
