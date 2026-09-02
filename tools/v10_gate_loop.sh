#!/usr/bin/env bash
# tools/v10_gate_loop.sh - V10 gate supervisor (Git Bash). See docs/design/v10_gate_autoloop_260902.md
# Design iterations ONLY. Stops at HOLDOUT-READY for the human. Deadline 2026-09-03 09:00 KST.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python"
export PYTHONUTF8=1
unset FRED_API_KEY ALPHAVANTAGE_KEY OPENAI_API_KEY ANTHROPIC_API_KEY 2>/dev/null || true

LOOPDIR="outputs/timeseries_v10/loop"; mkdir -p "$LOOPDIR"
LOCK="$LOOPDIR/lock"; STATE="$LOOPDIR/state.json"; ABORT="$LOOPDIR/ABORT"
LEDGER="data/timeseries_v10/ledgers/development_experiments.jsonl"
V8_DIR="src/ai_fc/timeseries_v8"
V2_FILES="src/ai_fc/timeseries_v2/contracts.py src/ai_fc/timeseries_v2/market_archive.py src/ai_fc/timeseries_v2/dfm_cache.py src/ai_fc/timeseries_v2/features.py src/ai_fc/timeseries_v2/model.py src/ai_fc/timeseries_v2/backtest.py src/ai_fc/timeseries_v2/pipeline.py src/ai_fc/timeseries_v2/artifact.py"
MAX_BUDGET="${MAX_BUDGET:-24}"; STOPLOSS_AT=12; SLEEP_E=30; SLEEP_S=1800
MAX_CYCLES="${MAX_CYCLES:-0}"; DRY_RUN="${DRY_RUN:-0}"; SMOKE="${SMOKE:-0}"
DEADLINE="${LOOP_DEADLINE_EPOCH:-1788393600}"   # 2026-09-03 09:00 KST = 00:00 UTC

log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOOPDIR/loop_$(date +%Y%m%d).log"; }
setstate(){ "$PY" - "$STATE" "$1" "$2" <<'PYEOF'
import json,sys,datetime
p,mode,note=sys.argv[1],sys.argv[2],sys.argv[3]
try: s=json.load(open(p))
except Exception: s={"cycle":0}
s.update(mode=mode,note=note[:4000],ts=datetime.datetime.now().isoformat())
s["cycle"]=s.get("cycle",0)+(1 if mode in("EXPLORE","SHADOW") else 0)
json.dump(s,open(p,"w"),ensure_ascii=False,indent=1)
PYEOF
}
halt(){ log "HALT: $1"; setstate HALT "$1"; rmdir "$LOCK" 2>/dev/null; exit "${2:-1}"; }

# lock
if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; else
  OLD=$(cat "$LOCK/pid" 2>/dev/null || echo 0)
  kill -0 "$OLD" 2>/dev/null && { echo "already running pid=$OLD"; exit 0; } || { log "stale lock reclaimed"; echo $$ > "$LOCK/pid"; }
fi
trap 'log "signal shutdown"; setstate SHUTDOWN "signal"; rmdir "$LOCK" 2>/dev/null; exit 0' INT TERM

# PRE-FLIGHT
BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
[ "$BR" = "main" ] && halt "branch is main - forbidden"
[ -d "src/ai_fc/timeseries_v10" ] || halt "v10 package missing (run G0 first)"
"$PY" -c "import scipy,pyarrow,numpy,statsmodels" 2>/dev/null || halt "venv import preflight failed"
# forbidden verbs must be ABSENT from the CLI seam and the harness (design contract)
grep -qiE "holdout|sealed" src/ai_fc/timeseries_v10/cli.py tools/ralph_timeseries_v10.py \
  && halt "forbidden verb text found in CLI/harness"
sealed_hash(){
  { find "$V8_DIR" -type f -name '*.py' -exec sha256sum {} \; ; sha256sum $V2_FILES ; } | sort | sha256sum | cut -d' ' -f1
}
BASE=$(sealed_hash); echo "$BASE" > "$LOOPDIR/sealed_baseline.hash"
log "BOOT branch=$BR sealed_baseline=$BASE deadline_epoch=$DEADLINE"
setstate BOOT "preflight ok"

check_sealed(){
  [ "$(sealed_hash)" = "$(cat "$LOOPDIR/sealed_baseline.hash")" ] || halt "SEALED SOURCES CHANGED - abort"
  "$PY" -c "
import sys; sys.path.insert(0,'src')
from pathlib import Path
from ai_fc.timeseries_v10.identity_test import check_source_pins
errors = check_source_pins(Path('.'))
raise SystemExit(1 if errors else 0)
" || halt "contract source pins failed"
}
budget_used(){ [ -f "$LEDGER" ] && grep -c . "$LEDGER" || echo 0; }

run_explore(){
  check_sealed
  U=$(budget_used); [ "$U" -ge "$MAX_BUDGET" ] && { log "budget exhausted ($U/$MAX_BUDGET)"; return 1; }
  if [ "$U" -ge "$STOPLOSS_AT" ]; then
    BEST=$("$PY" tools/ralph_timeseries_v10.py status 2>/dev/null | grep -oE "best_dual_improvement: [0-9.]+" | grep -oE "[0-9.]+$")
    if [ -n "${BEST:-}" ] && "$PY" -c "import sys; sys.exit(0 if float('$BEST') < 0.01 else 1)"; then
      log "STOP-LOSS: best dual improvement $BEST < 0.01 after $U singles"; setstate STOP-LOSS "best=$BEST"; return 1
    fi
  fi
  NEXT=$("$PY" tools/ralph_timeseries_v10.py next 2>>"$LOOPDIR/harness.err") || { log "harness next unavailable"; return 1; }
  [ -z "$NEXT" ] && { log "queue exhausted"; return 1; }
  LABEL=$(echo "$NEXT" | "$PY" -c "import json,sys;print(json.load(sys.stdin).get('label',''))" 2>/dev/null)
  [ -z "$LABEL" ] && { log "next() parse mismatch"; return 1; }
  log "EXPLORE run $LABEL budget=$U/$MAX_BUDGET"
  [ "$DRY_RUN" = 1 ] && { log "DRY: timeseries-v10-dev-backtest --label $LABEL"; return 0; }
  ( cd src && "../$PY" -m ai_fc timeseries-v10-dev-backtest --label "$LABEL" ) >> "$LOOPDIR/backtest_$LABEL.log" 2>&1
  RC=$?; [ $RC -ne 0 ] && { log "backtest rc=$RC ($LABEL)"; setstate EXPLORE "fail $LABEL"; return 0; }
  "$PY" tools/ralph_timeseries_v10.py record --label "$LABEL" >>"$LOOPDIR/harness.err" 2>&1 || { log "record/diagnostics failed $LABEL"; return 0; }
  git add "$LEDGER" data/timeseries_v10/runs outputs/timeseries_v10 2>/dev/null
  git commit -q -m "loop(v10): record $LABEL [budget $(budget_used)/$MAX_BUDGET]" 2>/dev/null || true
  CHAMP=$("$PY" tools/ralph_timeseries_v10.py status 2>/dev/null | grep -c "^champion:" || true)
  [ "${CHAMP:-0}" -gt 0 ] && { log "CHAMPION -> HOLDOUT-READY, stopping for user"; setstate HOLDOUT-READY "champion; awaiting user"; return 2; }
  return 0
}
run_shadow(){
  log "SHADOW monitor"
  [ "$DRY_RUN" = 1 ] && { log "DRY: v10-verify + hermetic"; return 0; }
  ( cd src && "../$PY" -m ai_fc timeseries-v10-verify ) >> "$LOOPDIR/verify.log" 2>&1 || log "WARN verify failed"
  ( cd src && "../$PY" -m pytest tests/test_multivariate_timeseries_v10.py -q ) >> "$LOOPDIR/hermetic.log" 2>&1 || log "WARN hermetic failed"
  setstate SHADOW "monitor done"
}

N=0; LAST_S=0; EXPLORE_DONE=0
while :; do
  [ -f "$ABORT" ] && { log "ABORT -> shutdown"; break; }
  NOW=$(date +%s); [ "$NOW" -ge "$DEADLINE" ] && { log "deadline reached"; break; }
  if [ "$SMOKE" = 1 ]; then MODE=SHADOW; elif [ "$EXPLORE_DONE" = 1 ]; then MODE=SHADOW; else MODE=EXPLORE; fi
  setstate "$MODE" "cycle start"
  if [ "$MODE" = "EXPLORE" ]; then
    run_explore; RC=$?
    [ $RC -eq 2 ] && break
    [ $RC -eq 1 ] && EXPLORE_DONE=1
    SLEEP=$SLEEP_E
  fi
  if [ "$MODE" = "SHADOW" ]; then
    if [ $(( NOW - LAST_S )) -ge 3600 ] || [ "$SMOKE" = 1 ] || [ "$LAST_S" = 0 ]; then run_shadow; LAST_S=$NOW; fi
    SLEEP=$SLEEP_S
  fi
  N=$((N+1)); [ "$MAX_CYCLES" != 0 ] && [ "$N" -ge "$MAX_CYCLES" ] && { log "MAX_CYCLES reached"; break; }
  sleep "$SLEEP"
done
check_sealed
setstate SHUTDOWN "clean exit after $N cycles"
log "SHUTDOWN clean ($N cycles)"; rmdir "$LOCK" 2>/dev/null; exit 0
