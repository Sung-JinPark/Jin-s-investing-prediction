# [설계도] V8 주말 상시 루프 — Git Bash 감독자 (2026-08-28)

> 배치 위치: `docs/timeseries_v8/WEEKEND_LOOP_DESIGN.md`. 구현: `tools/weekend_loop.sh`.
> 원칙: 루프는 **감독자(supervisor)**일 뿐 판단자가 아니다 — 큐·예산·가드의 정본은 기존
> 하네스(`tools/ralph_timeseries_v8.py`)이며, 루프는 그것을 호출·감시·재개한다.

## 1. 상태 기계

```
BOOT → PRE-FLIGHT ──(실패)──────────────→ HALT(사유 기록)
         │(통과)
         ▼
   MODE-DETECT ──(holdout 원장에 PASS 행)──→ MODE-B (감시·누적)
         │(원장 없음/미결/실패)                     │ 24h 주기: ops_status+verify+hermetic
         ▼                                          │ ABORT/기한 → SHUTDOWN
      MODE-A (탐색)                                 │
  next→backtest→record→local commit                 │
         │                                          │
  정지규칙 충족(예산·큐소진·2연속 무개선) ─────────→ MODE-B
         │
  ABORT 파일 / 기한(월 07:00 KST) / blocker 3회 → SHUTDOWN(state 봉인)
```

모드 전환은 **매 사이클 재판정**한다(주말 중 홀드아웃 채점이 끝나면 자동으로 B로 좁아짐).

## 2. 하드 라인 → 구현 지점 매핑 (요청서 §2 전부)

| 금지 | 구현 |
|---|---|
| 봉인 2019+ 평가 | ① 명령 화이트리스트 4개 외 실행 불가 ② 조합 JSON·명령 문자열에 `sealed` 포함 시 즉시 HALT |
| 홀드아웃 자동 소모 | 화이트리스트에 holdout 채점 verb 자체가 없음. 존재 여부는 **읽기만** |
| 그리드 밖 탐색 | 큐 산출은 하네스 `next`만 — 루프는 조합을 생성하지 않는다. 코드 레벨 거부는 `build_config_from_grids` 이중선 |
| 예산 24회 초과 | 실행 전 bash에서 원장 행수 재확인(<24) + 코드 거부 이중선 |
| 불변 좌표·계약 yaml | 루프는 `data/contracts/`·`forecasts/`·`calibration/`에 쓰기 없음. 커밋 대상은 원장·outputs·state뿐(경로 화이트리스트 add) |
| main 직접 커밋 | 시작 시 브랜치≠main 강제, 위반 시 HALT. push/PR verb 없음 |
| 시크릿 무로드 | 시작 시 `FRED_API_KEY` 등 환경변수 unset (sanitize) |

## 3. 상시 실행·재개 (요청서 §4)

- **구동**: `nohup bash tools/weekend_loop.sh >> outputs/timeseries_v8/loop/nohup.out 2>&1 &`
  — Git Bash(mintty) 창을 닫아도 지속. **주의**: Windows 절전은 프로세스를 멈춘다 →
  주말 전 전원 옵션에서 절전 해제(또는 `powercfg /change standby-timeout-ac 0`).
- **재부팅/크래시 재개**: 같은 명령 재실행. BOOT에서 state.json↔원장을 대사 —
  state가 "실행 중 L"인데 원장에 L 행이 없으면 **동일 명령 재실행**(결정론·멱등 —
  동일 config → 동일 experiment_id, 원장 중복 없음. 요청서 §1 보장 활용).
- **이중 실행 방지**: `mkdir` 원자 락 + PID 기록. PID 사망 확인 시 스테일 락 회수.
- **우아한 중단**: `touch outputs/timeseries_v8/loop/ABORT` → 현재 스텝 종료 후 정지.
- **상태**: `state.json` = {mode, cycle, last_experiment, budget_used, ts, note} — 매 전이 갱신.
- **로그**: 일자별 `loop_YYYYMMDD.log` 회전, 스텝 실패 시 마지막 40줄을 state.note에 복사.
- **환경**: `.venv/Scripts/python.exe` 고정, `PYTHONUTF8=1`, 저장소 루트 상대경로.
  scipy 1.17.1·pyarrow 24.0.0 핀 유지 — 루프는 pip 명령을 절대 실행하지 않는다.

## 4. ADAPT 포인트 — **확정 완료 (2026-08-28 Code 세션, 실제 소스 대조)**

1. **확정**: `next`/`record`/`status` 모두 **run_id 필수 인자**. run_id는
   `outputs/timeseries_v8/loop/harness_run_id` 파일이 정본이며(세션이 init 후 기록),
   파일 부재·status 실패 시 탐색 포기 → MODE-B only. `next` 출력은
   `{"next": {"label","config"}, "command": ...}`, 큐 소진 시 `{"next": null}` —
   파서는 raw_decode로 첫 JSON 객체만 읽는다(status는 객체 2개를 출력).
2. **확정**: `record <run_id> --experiment-id <id>` — 라벨이 아니라 id. 방금 append된
   원장 마지막 행에서 `experiment_label` 일치를 확인하고 `experiment_id`를 회수해 전달.
3. **확정**: 정지 판정의 정본은 `status` JSON의 `status` 필드 —
   `running` 이외(blocked/hold/proxy_green/stop_loss_triggered/aborted)면 탐색 중단.
   (문자열 grep "stop"은 hold/blocked/proxy_green을 놓치므로 폐기.)

**MODE-W 복원**: 홀드아웃 원장 부재 + 승인 마커(`holdout_approved_E10.json`) 존재 시,
대형 python 프로세스(또는 기록된 holdout.pid) 생존이면 대기, 사망이면 **동일 config의
승인된 홀드아웃 채점만 멱등 재개**(신규 소모 아님 — 동일 experiment_id, 중복 거부).
원장에 행이 생기면 proxy.pass로 B/A 분기. 홀드아웃 채점 verb를 새로 만드는 일은 없다.
주말 하네스 런: `tsv8-ralph-20260828T081020Z` (max-iterations 12, max-hours 72,
큐 = W1~W4 잔여 그리드 조합).

## 5. 드라이런·스모크 (요청서 §4 요구)

- **드라이런**: `DRY_RUN=1 bash tools/weekend_loop.sh` — 실행 대신 명령 문자열만 로그.
  PRE-FLIGHT·모드판정·가드 전부 실동작, backtest만 skip.
- **10분 스모크**: `SMOKE=1 MAX_CYCLES=1 bash tools/weekend_loop.sh` — MODE-B 1사이클
  (ops_status+verify+hermetic)만 수행 후 정상 SHUTDOWN·state 확인. 탐색 스모크는
  Code 세션에서 하네스 인터페이스 확정 후 `MAX_CYCLES=1`로 1실험(≈13분) 실행.

## 6. 산출·커밋 규약

로컬 커밋 메시지: `loop(v8): record <experiment_id> [budget k/24]` — 대상 경로 화이트리스트
(`data/timeseries_v8/ledgers/development_experiments.jsonl`, `outputs/timeseries_v8/`)만 add.
월요일 세션 체크리스트: ABORT → 로그·state 검토 → hermetic 재실행 → inventory 재생성
(`cd src && python -m ai_fc inventory`) → 브랜치 정리·PR (push는 사람/Code 세션).
