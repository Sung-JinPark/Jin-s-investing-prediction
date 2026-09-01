# [자동 학습·게이트 루프 설계서] V9 다변량 연구 트랙 — Claude Code 직접 예측·게이트 (2026-09-01)

> 배치: `docs/design/v9_gate_autoloop_260901.md`. 실행: Claude Code(저장소 접근) + git-bash 감독 루프.
> 계보: V8이 봉인 PASS·라이브 배포 완료(R8-D3) → 신규 DB 레이어(신용·유동성·AI빌드아웃·SEC파생)를
> **V8에 주입 금지**(봉인 정체성 파괴) → **V9 새 계약·새 봉인 절차**로만. 본 설계는 그 V9 게이트 루프.
> 지위: 참고 의견(CLAUDE.md). 게이트 기준·봉인 1회·retune 금지 전부 승계.

---

## 0. 이 루프가 하는 일과 하지 않는 일 (헌법)

**목표**: 새로 쌓인 DB 레이어를 피처로, V9 후보 모델을 **개발창(design)에서 반복 학습·평가**하여
게이트-정합 챔피언을 찾고, **봉인 평가 1회**로 게이트를 시도한다. Claude Code가 직접 예측 테스트를
돌리되, 아래 선을 넘으면 즉시 정지한다.

| 하지 않는다 (위반 시 BLOCKED) | 한다 |
|---|---|
| V8 봉인 계약·model_code_hash·원장 수정 | V9 신규 격리 패키지 `src/ai_fc/timeseries_v9/`에서만 작업 |
| 봉인 2019+ 평가를 자동 실행 | 개발창(design)·홀드아웃까지만 자동. 봉인은 **사용자 사인오프 후 별도** |
| 홀드아웃 finalist 자동 소모 | finalist당 1회, 최대 3 — 사용자/Code 명시 결정으로만 |
| 그리드 밖 파라미터·예산 초과 | 사전등록 그리드·예산(원장 행수) 내에서만, 코드가 이중 거부 |
| retune-after-failure | 봉인 실패 시 재학습 금지 — 새 데이터 축적 후 새 계약으로만 |
| 새 레이어를 V8에 주입 | V9 계약에만 피처로 등록 |
| forecasts/·calibration/·main 직접 커밋 | 로컬 브랜치 커밋(원장·outputs)만, push/PR은 사람 |
| FRED_API_KEY 등 시크릿을 루프에 로드 | 로컬 결정론 수치계산만 (데이터는 이미 수집됨) |

**정직한 기대치 (문헌 근거)**: 방향 예측은 거의 불가(M6 IR −3.4). V9 이득은 **분포·스케일 채널**
(신용 스트레스·유동성·변동성)에서만. 전 지평 양수 skill이 안 나오면 **HOLD가 정답**이고 그 HOLD를
기록하는 것까지가 성공.

---

## 1. 신규 DB 레이어 → V9 피처 (계약 등록 대상)

이전 설계(CREDIT-LIQ·V8R 팩)에서 준비된 소스가 이번 세션에 실제 수집·정제되었다는 전제. 각 피처는
**사전등록 + 단독 ablation + PIT(available_at ≤ origin) 강제**.

| 피처군 | 시리즈(예) | 채널 | 전제 |
|---|---|---|---|
| 신용/여신 | TOTCI·TOTLL(FRED 공식 API) | 기업 신용 사이클 | 이미 수집됨 |
| 예대율 | TOTLL÷Deposits(파생) | 은행 유동성 | 분자·분모 각 receipt |
| MMF 유동성 | MMMFFAQ027S(분기)·WRMFNS(주간) | 대기자금 | 주기 혼재 분리 필수 |
| 변동성/틸트 | VIXCLS·VXNCLS·VRP | 스케일 | FRED 기존 |
| AI 빌드아웃 | structures·회사채(GDP%) | 자본 사이클 | P2 검수 완료값 사용 |

**금지**: 판정 문구("과열/버블") 렌더, 확률공간 결합, 주간·분기 격자 혼합, 폐지 시리즈(WRMFSL).

---

## 2. 상태 기계 (git-bash 감독 루프)

```
BOOT → PRE-FLIGHT ─(실패)─→ HALT
  │(통과: V9 패키지 존재·계약 draft·역할해시·시크릿 sanitize)
  ▼
MODE-DETECT ─(홀드아웃 원장 PASS 행)─→ MODE-SHADOW (감시·누적)
  │(없음/미결/실패)
  ▼
MODE-EXPLORE (design 반복)
  next(그리드 조합)→ v9-dev-backtest(design,2000경로)→ 원장 append→ ablation→ 로컬 커밋
  │
  정지: 예산 소진 · 큐 소진 · 2연속 무개선 · ABORT · blocker 3회
  │
  ▼ (design 챔피언 확정, 게이트-정합 후보 존재 시)
HOLDOUT-READY → 정지 + 사용자 결정 대기 (홀드아웃 소모는 자동 금지)
  │(사용자 승인 후 Code 세션)
  ▼
HOLDOUT (finalist 1회) → PASS면 → SEALED-READY(정지, 사용자 사인오프 대기)
                        → FAIL이면 finalist 소모 기록 → EXPLORE 복귀(잔여 예산)
```

봉인(SEALED)은 **루프 밖**이다 — 사용자 사인오프 후 Code 세션에서만, 1회.

---

## 3. 게이트 기준 (V8 계약 승계, 변경 금지)

design 통과 proxy(R8-D1 계열): `design 장기평균 ≥ +2.5% AND paired se ≤ 0.001 AND
full-투영 CI90 상단 ≤ −0.0004 AND coverage 게이트 밴드`. 홀드아웃 통과: `장기평균 ≥ +2% AND
CI90 상단 ≤ 0`. **판정식·임계는 V9 계약에 복제하되 값은 G0에서 원문 확인** — 루프가 바꾸지 않는다.

자격 통계: 동일 좌표 쌍대차 + stationary block bootstrap(ℓ=2h, B=2000) + **지평별 MDE 사전 공표**
(검정력 부족과 효과 없음의 구분). 다중성: 후보 전부 사전등록, 사후 추가·실패 은폐 금지.

---

## 4. Claude Code 실행 프롬프트 (붙여넣기)

```
너는 V9 다변량 연구 트랙의 게이트 루프 실행자다. docs/design/v9_gate_autoloop_260901.md의
§0 헌법이 절대 규율이다. git fetch 후 저장소 최신 상태(main·V8 봉인 원장·신규 DB 레이어 수집분)를
재확인하고 G0부터 순서대로 진행하라. Phase 전환·홀드아웃 소모·봉인은 네가 판단하지 말고 정지·질문.

[G0 정찰] V8 봉인 계약에서 게이트 판정식·임계·coverage 밴드·holdout 규칙 원문 인용.
  V9 계약 draft를 이 값으로 생성(판정 변경 금지). 신규 DB 레이어 수집 상태·PIT 계약서 확인.
  src/ai_fc/timeseries_v9/ 격리 패키지 골격 + 역할분리(train/selection/holdout) 해시 고정.

[G1 피처] §1 피처를 V9 계약에 사전등록. 각 피처 available_at≤origin 강제 테스트 + 단독 ablation
  하네스. 상관 |ρ|>0.85 자동 기각. 주기 혼재(MMF 분기/주간) 분리 검증.

[G2 개발 반복] v9-dev-backtest를 design(2007–2014류 설계창, 2000경로)에서 그리드 조합마다 실행.
  E0 내포(퇴화 파라미터=E0 1e-12 일치) 필수. 원장 append-only, 예산=행수 상한. 매 실험 로컬 커밋.
  champion = design proxy 4조건 충족 후보. 없으면 정직하게 "충족 없음" 기록.

[G3 홀드아웃] champion 존재 시 정지·보고. 사용자 승인 후에만 finalist 1회 채점(2015–2018류).
  PASS면 SEALED-READY 정지(사인오프 대기). FAIL이면 finalist 소모 기록 후 잔여 예산으로 G2 복귀.

[G4 감시] 봉인 PASS·사이트 배선은 P1(#116/#122) 패턴 재사용: 신규 비봉인 display 모듈 +
  slot chain + fail-closed 검증기 + shadow 원장. 재학습 금지·display_only.

절대: V8 봉인 파일 0바이트·main 직접 커밋 금지·홀드아웃 자동 소모 금지·봉인 자동 실행 금지·
그리드 밖 금지·시크릿 미로드. 종료 상태는 HOLDOUT-READY/SEALED-READY/BLOCKED 중 하나.
매 Phase 종료 시 계약 자기점검(판정 불변·역할해시·예산·PIT 위반0·봉인 무접촉) 보고.
```

---

## 5. git-bash 감독 루프 (weekend_loop 계보 승계)

기존 `tools/weekend_loop.sh`(V8 주말 루프) 구조를 V9로 복제하되 다음만 교체:
- 하네스: `tools/ralph_timeseries_v9.py`(있으면) 또는 dev-backtest 직접 호출 + 원장 tail 판정.
- 명령 화이트리스트: `v9-dev-backtest`·`v9-verify`·hermetic만. **holdout·sealed verb 부재**.
- 모드 감지: `data/timeseries_v9/ledgers/holdout_scorings.jsonl` PASS 행 → SHADOW.
- 정지: ABORT 파일 · 예산 소진 · 2연속 무개선 · 기한(사용자 지정).
- 구동: `nohup bash tools/v9_gate_loop.sh >> outputs/timeseries_v9/loop/nohup.out 2>&1 &`
  (창 닫아도 지속, Windows 절전 해제 필수, 재개는 같은 명령 — state↔원장 대사).
- 드라이런 `DRY_RUN=1`, 스모크 `SMOKE=1 MAX_CYCLES=1`.

**핵심 안전**: 루프는 design 반복까지만 무인 수행. HOLDOUT-READY 도달 시 **정지하고 사람을 기다린다**
— 홀드아웃 표본과 봉인 1회는 무인 자동화가 건드릴 수 없는 경계다.

---

## 6. 검증 체크리스트 (Phase별 산출물 게이트)

- [ ] V8 봉인 파일 sha256 무변경 (해시 대사)
- [ ] V9 피처 전부 available_at ≤ origin (PIT 위반 0)
- [ ] E0 내포 테스트 통과 (퇴화=E0 1e-12)
- [ ] 예산 = 원장 행수 ≤ 상한, 그리드 밖 조합 0
- [ ] design proxy 판정식이 V8 원문과 일치 (변경 0)
- [ ] 홀드아웃 소모 = 사용자 승인 로그 존재 시에만
- [ ] main 직접 커밋 0, forecasts/·calibration/ 무접촉
- [ ] MDE 지평별 공표, 다중성 사전등록 준수
- [ ] inventory 재생성 (`cd src && python -m ai_fc inventory`)

---

## 7. 사용자 결정 대기

| # | 항목 | 선택지 |
|---|---|---|
| V9-D1 | V9 트랙 개시 승인 | (a) 신규 DB 레이어로 V9 착수 (b) 레이어만 쌓고 대기 |
| V9-D2 | 설계창/홀드아웃 구간 | V8과 동일(2007–2014/2015–2018) vs 재정의 |
| V9-D3 | 피처 1차 셋 | §1 전체 vs 신용·유동성만 우선 |
| V9-D4 | 홀드아웃 소모 | champion 확정 후: 즉시 채점 vs shadow 누적 후 |

*문서 끝. V9-D1 승인 후 G0 착수. 봉인·홀드아웃은 무인 자동화 밖.*
