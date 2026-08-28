#!/usr/bin/env bash
# tools/weekend_loop.sh - V8 weekend supervisor (Git Bash / Windows). See docs/timeseries_v8/WEEKEND_LOOP_DESIGN.md
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python"
export PYTHONUTF8=1
unset FRED_API_KEY ALPHAVANTAGE_KEY OPENAI_API_KEY 2>/dev/null || true   # secrets sanitize

LOOPDIR="outputs/timeseries_v8/loop"; mkdir -p "$LOOPDIR"
LOCK="$LOOPDIR/lock"; STATE="$LOOPDIR/state.json"; ABORT="$LOOPDIR/ABORT"
LEDGER="data/timeseries_v8/ledgers/development_experiments.jsonl"
HOLDOUT="data/timeseries_v8/ledgers/holdout_scorings.jsonl"
HOLDOUT_MARKER="$LOOPDIR/holdout_approved_E10.json"
HARNESS="tools/ralph_timeseries_v8.py"
RUN_ID_FILE="$LOOPDIR/harness_run_id"
MAX_BUDGET=24; SLEEP_A=60; SLEEP_B=1800; SLEEP_W=120
MAX_CYCLES="${MAX_CYCLES:-0}"; DRY_RUN="${DRY_RUN:-0}"; SMOKE="${SMOKE:-0}"
DEADLINE="${LOOP_DEADLINE_EPOCH:-0}"
if [ "$DEADLINE" = 0 ]; then DEADLINE=$(date -d "next monday 07:00" +%s 2>/dev/null || echo $(( $(date +%s)+60*60*60 ))); fi

log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOOPDIR/loop_$(date +%Y%m%d).log"; }
state(){ "$PY" - "$STATE" "$1" "$2" <<'PYEOF'
import json,sys,datetime
p,mode,note=sys.argv[1],sys.argv[2],sys.argv[3]
try: s=json.load(open(p))
except Exception: s={"cycle":0}
s.update(mode=mode,note=note[:4000],ts=datetime.datetime.now().isoformat())
s["cycle"]=s.get("cycle",0)+ (1 if mode in("A","B","W") else 0)
json.dump(s,open(p,"w"),ensure_ascii=False,indent=1)
PYEOF
}
halt(){ log "HALT: $1"; state HALT "$1"; rmdir "$LOCK" 2>/dev/null; exit "${2:-1}"; }
tail_note(){ tail -n 40 "$LOOPDIR/loop_$(date +%Y%m%d).log" 2>/dev/null | tr '\n' '|'; }
# first JSON object from stdin (harness prints indented JSON, status prints two objects)
jfirst(){ "$PY" -c "import json,sys;d,_=json.JSONDecoder().raw_decode(sys.stdin.read());print(json.dumps(d,ensure_ascii=False))"; }

# ---- lock (atomic mkdir) ----
if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; else
  OLD=$(cat "$LOCK/pid" 2>/dev/null || echo 0)
  if kill -0 "$OLD" 2>/dev/null; then echo "already running pid=$OLD"; exit 0
  else log "stale lock (pid=$OLD) reclaimed"; echo $$ > "$LOCK/pid"; fi
fi
trap 'log "signal shutdown"; state SHUTDOWN "signal"; rmdir "$LOCK" 2>/dev/null; exit 0' INT TERM

# ---- PRE-FLIGHT ----
BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
[ "$BR" = "main" ] && halt "branch is main - forbidden"
[ -f "$HARNESS" ] || halt "harness missing: $HARNESS"
"$PY" -c "import scipy,pyarrow" 2>/dev/null || halt "venv import preflight failed"
HARNESS_OK=1
RUN_ID=$(cat "$RUN_ID_FILE" 2>/dev/null | tr -d '[:space:]' || echo "")
# ADAPT-확정(1/3): status/next/record 는 run_id 가 필수 인자다. run_id 파일이 없거나
# status 가 실패하면 탐색을 포기하고 MODE-B 로만 감시한다 (무인 안전 우선).
if [ -z "$RUN_ID" ] || ! "$PY" "$HARNESS" status "$RUN_ID" >/dev/null 2>&1; then
  HARNESS_OK=0; log "WARN harness run_id/status unavailable -> MODE-B only"
fi
log "BOOT branch=$BR run_id=${RUN_ID:-none} deadline=$(date -d @"$DEADLINE" 2>/dev/null || echo "$DEADLINE") dry=$DRY_RUN smoke=$SMOKE"
state BOOT "preflight ok; harness_ok=$HARNESS_OK"

holdout_passed(){
  "$PY" - "$HOLDOUT" <<'PYEOF'
import json,sys,os
p=sys.argv[1]
ok=False
if os.path.exists(p):
    for line in open(p,encoding="utf-8"):
        line=line.strip()
        if not line: continue
        try: r=json.loads(line)
        except Exception: continue
        if r.get("window_role")=="holdout" and (r.get("proxy") or {}).get("pass") is True:
            ok=True
print("PASS" if ok else ("FAIL" if os.path.exists(p) else "ABSENT"))
PYEOF
}
detect_mode(){  # A=explore, B=monitor, W=wait/resume approved holdout
  [ "$SMOKE" = 1 ] && { echo B; return; }
  [ "$HARNESS_OK" = 0 ] && { echo B; return; }
  case "$(holdout_passed)" in
    PASS) echo B ;;
    FAIL) echo A ;;
    ABSENT) if [ -f "$HOLDOUT_MARKER" ]; then echo W; else echo A; fi ;;
  esac
}
budget_used(){ [ -f "$LEDGER" ] && grep -c . "$LEDGER" || echo 0; }
big_python_alive(){
  HP=$(cat "$LOOPDIR/holdout.pid" 2>/dev/null || echo 0)
  if [ "$HP" != 0 ] && kill -0 "$HP" 2>/dev/null; then return 0; fi
  # tasklist memory prints thousands separators ("871,856 K"): use the fixed
  # column layout (//NH, no CSV) and strip separators before comparing.
  tasklist //FI "IMAGENAME eq python.exe" //NH 2>/dev/null \
    | awk 'NF>=3 {v=$(NF-1); gsub(/[^0-9]/,"",v); if (v+0>800000) f=1} END{exit !f}'
}

run_mode_W(){
  # The single APPROVED holdout scoring (R8-D1). Never a new burn: identical
  # config -> identical experiment_id, and the pipeline refuses duplicates.
  if big_python_alive; then log "W: approved holdout still computing - waiting"; return 0; fi
  LABEL=$("$PY" -c "import json;print(json.load(open('$HOLDOUT_MARKER'))['label'])" 2>/dev/null)
  CFG=$("$PY" -c "import json;print(json.dumps(json.load(open('$HOLDOUT_MARKER'))['config'],ensure_ascii=False))" 2>/dev/null)
  { [ -z "$LABEL" ] || [ -z "$CFG" ]; } && { log "W: marker unreadable -> MODE-B"; HARNESS_OK=0; return 1; }
  echo "$CFG$LABEL" | grep -qi "sealed" && halt "sealed in holdout marker"
  log "W: resuming approved holdout $LABEL (process died without ledger row)"
  if [ "$DRY_RUN" = 1 ]; then log "DRY: $PY -m ai_fc timeseries-v8-dev-backtest --role holdout --label $LABEL --config $CFG"; return 0; fi
  "$PY" -m ai_fc timeseries-v8-dev-backtest --role holdout --label "$LABEL" --config "$CFG" \
    >> "$LOOPDIR/holdout_resume.log" 2>&1 &
  echo $! > "$LOOPDIR/holdout.pid"
}

run_mode_A(){
  U=$(budget_used); [ "$U" -ge $MAX_BUDGET ] && { log "budget exhausted ($U/$MAX_BUDGET) -> MODE-B"; return 1; }
  NEXT_JSON=$("$PY" "$HARNESS" next "$RUN_ID" 2>>"$LOOPDIR/harness.err" | jfirst) \
    || { log "harness next failed/blocked -> MODE-B"; return 1; }
  [ -z "$NEXT_JSON" ] && { log "queue empty -> MODE-B"; return 1; }
  echo "$NEXT_JSON" | grep -qi "sealed" && halt "sealed verb detected in next()"
  # ADAPT-확정(2/3): next 출력은 {"next": {"label","config"}, "command": ...} 이고
  # 큐 소진 시 {"next": null} 이다.
  LABEL=$(echo "$NEXT_JSON" | "$PY" -c "import json,sys;d=json.load(sys.stdin);n=d.get('next') or {};print(n.get('label',''))" 2>/dev/null)
  CFG=$(echo "$NEXT_JSON"   | "$PY" -c "import json,sys;d=json.load(sys.stdin);n=d.get('next') or {};print(json.dumps(n.get('config',{}),ensure_ascii=False) if n else '')" 2>/dev/null)
  { [ -z "$LABEL" ] || [ -z "$CFG" ]; } && { log "queue empty or parse mismatch -> MODE-B"; return 1; }
  echo "$CFG" | grep -qi "sealed" && halt "sealed in config"
  log "A: run $LABEL budget=$U/$MAX_BUDGET"
  CMD=("$PY" -m ai_fc timeseries-v8-dev-backtest --label "$LABEL" --config "$CFG")
  if [ "$DRY_RUN" = 1 ]; then log "DRY: ${CMD[*]}"; return 0; fi
  "${CMD[@]}" >> "$LOOPDIR/backtest_$LABEL.log" 2>&1
  RC=$?
  if [ $RC -ne 0 ]; then log "backtest rc=$RC ($LABEL)"; state A "backtest fail $LABEL rc=$RC | $(tail_note)"; return 0; fi
  # ADAPT-확정(2/3 계속): record 는 --experiment-id 를 받는다. 방금 append 된
  # 마지막 원장 행에서 라벨 일치를 확인하고 id 를 회수한다.
  EXP_ID=$("$PY" - "$LEDGER" "$LABEL" <<'PYEOF'
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1],encoding="utf-8") if l.strip()]
match=[r for r in rows if r.get("experiment_label")==sys.argv[2]]
print(match[-1]["experiment_id"] if match else "")
PYEOF
)
  if [ -n "$EXP_ID" ]; then
    "$PY" "$HARNESS" record "$RUN_ID" --experiment-id "$EXP_ID" >>"$LOOPDIR/harness.err" 2>&1 \
      || log "WARN record failed $LABEL ($EXP_ID)"
  else
    log "WARN no ledger row for $LABEL - record skipped"
  fi
  git add data/timeseries_v8 outputs/timeseries_v8/ralph 2>/dev/null
  git commit -q -m "loop(v8): record $LABEL [budget $(budget_used)/$MAX_BUDGET]" 2>/dev/null || true
  # ADAPT-확정(3/3): 정지 판정의 정본은 status JSON 의 status 필드다.
  # running 이외(blocked/hold/proxy_green/stop_loss_triggered/aborted)면 탐색 중단.
  ST=$("$PY" "$HARNESS" status "$RUN_ID" 2>/dev/null | jfirst \
    | "$PY" -c "import json,sys;print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
  [ "$ST" != "running" ] && { log "harness status=$ST -> MODE-B"; return 1; }
  return 0
}

run_mode_B(){
  log "B: monitor cycle"
  if [ "$DRY_RUN" = 1 ]; then log "DRY: ops_status/verify/pytest"; return 0; fi
  "$PY" tools/ops_status.py            >> "$LOOPDIR/ops_status.log" 2>&1 || log "WARN ops_status failed"
  "$PY" -m ai_fc timeseries-v8-verify  >> "$LOOPDIR/verify.log"    2>&1 || log "WARN verify failed"
  ( cd src && "../$PY" -m pytest tests/test_multivariate_timeseries_v8.py -q ) \
                                       >> "$LOOPDIR/hermetic.log"  2>&1 || log "WARN hermetic failed"
  state B "monitor done | $(tail_note)"
}

# ---- MAIN LOOP ----
N=0; LAST_B_TS=0
while :; do
  [ -f "$ABORT" ] && { log "ABORT file -> shutdown"; break; }
  NOW=$(date +%s); [ "$NOW" -ge "$DEADLINE" ] && { log "deadline reached"; break; }
  MODE=$(detect_mode); state "$MODE" "cycle start"
  if [ "$MODE" = "W" ]; then
    run_mode_W || MODE=B
    SLEEP=$SLEEP_W
  fi
  if [ "$MODE" = "A" ]; then
    run_mode_A || MODE=B
    SLEEP=$SLEEP_A
  fi
  if [ "$MODE" = "B" ]; then
    if [ $(( NOW - LAST_B_TS )) -ge 86400 ] || [ "$SMOKE" = 1 ] || [ "$LAST_B_TS" = 0 ]; then
      run_mode_B; LAST_B_TS=$NOW
    fi
    SLEEP=$SLEEP_B
  fi
  N=$((N+1)); [ "$MAX_CYCLES" != 0 ] && [ "$N" -ge "$MAX_CYCLES" ] && { log "MAX_CYCLES=$MAX_CYCLES reached"; break; }
  sleep "$SLEEP"
done
state SHUTDOWN "clean exit after $N cycles"
log "SHUTDOWN clean ($N cycles)"; rmdir "$LOCK" 2>/dev/null; exit 0
