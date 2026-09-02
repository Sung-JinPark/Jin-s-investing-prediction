# V10 게이트 자동화 루프 설계서 + 실행 프롬프트 (2026-09-02)

> 계보: `tools/v9_gate_loop.sh` + `tools/ralph_timeseries_v9.py` 승계. 데드라인 **2026-09-03 09:00 KST
> = 00:00 UTC = epoch 1788393600**. 18시간 창 시작 15:00 KST(epoch 1788328800).
> 루프는 **design 반복만** 수행한다. holdout·sealed verb는 하네스·CLI 양쪽에 존재하지 않는다.

---

## 1. 단계 구성

```
G0 (루프 밖, Code 세션 선행 ~2.5h)
  계약 yaml(원본 sha256 핀 2건·grid·3중 caveat) → timeseries_v10 포크 패키지(6파일)
  → identity_test (E0 비트동일: κ=0·γ=0·w=.75·isotonic off → V8 챔피언 scores 절대차 0)
  → CLI(dev-backtest·verify) → 하네스(next/record/status) → 루프 스크립트
  → DRY_RUN=1 → SMOKE=1 MAX_CYCLES=1
        │ (스모크 PASS ∧ V8/V2 봉인 해시 대사 ∧ 브랜치≠main)
        ▼
루프 BOOT → PRE-FLIGHT(락·해시 baseline·venv·패키지) → MODE-DETECT
        │
   EXPLORE: next(사전등록 큐) → identity_test → v10-dev-backtest(~14분) → record(원장 append)
            → gate_margin 진단 기록 → 로컬 커밋 → status(champion?)
        │
   정지: 예산 24 소진 · 큐 소진(next 빈 stdout) · 2연속 무개선(status) · stop-loss(12회 후 <+1%)
         · ABORT 파일 · 데드라인 epoch 1788393600 · V8/V2 해시 변화 · blocker 3회
        │
   champion → HOLDOUT-READY 정지 (사용자 대기 — 홀드아웃 자동 소모 없음)
```

## 2. 18시간 창 마일스톤 표 (실측 근거: design 백테스트 1회 ~14분, V9 7회 실측)

| KST | UTC | 단계 | 누적 실험 | 비고 |
|---|---|---|---|---|
| 15:00 | 06:00 | 세션 착수·배치·검증 | 0 | git fetch·브랜치 신설 |
| 15:20 | 06:20 | G0-1 계약 yaml + 원본 sha256 핀 | 0 | source_pins 2건 |
| 16:00 | 07:00 | G0-2 포크 패키지 6파일 | 0 | cp 사본 + W 분기 |
| 16:40 | 07:40 | G0-3 **identity_test PASS** | 0 | 비트동일 실패면 여기서 정지 |
| 17:10 | 08:10 | G0-4 CLI·하네스·루프 스크립트 | 0 | verb 부재 grep 검증 |
| 17:30 | 08:30 | DRY_RUN → SMOKE(1사이클 ≈15분) | 0 | 스모크 로그 확인 |
| **17:50** | **08:50** | **nohup 기동** (해시 대사·브랜치 전제) | 0 | 여기부터 무인 |
| 18:05 | 09:05 | E0 항등 실험 (원장 1행) | 1 | 게이트 여유 baseline |
| 18:50 | 09:50 | W1 κ=0.5 · W1 κ=1.0 · W3 γ=−0.10 | 4 | 1순위 축 |
| 19:35 | 10:35 | W3 γ=−0.20 · W1 민감도(c) · W2 S1 | 7 | |
| 20:20 | 11:20 | W2 S2 · S3 · W4a | 10 | |
| 21:05 | 12:05 | W4b · W5 h5 · W5 h1+h5 | **13** | 단독 12 완료 → stop-loss 판정 |
| 21:05~ | 12:05~ | (stop-loss 통과 시) 조합 ≤5 · 예비 | ≤24 | 조합은 사전등록된 것만 |
| ~23:40 | ~14:40 | 예산 24 소진 상한 | 24 | 이후 SHADOW 감시 모드 |
| 09:00(+1) | 00:00 | **데드라인 자동 정지** | — | state 봉인·보고 |

산술: 단독 13회 × 14분 = 182분 ≈ 3.0h + 실험 간 오버헤드(identity·commit ~1분) → **17:50
기동 시 21:05경 단독 격자 완료**, 데드라인까지 12h 여유. 조합 5 + 예비 6을 전부 써도 ~23:40 종료.
**여유의 용도는 속도가 아니라 안전 — 실패 재시도 1회·해시 이상 시 정지 후 사람 복귀 시간.**

## 3. 안전 경계 (계보 승계 + V10 추가)

| 경계 | 구현 |
|---|---|
| holdout·sealed verb 부재 | cli.py 서브커맨드 {dev-backtest, verify}만. 하네스 {next, record, status}만. 루프 PRE-FLIGHT에서 `grep -E "holdout\|sealed"`가 CLI·하네스 소스에 verb 정의 없음을 확인 |
| V8/V2 봉인 sha256 대사 | BOOT에서 `src/ai_fc/timeseries_v8/**`·V2 봉인 8파일 baseline 저장, **매 사이클 + 종료 시** 재계산 대조, 불일치 즉시 HALT |
| 원본 핀 대사 | 계약 source_pins(backtest.py·model.py sha256)를 매 사이클 검증 |
| 시크릿 미로드 | FRED_API_KEY 등 unset — design 백테스트는 커밋된 원장·번들만 사용 |
| main 금지 | BOOT에서 브랜치≠main 강제. 커밋은 원장·outputs 경로만 |
| 데드라인 | `LOOP_DEADLINE_EPOCH=1788393600` 고정 (환경변수 미설정 시 기본값도 이 값) |
| 예산 | 원장 행수 ≥ 24 → EXPLORE 종료. 코드(pipeline)도 이중 거부 |
| champion | status "champion:" 라인 감지 → HOLDOUT-READY 정지. **어떤 명령도 홀드아웃을 호출하지 않음** |
| 재개 | 같은 nohup 명령 — state↔원장 대사, 미기록 실험 재실행(결정론 멱등) |
| 중단 | `touch outputs/timeseries_v10/loop/ABORT` |

## 4. 스크립트 — v9_gate_loop.sh 대비 변경점만

- 경로 v9→v10 전환(LOOPDIR·LEDGER·HOLDOUT 원장·패키지·CLI·하네스·커밋 메시지 `loop(v10)`).
- `DEADLINE` 기본값 `1788393600` (V9의 now+48h 대체).
- 매 사이클 `check_sealed_untouched`에 **V2 봉인 8파일 + 계약 source_pins** 추가.
- EXPLORE 진입 시 `identity_test` 실행 — 실패면 해당 실험 무효·halt.
- record 후 `gate_margin` 필드 존재 검사(진단 의무).
- stop-loss: 원장 12행 도달 시 status가 최고 쌍대 개선 <+1% 보고하면 EXPLORE 종료.
- PRE-FLIGHT verb 부재 검사: `grep -qiE "holdout|sealed" src/ai_fc/timeseries_v10/cli.py tools/ralph_timeseries_v10.py && halt`.

---

## 5. 실행 프롬프트 (G0 구현 → 스모크 → 기동 세션용 — 그대로 붙여넣기)

```
NASDAQ_V10 설계 팩(v10_gate_precision_design_260902.md·v10_gate_autoloop_260902.md)을 이행한다.
C:/workspace/ai-investing 에서 git fetch 후 최신 main 확인, 브랜치 claude/v10-gate 신설(main 금지).
"사용자 결정 대기"로 명시된 두 정지점(홀드아웃 소모·봉인)을 제외하고 연속 실행하라.

[0 배치·검증] 두 설계서를 docs/design/에 배치, LF 정규화. 정밀 설계서 §0 실측 3건(E0 dev proxy
전부 통과·봉인창 hold 사유=GFC 누락·V9 exog 소진)을 원장에서 재현해 확인 로그 남김.

[G0-1 계약] data/contracts/multivariate_timeseries_v10.yaml: V8 계약 게이트 산술 그대로 복제
(publication/dev proxy 임계 무변경), source_pins{backtest.py,model.py}=현재 V8 원본 sha256,
grid=정밀 설계서 §3(W1 κ{0.5,1.0}+민감도·W3 γ{−.10,−.20}·W2 S1~S3·W4a/b·W5 h5/h1+h5·E0 항등),
budget=24, stop_loss(12회,<+1%), 3중 disclosure_caveat(V2·V8 2019+ 공개·V9 판정 공개·2022형 대리 부재).

[G0-2 포크] src/ai_fc/timeseries_v10/{__init__,backtest_fork,model_fork,state,identity_test,
pipeline,cli}.py — backtest_fork/model_fork는 V8 원본 cp 후 W 분기만 diff. state.py: EWMA(λ=.97)
분산비 + 2520일 기준선 + 1996~2004 워밍업 s≡1 + RV63/RV504 대조. W1은 B5 keep-마스크 가중
quantile(exp(−κ|s_t−s_i|))로만 — 인덱스 가중 금지(RNG 순서 보존). W3 w(s)=clip(.75+γ(s−1),.5,.9).

[G0-3 identity_test] 퇴화 파라미터(κ=0,γ=0,w=.75,isotonic off,[21,63])로 포크 실행 → V8 챔피언
design scores와 전 원점·전 지평 CRPS 절대차 0 단언. PASS 못 하면 여기서 정지·보고(추측 수정 금지).

[G0-4 CLI·하네스·루프] cli 서브커맨드 {timeseries-v10-dev-backtest, timeseries-v10-verify}만.
tools/ralph_timeseries_v10.py {next,record,status} — V9 인터페이스 승계(next: {label,config} JSON,
큐 소진 시 빈 stdout; status: champion 시 "champion:" 라인). tools/v10_gate_loop.sh = v9 계보 +
설계서 §4 변경점. holdout/sealed 문자열이 CLI·하네스에 없음을 grep으로 증명. hermetic 테스트:
락 이중실행·verb 부재·해시 변조 HALT·main 거부·identity 실패 무효 5케이스. inventory 재생성.

[스모크] DRY_RUN=1 bash tools/v10_gate_loop.sh → 로그에 가드·모드판정 확인.
SMOKE=1 MAX_CYCLES=1 → 1사이클 정상 SHUTDOWN + state.json 확인. 실패 시 기동 금지·보고.

[기동 — 전제 3건 충족 시에만] ① V8/V2 봉인 sha256이 baseline과 일치 ② 브랜치≠main
③ 스모크 PASS. 충족 시:
  nohup env LOOP_DEADLINE_EPOCH=1788393600 bash tools/v10_gate_loop.sh \
    >> outputs/timeseries_v10/loop/nohup.out 2>&1 &
기동 후 첫 실험(E0 항등) 원장 append와 state.json EXPLORE 전이를 확인하고 보고. Windows 절전
해제(powercfg /change standby-timeout-ac 0)를 사용자에게 안내.

[절대 규율] V8/V2 봉인 파일 0바이트 · 홀드아웃·봉인 자동 실행 금지(verb 부재) · 예산 24 · 그리드 밖
조합 0 · main 직접 커밋 0 · forecasts/·calibration/ 무접촉 · 시크릿 미로드 · 게이트 산술 무변경.
[정지점·보고] champion → HOLDOUT-READY 정지 후 사용자 질문. 데드라인 09-03 09:00 KST 자동 정지.
종료 상태 {HOLDOUT-READY, BUDGET-EXHAUSTED, STOP-LOSS, DEADLINE, BLOCKED} 중 하나를 gate_margin
표·쌍대 개선 표와 함께 보고. push/PR은 하지 말 것.
```

---

## 6. 사용자 결정 대기 (변동 없음 — 최종 설계서 §9)
V10-D1 개시(지시로 승인 해석) · V10-D2 A′ 승계 · V10-D3 W1+W3 우선 · V10-D4 예산 24.
루프 종료 후 신규: **V10-D5 champion 홀드아웃 소모 여부**(HOLDOUT-READY 도달 시).
