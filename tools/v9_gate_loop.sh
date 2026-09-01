#!/usr/bin/env bash
# tools/v9_gate_loop.sh - V9 research gate supervisor (Git Bash). See docs/design/v9_gate_autoloop_260901.md
# Supervises DESIGN iterations only. Stops at HOLDOUT-READY for human decision. Never touches sealed/holdout automatically.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python"
export PYTHONUTF8=1
unset FRED_API_KEY ALPHAVANTAGE_KEY OPENAI_API_KEY 2>/dev/null || true

LOOPDIR="outputs/timeseries_v9/loop"; mkdir -p "$LOOPDIR"
LOCK="$LOOPDIR/lock"; STATE="$LOOPDIR/state.json"; ABORT="$LOOPDIR/ABORT"
LEDGER="data/timeseries_v9/ledgers/development_experiments.jsonl"
HOLDOUT="data/timeseries_v9/ledgers/holdout_scorings.jsonl"
V8_SEALED_DIR="src/ai_fc/timeseries_v8"
MAX_BUDGET="${MAX_BUDGET:-24}"; SLEEP_E=60; SLEEP_S=1800
MAX_CYCLES="${MAX_CYCLES:-0}"; DRY_RUN="${DRY_RUN:-0}"; SMOKE="${SMOKE:-0}"
DEADLINE="${LOOP_DEADLINE_EPOCH:-$(( $(date +%s)+48*3600 ))}"

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
tnote(){ tail -n 40 "$LOOPDIR/loop_$(date +%Y%m%d).log" 2>/dev/null | tr '\n' '|'; }

# lock
if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; else
  OLD=$(cat "$LOCK/pid" 2>/dev/null || echo 0)
  kill -0 "$OLD" 2>/dev/null && { echo "already running pid=$OLD"; exit 0; } || { log "stale lock reclaimed"; echo $$ > "$LOCK/pid"; }
fi
trap 'log "signal shutdown"; setstate SHUTDOWN "signal"; rmdir "$LOCK" 2>/dev/null; exit 0' INT TERM

# PRE-FLIGHT
BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
[ "$BR" = "main" ] && halt "branch is main - forbidden"
[ -d "src/ai_fc/timeseries_v9" ] || halt "v9 package missing (run G0 first)"
"$PY" -c "import scipy,pyarrow,numpy" 2>/dev/null || halt "venv import preflight failed"
# record V8 sealed hash baseline for tamper check
V8HASH=$(find "$V8_SEALED_DIR" -type f -name '*.py' -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
echo "$V8HASH" > "$LOOPDIR/v8_sealed_baseline.hash"
log "BOOT branch=$BR v8_sealed_baseline=$V8HASH deadline=$(date -d @"$DEADLINE" 2>/dev/null || echo "$DEADLINE")"
setstate BOOT "preflight ok"

check_v8_untouched(){
  local now; now=$(find "$V8_SEALED_DIR" -type f -name '*.py' -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
  [ "$now" = "$(cat "$LOOPDIR/v8_sealed_baseline.hash")" ] || halt "V8 SEALED FILES CHANGED - abort"
}
budget_used(){ [ -f "$LEDGER" ] && grep -c . "$LEDGER" || echo 0; }
detect_mode(){
  [ "$SMOKE" = 1 ] && { echo SHADOW; return; }
  "$PY" - "$HOLDOUT" <<'PYEOF'
import json,sys,os
p=sys.argv[1]
if not os.path.exists(p): print("EXPLORE"); raise SystemExit
ok=False
for line in open(p,encoding="utf-8"):
    line=line.strip()
    if not line: continue
    try: r=json.loads(line)
    except Exception: continue
    lt=r.get("holdout_long_mean", r.get("long_horizon_mean_skill"))
    ci=r.get("ci90_upper")
    if lt is not None and ci is not None and float(lt)>=0.02 and float(ci)<=0: ok=True
print("SHADOW" if ok else "EXPLORE")
PYEOF
}

run_explore(){
  check_v8_untouched
  U=$(budget_used); [ "$U" -ge "$MAX_BUDGET" ] && { log "budget exhausted ($U/$MAX_BUDGET)"; return 1; }
  # ADAPT: harness next -> {label, config}. If absent, stop (no guessing).
  NEXT=$("$PY" tools/ralph_timeseries_v9.py next 2>>"$LOOPDIR/harness.err") || { log "harness next unavailable -> stop explore"; return 1; }
  [ -z "$NEXT" ] && { log "queue empty"; return 1; }
  echo "$NEXT" | grep -qiE "sealed|holdout" && halt "forbidden verb in next()"
  LABEL=$(echo "$NEXT" | "$PY" -c "import json,sys;print(json.load(sys.stdin).get('label',''))" 2>/dev/null)
  CFG=$(echo "$NEXT" | "$PY" -c "import json,sys;print(json.dumps(json.load(sys.stdin).get('config',{}),ensure_ascii=False))" 2>/dev/null)
  { [ -z "$LABEL" ] || [ -z "$CFG" ]; } && { log "next() parse mismatch -> stop explore"; return 1; }
  log "EXPLORE run $LABEL budget=$U/$MAX_BUDGET"
  [ "$DRY_RUN" = 1 ] && { log "DRY: v9-dev-backtest --label $LABEL"; return 0; }
  "$PY" -m ai_fc timeseries-v9-dev-backtest --label "$LABEL" --config "$CFG" >> "$LOOPDIR/backtest_$LABEL.log" 2>&1
  RC=$?; [ $RC -ne 0 ] && { log "backtest rc=$RC ($LABEL)"; setstate EXPLORE "fail $LABEL | $(tnote)"; return 0; }
  "$PY" tools/ralph_timeseries_v9.py record --label "$LABEL" >>"$LOOPDIR/harness.err" 2>&1 || log "WARN record failed $LABEL"
  git add "$LEDGER" "outputs/timeseries_v9" 2>/dev/null
  git commit -q -m "loop(v9): record $LABEL [budget $(budget_used)/$MAX_BUDGET]" 2>/dev/null || true
  # champion found? -> stop for human (holdout is not auto-consumed)
  CHAMP=$("$PY" tools/ralph_timeseries_v9.py status 2>/dev/null | grep -ci "champion" || true)
  [ "${CHAMP:-0}" -gt 0 ] && { log "CHAMPION found -> HOLDOUT-READY, stopping for user decision"; setstate HOLDOUT-READY "champion; awaiting user"; return 2; }
  return 0
}
run_shadow(){
  log "SHADOW monitor"
  [ "$DRY_RUN" = 1 ] && { log "DRY: v9-verify + hermetic"; return 0; }
  "$PY" -m ai_fc timeseries-v9-verify >> "$LOOPDIR/verify.log" 2>&1 || log "WARN verify failed"
  ( cd src && "../$PY" -m pytest tests/test_multivariate_timeseries_v9.py -q ) >> "$LOOPDIR/hermetic.log" 2>&1 || log "WARN hermetic failed"
  setstate SHADOW "monitor done | $(tnote)"
}

N=0; LAST_S=0
while :; do
  [ -f "$ABORT" ] && { log "ABORT -> shutdown"; break; }
  NOW=$(date +%s); [ "$NOW" -ge "$DEADLINE" ] && { log "deadline reached"; break; }
  MODE=$(detect_mode); setstate "$MODE" "cycle start"
  if [ "$MODE" = "EXPLORE" ]; then
    run_explore; RC=$?
    [ $RC -eq 2 ] && break   # HOLDOUT-READY: stop for human
    [ $RC -eq 1 ] && MODE=SHADOW
    SLEEP=$SLEEP_E
  fi
  if [ "$MODE" = "SHADOW" ]; then
    if [ $(( NOW - LAST_S )) -ge 86400 ] || [ "$SMOKE" = 1 ] || [ "$LAST_S" = 0 ]; then run_shadow; LAST_S=$NOW; fi
    SLEEP=$SLEEP_S
  fi
  N=$((N+1)); [ "$MAX_CYCLES" != 0 ] && [ "$N" -ge "$MAX_CYCLES" ] && { log "MAX_CYCLES reached"; break; }
  sleep "$SLEEP"
done
check_v8_untouched
setstate SHUTDOWN "clean exit after $N cycles"
log "SHUTDOWN clean ($N cycles)"; rmdir "$LOCK" 2>/dev/null; exit 0
