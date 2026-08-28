#!/usr/bin/env bash
# V8 게이트 캠페인 상시 루프 (git bash 전용, Claude 세션과 무관하게 지속).
#
# 목적: 다변량 시계열 publication gate 성공을 향한 무인 진행.
#   - 홀드아웃 결과가 나오면 원장 기록으로 판정하고 모드를 전환한다.
#   - explore 모드: 사전등록 그리드 내 잔여 조합을 design window(2019-blind,
#     2000 paths)에서 순차 평가 (예산 = 원장 행수 <= 24, 코드가 강제).
#   - monitor 모드(홀드아웃 통과 후): 24시간마다 verify + hermetic 테스트.
#
# 하드 규칙 (이 스크립트가 절대 하지 않는 것):
#   - 봉인 2019+ 평가 실행/생성 (코드 경로도 없음)
#   - 새 홀드아웃 소모 (이미 승인·개시된 E10 채점의 '재개'만 허용 — 원장에
#     행이 없고 프로세스가 죽었을 때, 승인 마커의 config 그대로)
#   - 그리드 밖 config, 계약/원장 수정, git push (로컬 저장소 상태만 사용)
#
# 사용:
#   시작:  nohup bash tools/weekend_loop.sh >> outputs/timeseries_v8/loop/nohup.log 2>&1 &
#   상태:  tail -20 outputs/timeseries_v8/loop/loop.log
#   중단:  touch outputs/timeseries_v8/loop/ABORT
#   스모크: SMOKE=1 bash tools/weekend_loop.sh   (실평가 없이 한 사이클 검증)

set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
PY=".venv/Scripts/python.exe"
LOOPDIR="outputs/timeseries_v8/loop"
LOG="$LOOPDIR/loop.log"
QUEUE="$LOOPDIR/queue.jsonl"
LOCK="$LOOPDIR/lock"
LEDGER="data/timeseries_v8/ledgers/development_experiments.jsonl"
HOLDOUT="data/timeseries_v8/ledgers/holdout_scorings.jsonl"
APPROVAL="$LOOPDIR/holdout_approved_E10.json"
mkdir -p "$LOOPDIR"

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

# ── 단일 인스턴스 잠금 ──────────────────────────────────────────────────────
if ! mkdir "$LOCK" 2>/dev/null; then
  other="$(cat "$LOCK/pid" 2>/dev/null || echo '?')"
  if [ "$other" != "?" ] && kill -0 "$other" 2>/dev/null; then
    echo "loop already running (pid $other)"; exit 0
  fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"; log "loop exited"' EXIT
log "loop started (pid $$, SMOKE=${SMOKE:-0})"

# ── 승인 마커: 사용자 승인(R8-D1)으로 개시된 E10 홀드아웃의 재개 전용 ──────
if [ ! -f "$APPROVAL" ]; then
  cat > "$APPROVAL" <<'EOF'
{"approved": "R8-D1 user decision 2026-08-28", "role": "holdout", "label": "E10_holdout_scoring",
 "config": {"fhs_horizons": [21, 63], "blend_weight_by_horizon": {"21": 0.75, "63": 0.75}, "pit_recalibration_shrinkage": 0.5}}
EOF
fi

# ── 탐색 큐 (사전등록 그리드 내 조합만; 최초 1회 생성, 이후 수정 가능) ──────
if [ ! -f "$QUEUE" ]; then
  cat > "$QUEUE" <<'EOF'
{"label": "W1_blend_h21_75_h63_50", "config": {"fhs_horizons": [21, 63], "blend_weight_by_horizon": {"21": 0.75, "63": 0.5}, "pit_recalibration_shrinkage": 0.5}}
{"label": "W2_blend_h21_50_h63_75", "config": {"fhs_horizons": [21, 63], "blend_weight_by_horizon": {"21": 0.5, "63": 0.75}, "pit_recalibration_shrinkage": 0.5}}
{"label": "W3_tilt_blend_b4", "config": {"fhs_horizons": [21, 63], "fhs_tilt_omega": 0.25, "fhs_tilt_cap_sigma": 0.35, "blend_weight_by_horizon": {"21": 0.75, "63": 0.75}, "pit_recalibration_shrinkage": 0.5}}
{"label": "W4_mu_hat_10y", "config": {"fhs_horizons": [21, 63], "mu_hat_window_sessions": 2520, "blend_weight_by_horizon": {"21": 0.75, "63": 0.75}, "pit_recalibration_shrinkage": 0.5}}
EOF
fi

verify_fail_streak=0
last_monitor_check=0

while true; do
  # 1) 우아한 중단
  if [ -f "$LOOPDIR/ABORT" ]; then log "ABORT file present - stopping"; exit 0; fi

  # 2) fail-closed 검증 (3연속 실패 시 정지)
  if ! "$PY" -m ai_fc timeseries-v8-verify > "$LOOPDIR/verify_last.json" 2>&1; then
    verify_fail_streak=$((verify_fail_streak + 1))
    log "verify FAILED (streak $verify_fail_streak) - see verify_last.json"
    if [ "$verify_fail_streak" -ge 3 ]; then log "verify failed 3x - HOLD, stopping"; exit 2; fi
    sleep 300; continue
  fi
  verify_fail_streak=0

  # 3) 홀드아웃 판정 / 재개
  if [ -f "$HOLDOUT" ]; then
    verdict="$("$PY" - <<'EOF'
import json
from pathlib import Path
rows = [json.loads(l) for l in Path("data/timeseries_v8/ledgers/holdout_scorings.jsonl").read_text(encoding="utf-8").splitlines() if l]
r = rows[-1]
h = r["horizons"]
long_mean = (float(h["21"]["crps_improvement_vs_best"]) + float(h["63"]["crps_improvement_vs_best"])) / 2
print(json.dumps({"pass": bool(r["proxy"]["pass"]), "long_mean": long_mean,
                  "ci_up": r["paired_long_horizon"]["ci90"]["upper"], "id": r["experiment_id"]}))
EOF
)"
    echo "$verdict" > "$LOOPDIR/holdout_verdict.json"
    if echo "$verdict" | grep -q '"pass": true'; then MODE=monitor; else MODE=explore; fi
  else
    # 원장 행 없음: 실행 중이면 대기, 죽었으면 승인된 채점을 '재개' (멱등).
    # 홀드아웃은 2GB+ 메모리를 쓰므로 1GB+ python 프로세스 존재를 생존 신호로 본다.
    if tasklist //FI "IMAGENAME eq python.exe" //FI "MEMUSAGE gt 1000000" 2>/dev/null | grep -q "python.exe"; then
      log "holdout ledger absent; large python process alive - waiting"
      [ "${SMOKE:-0}" = "1" ] && { log "SMOKE cycle done (wait branch)"; exit 0; }
      sleep 300; continue
    fi
    log "holdout ledger absent and no python process - RESUMING approved E10 scoring"
    [ "${SMOKE:-0}" = "1" ] && { log "SMOKE cycle done (would resume holdout)"; exit 0; }
    cfg="$("$PY" -c "import json;print(json.dumps(json.load(open(r'$APPROVAL'))['config']))")"
    "$PY" -m ai_fc timeseries-v8-dev-backtest --role holdout --label E10_holdout_scoring \
      --config "$cfg" >> "$LOOPDIR/holdout_resume.log" 2>&1
    continue
  fi

  # 4) 모드별 진행
  if [ "$MODE" = "monitor" ]; then
    now=$(date +%s)
    if [ $((now - last_monitor_check)) -ge 86400 ]; then
      log "monitor: daily hermetic tests"
      if "$PY" -m pytest src/tests/test_multivariate_timeseries_v8.py -q -p no:cacheprovider >> "$LOG" 2>&1; then
        log "monitor: tests green; holdout verdict $(cat "$LOOPDIR/holdout_verdict.json")"
      else
        log "monitor: TESTS FAILED - inspect"
      fi
      last_monitor_check=$now
    fi
    [ "${SMOKE:-0}" = "1" ] && { log "SMOKE cycle done (monitor)"; exit 0; }
    sleep 3600; continue
  fi

  # explore: 예산 확인 후 큐에서 미실행 항목 실행
  rows=$(grep -c . "$LEDGER" 2>/dev/null || echo 0)
  if [ "$rows" -ge 24 ]; then log "explore: budget exhausted ($rows/24) - stopping"; exit 0; fi
  item="$("$PY" - <<'EOF'
import json
from pathlib import Path
ledger = Path("data/timeseries_v8/ledgers/development_experiments.jsonl")
done = {json.loads(l)["experiment_label"] for l in ledger.read_text(encoding="utf-8").splitlines() if l} if ledger.is_file() else set()
for line in Path("outputs/timeseries_v8/loop/queue.jsonl").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    item = json.loads(line)
    if item["label"] not in done:
        print(json.dumps(item))
        break
EOF
)"
  if [ -z "$item" ]; then log "explore: queue drained - champion stands; stopping"; exit 0; fi
  label="$(echo "$item" | "$PY" -c "import json,sys;print(json.load(sys.stdin)['label'])")"
  cfg="$(echo "$item" | "$PY" -c "import json,sys;print(json.dumps(json.load(sys.stdin)['config']))")"
  log "explore: running $label"
  [ "${SMOKE:-0}" = "1" ] && { log "SMOKE cycle done (would run $label)"; exit 0; }
  if "$PY" -m ai_fc timeseries-v8-dev-backtest --label "$label" --config "$cfg" \
      > "$LOOPDIR/run_${label}.json" 2>&1; then
    summary="$("$PY" - <<EOF
import json
from pathlib import Path
rows=[json.loads(l) for l in Path("$LEDGER").read_text(encoding="utf-8").splitlines() if l]
r=rows[-1]; h=r["horizons"]
lm=(float(h["21"]["crps_improvement_vs_best"])+float(h["63"]["crps_improvement_vs_best"]))/2
print(f"{r['experiment_label']} long_mean={lm*100:+.2f}% proxy_pass={r['proxy']['pass']}")
EOF
)"
    log "explore: done - $summary"
  else
    log "explore: $label FAILED - see run_${label}.json"
    sleep 120
  fi
  sleep 10
done
