#!/usr/bin/env bash
# tools/sunday_opus_loop.sh — Opus ralph supervisor for the V12 Sunday loop (Git Bash). 0 backtests by construction.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
PY=".venv/Scripts/python.exe"; [ -x "$PY" ] || PY="python"
export PYTHONUTF8=1; unset FRED_API_KEY ALPHAVANTAGE_KEY OPENAI_API_KEY 2>/dev/null || true
LOOPDIR="outputs/timeseries_v12/loop"; mkdir -p "$LOOPDIR/results" "$LOOPDIR/logs"
BACKLOG="data/timeseries_v12/ralph/V12_SUNDAY_BACKLOG_260904.json"
MASTER="data/timeseries_v12/ralph/OPUS_MASTER_PROMPT_V12_SUNDAY_260904.md"
LOCK="$LOOPDIR/lock"; ABORT="$LOOPDIR/ABORT"; STATE="$LOOPDIR/state.json"
DEADLINE="${LOOP_DEADLINE_EPOCH:-1788739200}"; MONDAY="${MONDAY_CKPT_EPOCH:-1788706800}"
MODEL="${LOOP_MODEL:-opus}"; DRY_RUN="${DRY_RUN:-0}"; MAX_ITER="${MAX_ITER:-40}"; WAIT="${ITER_WAIT:-30}"
SEALED_PREFIX="e3ff2fdb"
log(){ printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOOPDIR/logs/loop_$(date +%Y%m%d).log"; }
halt(){ log "HALT: $1"; rmdir "$LOCK" 2>/dev/null; exit 1; }
sealed_hash(){ { find src/ai_fc/timeseries_v8 -type f -name '*.py' -exec sha256sum {} \; ; find src/ai_fc/timeseries_v2 -maxdepth 1 -type f -name '*.py' -exec sha256sum {} \; ; } 2>/dev/null | sort | sha256sum | cut -d' ' -f1; }
if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; else
  OLD=$(cat "$LOCK/pid" 2>/dev/null || echo 0); kill -0 "$OLD" 2>/dev/null && { echo "running pid=$OLD"; exit 0; } || { log "stale lock reclaimed"; echo $$ > "$LOCK/pid"; }; fi
trap 'log "signal shutdown"; rmdir "$LOCK" 2>/dev/null; exit 0' INT TERM
# PRE-FLIGHT
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] && halt "branch main forbidden"
[ -f "$BACKLOG" ] && [ -f "$MASTER" ] || halt "backlog/master missing"
command -v claude >/dev/null || halt "claude CLI missing"
START="${LOOP_START_EPOCH:-1788652800}"
if [ "$(date +%s)" -lt "$START" ]; then
  log "PRE-START: sleeping until start epoch $START ($(date -d @"$START" 2>/dev/null)) — ABORT file cancels"
  while [ "$(date +%s)" -lt "$START" ]; do [ -f "$ABORT" ] && { log "ABORT during pre-start"; rmdir "$LOCK" 2>/dev/null; exit 0; }; sleep 60; done
fi
BASE=$(sealed_hash); echo "$BASE" > "$LOOPDIR/sealed_baseline.hash"; log "BOOT sealed_baseline=$BASE deadline=$DEADLINE model=$MODEL"
LEDGER_BASE=$(cat data/timeseries_v8/ledgers/*.jsonl 2>/dev/null | sha256sum | cut -d' ' -f1); echo "$LEDGER_BASE" > "$LOOPDIR/ledger_baseline.hash"
check_invariants(){ [ "$(sealed_hash)" = "$BASE" ] || halt "SEALED FILES CHANGED"; [ "$(cat data/timeseries_v8/ledgers/*.jsonl 2>/dev/null | sha256sum | cut -d' ' -f1)" = "$LEDGER_BASE" ] || halt "LEDGER CHANGED"; }
next_task(){ "$PY" - "$BACKLOG" <<'PYEOF'
import json,sys; b=json.load(open(sys.argv[1])); done={t["id"] for t in b["tasks"] if t["status"] in("완료","부분완료")}
c=[t for t in b["tasks"] if t["status"]=="대기" and all(d in done for d in t["deps"])]
print(json.dumps(min(c,key=lambda t:t["priority"]),ensure_ascii=False) if c else "")
PYEOF
}
set_status(){ "$PY" - "$BACKLOG" "$1" "$2" <<'PYEOF'
import json,sys; p,i,s=sys.argv[1:4]; b=json.load(open(p))
for t in b["tasks"]:
    if t["id"]==i: t["status"]=s
json.dump(b,open(p,"w"),ensure_ascii=False,indent=1)
PYEOF
}
N=0; CKPT_DONE=0
while :; do
  [ -f "$ABORT" ] && { log "ABORT"; break; }
  NOW=$(date +%s); [ "$NOW" -ge "$DEADLINE" ] && { log "DEADLINE reached"; break; }
  [ "$NOW" -ge "$MONDAY" ] && [ "$CKPT_DONE" = 0 ] && { log "MONDAY CHECKPOINT — sealing S1~S3 hashes"; sha256sum docs/review/*.md docs/design/v12_*.md 2>/dev/null > "$LOOPDIR/monday_ckpt.sha256"; CKPT_DONE=1; }
  check_invariants
  T=$(next_task); [ -z "$T" ] && { log "backlog drained"; break; }
  TID=$(echo "$T" | "$PY" -c "import json,sys;print(json.load(sys.stdin)['id'])"); BUD=$(echo "$T" | "$PY" -c "import json,sys;print(json.load(sys.stdin).get('stage_budget_sec',0))")
  set_status "$TID" 진행; log "ITER $N task=$TID"
  ENV="[TASK ENVELOPE]\nnow_epoch=$NOW deadline_epoch=$DEADLINE stage_budget_sec=$BUD\n$T\n[END ENVELOPE]\n$(cat "$MASTER")"
  if [ "$DRY_RUN" = 1 ]; then log "DRY: would run claude -p --model $MODEL for $TID"; set_status "$TID" 완료; else
    OUT="$LOOPDIR/logs/${TID}_$(date +%H%M%S).log"
    printf '%b' "$ENV" | timeout "${BUD:-14400}" claude -p --model "$MODEL" --permission-mode acceptEdits > "$OUT" 2>&1; RC=$?
    ST=$(grep -oE 'RESULT: (완료|부분완료|차단)' "$OUT" | tail -1 | awk '{print $2}')
    [ $RC -eq 124 ] && ST=부분완료; [ -z "$ST" ] && ST=차단
    set_status "$TID" "$ST"; log "ITER $N task=$TID rc=$RC status=$ST"
    [ "$ST" = 차단 ] && { BL=$((${BL:-0}+1)); [ "$BL" -ge 3 ] && { log "blocker x3"; break; }; }
  fi
  check_invariants
  N=$((N+1)); [ "$N" -ge "$MAX_ITER" ] && { log "MAX_ITER"; break; }
  sleep "$WAIT"
done
"$PY" -c "import json,time;json.dump({'ended':time.time(),'iters':$N},open('$STATE','w'))"
log "SHUTDOWN ($N iters)"; rmdir "$LOCK" 2>/dev/null; exit 0
