#!/usr/bin/env bash
# V8 publication 48h loop — watch/dispatch only, never commits or pushes.
# Design: docs/design/v8_publication_48h_loop_260901.md (R8-D3)
# Stop:   touch outputs/timeseries_v8/publication_loop/ABORT
set -u

ROOT="C:/workspace/ai-investing"
DIR="$ROOT/outputs/timeseries_v8/publication_loop"
PY="$ROOT/.venv/Scripts/python.exe"
LOG="$DIR/loop.log"
STATE="$DIR/state.json"
END_TS=$(( $(date +%s) + 48*3600 ))
LAST_DISPATCH=0
SUCCESS_SINCE=0

log(){ echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

field(){ # $1 json, $2 python expr over dict d
  "$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print(eval(sys.argv[2]))" "$1" "$2" 2>/dev/null
}

wait_run(){ # $1 workflow file — wait for the latest dispatched run to finish (~25 min cap)
  local wf="$1" i=0 st=""
  while [ $i -lt 50 ]; do
    sleep 30
    st=$(gh run list --workflow="$wf" --event workflow_dispatch --limit 1 \
         --json status,conclusion --jq '.[0].status+"/"+(.[0].conclusion//"")' 2>>"$LOG")
    case "$st" in completed/*) echo "$st"; return 0;; esac
    i=$((i+1))
  done
  echo "timeout:$st"; return 1
}

log "=== V8 publication loop start (48h horizon, ends $(date -u -d @$END_TS +%FT%TZ 2>/dev/null || echo +48h)) ==="
while :; do
  if [ -f "$DIR/ABORT" ]; then log "ABORT file found — exiting"; break; fi
  now=$(date +%s)
  if [ "$now" -ge "$END_TS" ]; then log "48h horizon reached — exiting"; break; fi

  git -C "$ROOT" fetch origin main >/dev/null 2>>"$LOG"
  status_json=$("$PY" "$DIR/check_state.py" 2>>"$LOG")
  if [ -n "$status_json" ]; then
    echo "$status_json" > "$STATE"
    log "state: $status_json"
  else
    log "probe failed — retrying next cycle"
    sleep 600
    continue
  fi

  op=$(field "$status_json" "d.get('operational_pass')")
  live_ok=$(field "$status_json" "(d.get('live') or {}).get('status')=='shadow_live'")

  if [ "$op" = "True" ] && [ "$live_ok" = "True" ]; then
    if [ "$SUCCESS_SINCE" -eq 0 ]; then
      SUCCESS_SINCE=$now
      log "SUCCESS: operational gate PASS and live site serves shadow_live — holding 12h"
    elif [ $(( now - SUCCESS_SINCE )) -ge 43200 ]; then
      log "success held 12h — exiting"
      break
    fi
  else
    SUCCESS_SINCE=0
    # Cron schedules here have a 6-12h delay history; dispatch instead of waiting.
    # Both workflows are idempotent on unchanged data (append dedupe), and the
    # only dispatch targets are these two — the loop never touches anything else.
    if [ "$op" != "True" ] && [ $(( now - LAST_DISPATCH )) -ge 5400 ]; then
      log "operational HOLD — dispatching timeseries-v2-refresh"
      gh workflow run timeseries-v2-refresh.yml --ref main >>"$LOG" 2>&1
      sleep 60
      log "v2-refresh finished: $(wait_run timeseries-v2-refresh.yml)"
      log "dispatching timeseries-v8-shadow"
      gh workflow run timeseries-v8-shadow.yml --ref main >>"$LOG" 2>&1
      sleep 60
      log "v8-shadow finished: $(wait_run timeseries-v8-shadow.yml)"
      LAST_DISPATCH=$(date +%s)
      continue   # re-probe immediately after a dispatch round
    fi
  fi
  sleep 1800
done
log "=== V8 publication loop end ==="
