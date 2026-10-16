# NASDAQ 다변량 시계열(MTS) 프로그램 — P0~P4 종결 검토팩

**제출 2026-09-09 (KST) · 대상: 외부 검토관(프론티어 LLM 또는 통계 전문가) · 팩 진입점**

> **가장 먼저 읽을 것 — `00_ERRATA_AND_REFUTATIONS.md`**
>
> 이 팩의 다섯 축 문서는 각각 독립된 **적대적 검증**을 거쳤고, 그 결과 **16건이 반증**됐다.
> 우리는 원문을 조용히 고치는 대신 반증과 정정을 한 문서에 모아 두었다. A군 8건은 검토관의
> 판정을 바꿀 수 있으므로 **원문보다 정오표가 정본**이다. 특히 "봉인 바이트를 읽지 않았다"와
> "PAV 적합이 없었다"는 두 주장은 실제로는 더 좁은 사실이었다(A1·A2).
>
> 팩 자체의 결손은 `00_PACK_CRITIQUE.md` 에 17건(S1 3 · S2 5 · S3 5 · S4 4)으로 정리돼 있다.
>
> **2026-09-10 2·3차 라운드가 더해졌다.** 사용자가 원점별 자료 공개를 승인해 진단 5종이
> `E_artifacts/diagnostics/` 에 추가됐고, 그 검증 과정에서 **운영 불일치 하나**가 드러났다 —
> 홀드아웃 채점과 라이브 전진 채점이 **서로 다른 기후 기준선**을 쓴다(RV 3셀, 최대 0.0052).
> 정오표 3차 절과 `E_artifacts/diagnostics/scoring_path_baseline_divergence.json` 을 보라.
> 아직 채점된 행이 0이라 지금 결정하면 비용이 없다.
>
> 새 질문 **Q13·Q14** 와 개정 **Q3′·Q7′** 는 `00_REVIEW_REQUEST_ADDENDUM.md` 에 있다.
> 문서별 번호 충돌은 `QUESTION_INDEX.md` 가 푼다. 검증 절차는 `VERIFY.md`.

---

## 1. 이 팩은 무엇인가

이 팩은 NASDAQ 다변량 시계열(MTS) 프로그램의 **V13-VOL 트랙**(변동성 사건 확률 9셀)이 단계 P0부터 P4까지를 끝내고 **P5(외부 유료 정보집합) 앞에서 멈춘 상태**를 2026-09-09(KST) 기준으로 봉인해 제출한 것이다. 검토관이 저장소에 접근하지 않는다는 전제로 계약 원문·원장(append-only)·산출물 JSON·판정서 9종·판정 코드·테스트·거버넌스 원문을 전부 동봉했고, 팩 사본이 저장소 원본과 sha256 동일함을 계약·원장 등 6개 파일에서 확인해 두었다(`D_governance/00_GOVERNANCE_DIGEST.md` 부록 C, `01_STATE/STATE_OF_THE_PROGRAM.md` §0.1).

요청하는 것은 **판정의 재계산이나 번복이 아니라 세 가지 판단**이다 — ① 판정 기계가 건전한가(특히 홀드아웃 9셀 중 3셀 통과를 "통과"로 읽어도 되는가), ② 남은 **비가역 자원**(홀드아웃 슬롯 2개·개발 평가 예산 4회)을 어디에 쓸 것인가, ③ 이 트랙을 부정 결과로 종결할 조건은 무엇인가. 팩 안의 문서들은 결론을 옹호하지 않고 **자기 약점을 먼저 적어 두는 방식**으로 쓰였으므로(`B_verdicts/00_VERDICT_DIGEST.md` §8 W1~W12, 각 문서의 `[미확인]` 대장), 검토관은 그 목록을 공격 지점의 출발선으로 삼으면 된다.

> **읽기 전 경고 하나**: 통치 문서인 설계도(`C_design/mts_program_blueprint_v1_260909.md`)의 **§2 "현 위치" 수치는 낡았다.** 같은 날 오후에 홀드아웃 소모와 rung-4가 실행됐다. 정오표는 `C_design/00_BLUEPRINT_ERRATA.md`, 진실은 `01_STATE/FACTS.json`(기계 파생)이다.

---

## 2. 30초 요약

| 항목 | 실측값 | 출처(팩 내 경로) |
|---|---|---|
| 표적 | 9셀 = P(VIX 종가 ≥ K 를 h영업일 내 터치), K∈{25,30} · P(RV21_ann > θ=0.1694 를 h영업일 내 초과), h∈{5,21,63} | `A_contracts/multivariate_timeseries_v13_vol.yaml` L19-28 |
| 창 | 설계창 2007-01-01~2014-12-31(n=2014, 분할 2011-01-01) · 홀드아웃 2015-01-01~2018-12-31 · 봉인 2019+ | 계약 L35, L95, L118-121 |
| champion | **전 9셀 `persistence_pb`**(당일 수준 단독 로짓), finalist `V13VOL_champion_aec80c65038b` | `01_STATE/FACTS.json` `contract.champion` |
| 설계창 사다리 전적 | rung-1 EWMA vs 기후 **9/9 채택** → rung-2 HAR 증분 **0/9** → rung-3 EWMA vs PB **0/9** → rung-4 매크로 3블록 **0/27** (family P(k≥0\|n=27)=0.99999…) | `E_artifacts/vol/ladder_*.json` 4종, `E_artifacts/ledgers/vol_experiments.jsonl` 4행 |
| 홀드아웃 | **1/3 슬롯 소모(비가역) · partial — 9셀 중 3셀 통과**(`vix25_h21`·`rv_h5`·`rv_h21`), family P(k≥3\|n=9,p=0.05)=**0.008361039546874999** | `E_artifacts/ledgers/holdout_scorings.jsonl` 1행, `E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json` |
| 실패 6셀의 모양 | 4셀은 **기후는 이겼는데 건전 귀무(G4)에서 무너졌다**(`vix30_h5` 귀무 통과율 1.000) · 2셀은 G1(기후 대비) 실패 | `B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §0-§1 |
| 완성 정의 C0~C4 | **C2만 완전 충족** · C0·C4 부분 · C1·C3 미충족 | `01_STATE/STATE_OF_THE_PROGRAM.md` §2 |
| 자원 잔량 | 개발 평가 **4/8 소모(잔여 4)** · 홀드아웃 슬롯 **1/3 소모(잔여 2)** · 라이브 고유 원점 **2** · 성숙 채점 **0/60** | 계약 L77-78·L85·L343, `E_artifacts/ledgers/vol_live.jsonl`(3행/고유 as_of 2) |
| 현 단계 | **P5 — 외부 정보집합(옵션·일중)**. 차단 요인: 라이선스 확정 표에 CBOE 행 없음(회신·적재 전, 편지 **미발송**) | `01_STATE/roadmap_status.txt` L15·L18, `D_governance/CBOE_DATASHOP_QQQ_SEND_20260909.md` L3 |
| P3(배선) | **실패가 아니라 사용자 보류** — 영수증 `v13-approval:V13-D6-defer:2026-09-09:r1`(13:03:32 KST), 재개 조건 셀당 성숙 원점 60. 배선 자격 셀 2개(`rv_h5`·`rv_h21`)에 대응하는 등록 질문이 없다 | `E_artifacts/ledgers/approvals.jsonl` 9행, 계약 L335 |
| 화면 표시 | `t3_live_card`, 홀드아웃 실패 6셀은 숫자를 내려 **9칸 중 3칸만 숫자**. 매매 신호 아님·참고 의견 상시 | 계약 L328·L331-335, `E_artifacts/vol/vol_latest.json` |

**한 문장**: 변동성 사건 확률은 당일 변동성 수준이 거의 전부 말하고, 그 위에 얹은 세 확장(평활·다중스케일·매크로)은 63개 검정에서 하나도 증분을 주지 않았으며, 그 자명한 모형조차 진짜 표본외에서는 9셀 중 3셀에서만 살아남았다(`B_verdicts/00_VERDICT_DIGEST.md` §1).

---

## 3. 읽는 순서 — 세 가지 코스

### 3.1 30분 코스 — "무슨 일이 있었고 무엇을 묻는가"

| # | 파일 | 왜 이 순서인가 |
|---|---|---|
| 1 | `01_STATE/roadmap_status.txt` (26행) | 산문을 읽기 전에 **도구가 원장에서 파생한 상태 한 장**을 먼저 본다. 첫 줄에 읽은 체크아웃·커밋이 찍혀 있다 |
| 2 | `C_design/00_BLUEPRINT_ERRATA.md` (39행) | 설계도 §2를 최신으로 읽는 오독을 **미리 차단**한다. 2분이면 끝난다 |
| 3 | `01_STATE/STATE_OF_THE_PROGRAM.md` §0.2~§2 | 단계표 P0~P7과 완성 정의 C0~C4 판정이 **각각 근거 파일·필드와 함께** 있다 |
| 4 | `B_verdicts/00_VERDICT_DIGEST.md` §1(논증 사슬)·§3.2(핵심 표) | 사다리→가드→홀드아웃 사슬 전체가 한 화면에 들어온다. §3.2는 "기후는 이겼는데 귀무에서 무너진 4셀"의 기전 |
| 5 | `B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` (전문) | **비가역 자원을 실제로 쓴 유일한 판정**. 이 팩의 무게중심 |
| 6 | `H_prior_packs/00_STRATEGY_OPTIONS.md` §0·§5 | 지금 묻고 있는 **결정**이 무엇인지(Q1~Q5, A/B 선택형) |
| 7 | `00_REVIEW_REQUEST.md` | 판정 요청서 — §7 참조 |

### 3.2 2시간 코스 — 통계 검증까지

30분 코스에 이어서.

| # | 파일 | 왜 이 순서인가 |
|---|---|---|
| 8 | `01_STATE/FACTS.json` | **기계 파생 수치 정본**. 이후 읽을 산문의 수치를 이것과 대사하라. 다르면 이것이 옳다 |
| 9 | `E_artifacts/ledgers/holdout_scorings.jsonl`(1행) + `E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json` | 9셀 원자료. 판정서 표를 **읽지 말고 직접 세라** |
| 10 | `F_code/00_JUDGMENT_MACHINERY.md` §7.4 (검산 스크립트) | 여기서 **팩만으로 family P와 셀별 게이트 정합을 재현**한다. 저장소 없이 닫히는 유일한 산술 |
| 11 | `B_verdicts/00_VERDICT_DIGEST.md` 전문 — 특히 §4(가드)·§7(파생 진단 Δ1~Δ3)·§8(W1~W12) | Δ1은 G1 기준선이 홀드아웃 창 기후가 아님을, §8은 우리가 아는 약점 12개를 선제 공시한다 |
| 12 | `B_verdicts/V13_GUARD_MDE_20260909.md` + `E_artifacts/vol/guard_mde_design.json` | **국면(에피소드) 가드**가 이 트랙의 핵심 장치다. 사건 수 9/9 통과 ↔ 국면 수 3/9 통과의 대비 |
| 13 | `F_code/00_JUDGMENT_MACHINERY.md` §1~§2 | 판정 기계 8종의 수식·줄번호, **건전 귀무(y-block)와 p-순열 금지**의 실증 근거(T-A 사건) |
| 14 | `A_contracts/multivariate_timeseries_v13_vol.yaml` — `gate`(L53-69) · `prohibitions`(L124-)· `stopping_points`(L93-123) · `degeneracy_guard`(L220-286) | 사전등록된 **형(form)** 을 원문으로 확인. 임계가 아니라 CI 형태로 고정돼 있다 |
| 15 | `B_verdicts/V13_VOL_RUNG1~RUNG4` 판정서 4종 + `E_artifacts/vol/ladder_*.json` | 사다리 각 단의 원자료. 판정서 산문과 JSON이 어긋나는 곳은 §6.2에 이미 적혀 있다 |
| 16 | `H_prior_packs/00_STRATEGY_OPTIONS.md` 전문 | §1.3(“채택 0/27”이 정확히 뜻하는 것)·§2(남은 경로 7종)·§4(종결 트리거 T1~T6) |

### 3.3 하루 코스 — 코드 재현까지

2시간 코스에 이어서. **여기서부터는 저장소가 필요하다**(§6.2).

| # | 파일·작업 | 왜 이 순서인가 |
|---|---|---|
| 17 | `F_code/00_JUDGMENT_MACHINERY.md` 전문 | §3 홀드아웃 verb의 가드 순서(승인→예산→**데이터 읽기 전 거부**), §4 band80 좌표 불일치 버그와 수정, §5 발행·빌드 이중 페일클로즈, §8 열린 문제 12항 |
| 18 | `F_code/timeseries_v13/*.py`(8) + `F_code/tools/*.py`(8) + `F_code/timeseries_v13_vol_display.py` | 판정·동결·발행·표시 경로 전 코드. **적합 함수가 홀드아웃 모듈에 없다**는 사실을 직접 확인하라(§3.2) |
| 19 | `F_code/tests/*.py`(12) | 무엇이 **바이트로 고정**되는가 — `FROZEN_GATE`·`FROZEN_TARGETS` 상수가 계약 원문을 잠근다 |
| 20 | `D_governance/00_GOVERNANCE_DIGEST.md` 전문 + `E_artifacts/ledgers/approvals.jsonl` 9행 원문 | 승인이 집행에 선행했는가. **시각 정정(r2) 사건**과 미정정 잔여 의문까지 그대로 실려 있다 |
| 21 | `C_design/mts_program_blueprint_v1_260909.md` | 통치 문서 — 완성 정의 C0~C4(§1.2), 단계·종료 조건(§3·§9.3), 판정 기계 표준(§5), 표시 사다리(§7), 부정 결과 프로토콜(§10). **§2만 낡았다** |
| 22 | `G_session_20260909/*.diff` | 이 팩을 만든 날 저장소에 무엇이 들어갔는가(표시 정직성 수정 1건 + 매니페스트 기준선 갱신 1건) |
| 23 | 저장소 내려받아 §6.2 명령 실행 | pytest 11파일 · 결정론 러너 재실행 · **홀드아웃 verb가 거부되는지 확인** |
| 24 | `H_prior_packs/NASDAQ_MULTIVARIATE_ROADMAP_DESIGN_REVIEW_20260908.zip`(78파일) | 선행 팩 — V1~V13 계약 전체와 V9·V10·V11 동결 판정. **V13이 왜 다른가**를 맥락에서 판단할 때만 열면 된다 |

---

## 4. 디렉터리 지도

팩 루트 = `outputs/review-packs/NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909/`. 총 **87 파일**(README·MANIFEST 포함) · 최상위 디렉터리 **9개**(하위 디렉터리 포함 총 16개). 정확한 목록과 해시는 `MANIFEST.sha256` 에 있다 — 팩 루트에서 `sha256sum -c MANIFEST.sha256` 로 전수 검증된다.

| 디렉터리 | 파일 | 무엇이고 왜 넣었는가 |
|---|---|---|
| **`01_STATE/`** | `FACTS.json` · `STATE_OF_THE_PROGRAM.md` · `PREREG_CHAIN.md` · `roadmap_status.txt` · `git_log_main_recent.txt` | **현 위치 실측.** `FACTS.json`은 계약·원장·산출 JSON에서 기계적으로 파생한 수치 정본(산문과 다르면 이것이 옳다). `STATE_OF_THE_PROGRAM.md`(225행)는 단계표·C0~C4 판정·자원 잔량·9셀 현황 3종·오독 함정 7건·[미확인] 9건. `PREREG_CHAIN.md`는 원장 4행 ↔ 커밋 대조(감사 필드가 **rung-3부터** 기록되기 시작한 비대칭을 공시). `roadmap_status.txt`는 도구 출력 원문 |
| **`A_contracts/`** | `multivariate_timeseries_v13_vol.yaml`(416행) · `multivariate_timeseries_v8.yaml` · `multivariate_timeseries_v2.yaml` · `ledger_registry.yaml` | **사전등록 원문.** V13 계약이 정본 — 표적·게이트 형·금지 11종·정지 지점·국면 가드·표시·개정 이력이 한 파일에 있다. V8·V2는 봉인·섀도 규율의 출처(V13이 참조하는 read-only 아카이브). `ledger_registry.yaml`은 어느 파일이 `immutable_files`로 CI에 잠겨 있는지 |
| **`B_verdicts/`** | `00_VERDICT_DIGEST.md`(540행) + 판정서 9종: `V13_VOL_RUNG1`·`RUNG2`·`RUNG3_PB`·`RUNG4_MACRO`·`V13_GUARD_MDE`·`V13_HOLDOUT`·`V13_TA_NULL_REPAIR`·`V8_SHADOW_ORIGIN_STALL`·`V9_V10_V11_INDEPENDENT` | **판정 본문.** 다이제스트는 판정서 9종을 원자료와 전수 대조한 결과(일치 항목·불일치 8건·파생 진단 3종·검토관 공격 지점 W1~W12). `V13_TA_NULL_REPAIR`는 p-순열 귀무가 왜 금지됐는지의 실증, `V9_V10_V11_INDEPENDENT`는 선행 세 트랙 부정 결과의 독립 재분석 |
| **`C_design/`** | `00_BLUEPRINT_ERRATA.md` · `mts_program_blueprint_v1_260909.md`(1136행) · `v13_next_design_prereg_260907.md` · `v13_vol_live_card_display_design_260908.md` · `v13_cboe_datashop_qqq_request_260907.md` · `v13_firstrate_acquisition_plan_260907.md` | **통치 문서와 그 정오표.** 설계도가 완성 정의·단계·판정 기준·데이터 등급·표시 사다리를 정한다. CBOE·FirstRate 문서는 P5에서 사려는 것이 정확히 무엇인지(그리고 라이선스 상태) |
| **`D_governance/`** | `00_GOVERNANCE_DIGEST.md`(451행) · `CLAUDE.md` · `DECISIONS.md`(1108행) · `KNOWN_LIMITS.md` · `MODEL_REGISTRY.md` · `ARCHITECTURE.md` · `CBOE_DATASHOP_QQQ_SEND_20260909.md` | **규율이 실제로 지켜졌는가.** 다이제스트가 규율 7종의 명문화/집행/증거를 3열로 대조하고, 승인 원장 9행을 원문 대조하며, **시각 정정 사건과 미정정 잔여 의문을 숨기지 않는다**. `CLAUDE.md`는 프로젝트 헌법(ML 게이트·P3 게이트·불변성 규칙), `DECISIONS.md`는 결정 원문 |
| **`E_artifacts/`** | `ledgers/`(4): `approvals.jsonl`(9행) · `holdout_scorings.jsonl`(1행) · `vol_experiments.jsonl`(4행) · `vol_live.jsonl`(3행) <br> `vol/`(7): `champion_coefficients.json` · `guard_mde_design.json` · `ladder_ewma_logit`·`ladder_har_logit`·`ladder_pb_baseline`·`ladder_rung4_macro`·`vol_latest.json` <br> `runs/`(1): `holdout_V13VOL_champion_aec80c65038b.json` <br> `prereg/`(3): `ta_null_repair*.json` · `p1_h3_prediagnosis.json` | **원자료.** 모든 수치 주장의 최종 출처. 원장은 append-only(수정 불가), `ladder_*.json`·`champion_coefficients.json`은 `immutable_files`로 등록돼 바이트 변경이 CI violation이 된다. 판정서·다이제스트를 믿지 말고 여기서 세라 |
| **`F_code/`** | `00_JUDGMENT_MACHINERY.md`(953행) · `timeseries_v13/`(8 모듈) · `tools/`(8 러너) · `tests/`(12) · `timeseries_v13_vol_display.py` | **판정 기계 자체.** 부트스트랩 CI·건전 귀무·Murphy 분해·family 이항·국면 런 계산·델타법 대역이 어느 함수 몇 번째 줄에서 나오는지, 홀드아웃 verb가 어떤 순서로 거부하는지, 표시가 어디서 페일클로즈하는지. 테스트 12종은 계약 원문을 상수로 잠근다 |
| **`G_session_20260909/`** | `fixes.diff`(30KB) · `rung4_manifest_baseline.diff` | **팩 제작 당일 저장소 변경 전량.** 표시 정직성 수정(홀드아웃에서 떨어진 셀을 문장이 계속 가리키던 것)과 immutable 파일 기준선 갱신 1건. 후자는 "결과 후 파일이 한 번 재작성됐다"는 사실의 공시다 |

> **선행 팩 zip 주의**: `H_prior_packs/NASDAQ_MULTIVARIATE_ROADMAP_DESIGN_REVIEW_20260908.zip` 은
> **2026-09-08 판**이다. 그 안의 V13 계약·원장은 홀드아웃 소모(09-09) 이전 상태이므로, 수치가
> 이 팩과 다르면 **이 팩이 최신**이다. 선행 팩은 V1~V12 맥락 참조용으로만 열어라.

| **`H_prior_packs/`** | `00_STRATEGY_OPTIONS.md`(534행) · `NASDAQ_MULTIVARIATE_ROADMAP_DESIGN_REVIEW_20260908.zip`(78파일) | **다음 결정.** 전략 문서가 무료 경로 소진의 정확한 의미, 남은 경로 7종 비교(비용·라이선스·PIT·성공확률), 종결 트리거 T1~T6, 검토관 질문 Q1~Q5를 담는다. zip은 하루 전 선행 검토팩(V1~V13 계약 전체·선행 트랙 판정서) |

### 4.1 알려진 인용 좌표 오기 (이 README가 실측한 정오)

판정 내용에는 영향이 없으나, **줄번호를 축자 대조하는 검토관이 막힌다**. 2026-09-09 기준 실측이다.

| 문서 | 잘못된 인용 | 실제 |
|---|---|---|
| `01_STATE/STATE_OF_THE_PROGRAM.md` §0.2 | `roadmap_status.txt` **L19** (P5 차단 근거) | **L18** (L19는 P6 행 "성숙 원점 최소 0/60") |
| `H_prior_packs/00_STRATEGY_OPTIONS.md` §1.1 | 계약 **L281** `series_added_for_this_rung` | **L259** (L281은 `backtest_windows_opened: 0`) |
| 〃 §2.5 | 계약 **L27** RV 산식 | **L26** (L27은 `theta: 0.1694`) |
| 〃 §2.6 | 계약 **L242** `episode_failures` | **L245** |
| 〃 §2.7 | 계약 **L44** `climatology_base_rates` | **L40-42** |
| 〃 §4.4 | 계약 **L285-296** 보수 지연 10·42세션 | **L270**·**L274** |

설계도 §2의 상태 값이 낡은 건은 별도 문서로 공시돼 있다 — `C_design/00_BLUEPRINT_ERRATA.md`.

---

## 5. 용어 사전

이 저장소 고유 용어이거나 통상 용법과 다른 것만 적는다.

| 용어 | 뜻 |
|---|---|
| **설계창(design window)** | 2007-01-01~2014-12-31. 모형 개발·사다리 검정에 **반복 사용이 허용된** 창. 분할 2011-01-01로 early/late 반창을 나눠 양방향 전이를 요구한다(계약 L35·L55) |
| **홀드아웃(holdout)** | 2015-01-01~2018-12-31. **finalist당 1회, 총 3슬롯**의 비가역 자원. 사용자 원문 승인 + 영수증 없이는 데이터를 읽기 전에 거부된다. 1슬롯을 2026-09-09에 썼다(계약 L94-117) |
| **봉인(sealed)** | 2019-01-01~현재. V13에서는 **실행 경로 자체가 존재하지 않는다**(`execution_path: absent_by_construction`, 계약 L118-121). 홀드아웃 패널도 `observation_time <= 2018-12-31`로 절단된다 |
| **rung(사다리 단)** | 모형 사다리의 한 칸. 각 rung은 아래 칸을 특수형으로 포함한다(기후 = EWMA의 λ→0 = HAR의 계수 0). rung 하나가 **개발 평가 예산 1회**를 소모한다. rung-1 EWMA / rung-2 HAR / rung-3 PB 기준선 / rung-4 매크로 3블록 |
| **기후(climatology)** | 학습창의 **무조건 이벤트 빈도**(walk-forward). 참조 귀무이지 스킬이 아니다. 설계창이 GFC를 포함해 기저율이 높다(계약 L40-43). 홀드아웃 G1도 이 **설계창 고정 상수**를 기준선으로 쓴다 — 이것이 가장 큰 공격 지점이다(`B_verdicts/00_VERDICT_DIGEST.md` §8 W2, §7 Δ1) |
| **PB (persistence_pb)** | "당일 수준 단독 로짓" — 오늘의 VIX 종가(또는 RV21) 하나만 넣은 로지스틱. **자명 기준선**으로 도입했는데 EWMA도 HAR도 매크로도 이것을 못 이겨서, 결국 champion이 됐다 |
| **건전 귀무(negative control)** | **사건 라벨 y를 블록 순열(ℓ=13)** 해 스킬 통과율을 재는 귀무. 통과율 ≤ 0.10을 요구한다(계약 L65-68). 대비되는 **p-순열**(예측 확률을 섞는 방식)은 누수가 실증돼 계약 `prohibitions`로 **금지**됐다 — 근거는 `B_verdicts/V13_TA_NULL_REPAIR_VERDICT_20260907.md` |
| **국면(에피소드, episode)** | 라벨의 **연속 구간(run) 수**. 라벨을 h영업일 전방창으로 만들면 이웃 원점이 강하게 겹쳐 사건 '개수'가 유효 표본을 과대평가하므로, 독립 국면 수를 진짜 자유도로 본다. 임계는 반창×클래스당 5. 설계창에서 사건 수 가드는 9/9 통과했는데 **국면 가드는 3/9만 통과했다**(계약 L220-250) |
| **`episode_thin`** | 국면 수 미달 라벨. 채점은 하되 라이브 카드에 "국면 표본 얇음" 마커가 붙고, **홀드아웃 PASS여도 배선 자격이 없다**(계약 L241-242) |
| **페일클로즈(fail-closed)** | 확인되지 않으면 **숫자를 내리는** 기본값. 표시 tier의 착지점이 `t0_internal`(미표시)이고, 홀드아웃 실패 셀은 payload에서 아예 제거된다. 숫자만 내리는 것으로 부족해 **문장도 함께 바뀐다**(`G_session_20260909/fixes.diff`) |
| **tier T0~T4** | 표시 사다리. `t0_internal`(숫자 미표시, 페일클로즈 착지점) / **T1은 값 자체가 없다** / `t2_hidden_panel`(`?review=` 숨김 패널) / `t3_live_card`(라이브 카드 — **현재 위치**) / **T4(실전 자금 결정 근거)는 계약 `display_tiers_allowed`에 값이 없어 구조적으로 차단**(계약 L329) |
| **C0~C4 (완성 정의)** | 프로그램 완성 = C0∧C1∧C2∧C3∧C4, 표시 상한 T3. **C0** 판정 기계 건전성(건전 귀무 통과율 ≤0.10 · 국면 가드 · 결과 전 MDE 공표 — 상시 조건) / **C1** 라이브 전진 표본(V13 셀당 성숙 원점 ≥60, V8 섀도 세션 ≥126) / **C2** 홀드아웃 소모·판정(**결과 무관 완결 — FAIL도 충족**) / **C3** 배선(PASS 셀 확률을 EXIT 질문 base rate 공간에 **표시만** 연결) / **C4** 표시 정직성 |
| **C5 / P3 게이트** | LLM 캘리브레이션 원장의 해소 50문항+ & Brier < 0.18. **이 프로그램 외부 조건**이다 — 수치 모델이 아무리 좋아져도 C5를 진전시키지 못한다. "완성했는데 T4가 안 열린다"는 실패가 아니라 설계대로다(설계도 §1.3) |
| **배선(wiring)** | 홀드아웃 PASS 셀의 확률을 EXIT 트리거 질문의 base rate 공간에 연결하는 것. **표시만이고 산술 결합 0·자동 재예측 0**. 결정 id `V13-D6` |
| **G1~G4** | 홀드아웃 게이트. **G1** 기후 대비 쌍대 Brier CI90 하한 > 0 / **G2** PB 대비 유의 열위 아님(champion=PB인 셀은 **항등 통과**) / **G3** Murphy 신뢰도 **보고 의무**(판정 다리 아님) / **G4** 건전 귀무 통과율 ≤ 0.10. 셀 PASS = G1∧G2∧G4 (계약 L106-111) |
| **family P** | 다중비교 병기값. 이항 `P(k ≥ k_obs | n, p=0.05)`. 홀드아웃 = P(k≥3\|n=9) = 0.008361, rung-4 = P(k≥0\|n=27) = 0.99999… |
| **MDE** | 최소 검출 가능 효과 = 1.645 × bootstrap_se. `|Δ| < MDE`는 "결정적 증거 없음". **결과를 보기 전에 공표**하는 것이 C0의 셋째 항 |
| **band80** | 라이브 카드의 80% 대역. **델타법 계수 불확실성이지 보정(calibration) 구간이 아니다**(계약 L308-311). 좌표계 버그가 있었고 고정 표준화로 수정됐다(`F_code/00_JUDGMENT_MACHINERY.md` §4) |
| **BSS** | Brier Skill Score, 기준선 대비 상대 개선. 이 팩에서 기준선은 대부분 **설계창 고정 기후**다 — 홀드아웃 자체 기저율 대비로 다시 계산하면 9셀 중 4셀이 음수다(다이제스트 §7 Δ2) |
| **`measured_zero`** | rung-4 결과 산출물의 셀별 verdict 라벨. 27/27이 이 값이다. 다만 설계도 §10.1의 엄격 정의(증분이 MDE 미만)에 해당하는 것은 일부이고 나머지는 **유의 악화**라는 지적이 있다(`H_prior_packs/00_STRATEGY_OPTIONS.md` §1.3, Q5) |
| **PIT** | Point-In-Time. 관측을 `available_at <= origin`으로만 쓰는 규율. 데이터 원천마다 등급이 다르고(`archive_verified` > `reconstructed_market_archive`), rung-4의 F2·F3 블록은 **PIT 증거 없이 보수적 지연을 가정한 블록**임이 caveat로 붙어 있다 |
| **영수증(approval receipt)** | `approvals.jsonl`의 1행. 사용자 승인 **원문 문자열**·시각·범위·`git_head_at_approval`을 담는다. 비가역 자원은 영수증 id 없이는 코드가 데이터를 읽기 전에 거부한다 |

---

## 6. 재현 명령

### 6.1 팩만으로 (저장소 없이 닫히는 것)

```bash
cd <PACK>

# (1) 홀드아웃 판정의 산술 정합 + family P 재현  — F_code/00_JUDGMENT_MACHINERY.md §7.4
python - <<'PY'
import json, math
d = json.load(open("E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json", encoding="utf-8"))
scored = {k: v for k, v in d["cells"].items() if v["verdict"] != "untestable_by_construction"}
for name, c in scored.items():
    g1 = c["G1_vs_climatology"]["ci90"][0] > 0
    g2 = c["G2_not_inferior_to_pb"]["upper_ge_zero"]
    g4 = c["G4_negative_control_pass_rate"] <= 0.10
    assert (g1 and g2 and g4) == c["verdict"].startswith("pass"), name
    assert c["G1_pass"] == g1 and c["G2_pass"] == g2 and c["G4_pass"] == g4, name
k, n = len(d["pass_cells"]), len(scored)
fam = sum(math.comb(n, i) * 0.05**i * 0.95**(n - i) for i in range(k, n + 1))
print(k, n, fam, d["family_p_binomial"])   # 3 9 0.008361039546874999 (일치해야 한다)
PY

# (2) sha256 사슬 — 산출물 파일 해시가 원장 핀과 같은가
sha256sum E_artifacts/vol/ladder_rung4_macro.json E_artifacts/vol/ladder_pb_baseline.json \
          E_artifacts/vol/champion_coefficients.json
#  49edaaeb3a0115e8…  = vol_experiments.jsonl 4행 results_sha256
#  71c92648af96fa8d…  = vol_experiments.jsonl 3행 results_sha256
#  1a85785056738775…  = holdout_scorings.jsonl coefficients_sha256

# (3) 봉인창 절단의 산술 — 원점 수 차이가 지평 차이와 일치하는가
python -c "import json;d=json.loads(open('E_artifacts/ledgers/holdout_scorings.jsonl',encoding='utf-8').readline());print({k:(v['origins'],v['first_origin'],v['last_origin']) for k,v in d['cells'].items()})"
#  h5 1001 / h21 985 / h63 943  →  1001-985=16=21-5, 985-943=42=63-21
#  주의: 이는 라벨 완결 절단과 모순이 없다는 뜻이지, '봉인 바이트 미열람'의 증명은 아니다
#       (D_governance/00_GOVERNANCE_DIGEST.md §1.1 및 그 정정 참조)

# (4) 승인이 집행에 선행했는가 — 9행 원문과 supersedes 대소
cat E_artifacts/ledgers/approvals.jsonl

# (5) 결과 전 MDE 공표 순서 (C0 ③)
#  guard_mde_design.json  generated_at 2026-09-09T02:06:01Z
#   <  approvals 8행 approved_at 11:35:57 KST (= 02:35:57Z)
#   <  holdout_scorings knowledge_cutoff 2026-09-09T02:37:57Z

# (6) 계약 원문 게이트(L53-69)와 테스트 상수의 눈 대조
sed -n '53,69p' A_contracts/multivariate_timeseries_v13_vol.yaml
grep -n "FROZEN_GATE\|FROZEN_TARGETS" -A 20 F_code/tests/test_timeseries_v13_vol_contract.py
```

**팩만으로는 불가능한 것**: 부트스트랩 CI와 귀무 통과율의 **재계산**. 시장 패널이 필요하다.

### 6.2 저장소를 받았을 때

경로 대응: `F_code/tools/*` → `tools/*` · `F_code/timeseries_v13/*` → `src/ai_fc/timeseries_v13/*` · `F_code/timeseries_v13_vol_display.py` → `src/ai_fc/timeseries_v13_vol_display.py` · `F_code/tests/*` → `src/tests/*`.

```bash
# 테스트 — pytest 는 반드시 src/ 에서 실행
cd src && python -m pytest \
  tests/test_timeseries_v13_scoring.py tests/test_timeseries_v13_vol.py \
  tests/test_timeseries_v13_holdout.py tests/test_timeseries_v13_pipeline.py \
  tests/test_timeseries_v13_resolve.py tests/test_timeseries_v13_vol_display.py \
  tests/test_timeseries_v13_vol_contract.py tests/test_timeseries_v13_vol_panel.py \
  tests/test_timeseries_v13_vol_role_honesty.py tests/test_v13_vol_rung4_macro.py \
  tests/test_roadmap_status.py -q
#  role_honesty 는 node 필요 — 없으면 skip

# 재실행 가능한 결정론 러너 (seed 20260907 — 같은 수가 나와야 한다)
PYTHONUTF8=1 python tools/v13_vol_run.py            # rung-1
PYTHONUTF8=1 python tools/v13_vol_rung2.py          # rung-2
PYTHONUTF8=1 python tools/v13_guard_mde.py          # P0 가드 + 셀별 MDE
PYTHONUTF8=1 python tools/v13_ta_null_repair.py --count 1000
PYTHONUTF8=1 python tools/roadmap_status.py         # 읽기 전용 상태

# 재실행이 '거부되는 것'이 정상인 것 — 거부 자체를 확인하라
PYTHONUTF8=1 python tools/v13_vol_rung3_pb.py       # exit 2 (원장에 같은 label 존재)
PYTHONUTF8=1 python tools/v13_vol_rung4_macro.py    # exit 2
cd src && python -m ai_fc timeseries-v13-vol-holdout --approval-receipt v13-approval:V13-D3:2026-09-09:r1
#  → already consumed 로 거부. 영수증을 빼거나 가짜 id 를 주면 데이터를 읽기 전에 거부된다

# 사전등록이 결과보다 앞섰는가 (D_governance/00_GOVERNANCE_DIGEST.md 부록 A)
git show -s --format='%H %ad %s' --date=iso-strict 0ce8569b afec214e
git merge-base --is-ancestor 0ce8569b e576223c && echo "prereg precedes results"
git merge-base --is-ancestor afec214e 9c2b912a && echo "prereg precedes results"
git diff --stat 7a868424 0ce8569b            # 빈 출력이어야 한다 (cherry-pick 동일성)
```

### 6.3 하지 말 것 (검토관에게도 적용되는 규율)

- **홀드아웃 창(2015-2018)으로 새 채점을 돌리지 말 것.** 슬롯은 3개뿐이고 1개가 소모됐다. 코드가 막지만, 막히는 것을 확인하는 용도로만 실행하라.
- **봉인창(2019+) 데이터를 열지 말 것.** V13에는 실행 경로가 아예 없다.
- **결과를 본 뒤 문턱·기준선·귀무를 바꾼 재계산은 그 자체가 위반**이다(계약 `prohibitions.gate_threshold_relaxation`·`null_redesign_after_results`, 설계도 §3.9). 기준선을 바꿔 보고 싶다면 그것은 **판정이 아니라 진단**이며, 그렇게 표시해 달라 — 팩 안에서 우리가 한 것도 그 형태다(다이제스트 §7 Δ1~Δ3).

---

## 7. 다음 문서

판정 요청서는 **`00_REVIEW_REQUEST.md`**(팩 루트, 이 README와 나란히)다. 무엇을 판정해 달라는 것인지, 어떤 형식의 답을 원하는지, 어떤 항목이 사용자 결정 대기인지가 거기 있다.

> **[미확인]** 이 README를 집필한 시점(2026-09-09 20:2x KST)에 팩 루트에는 아직 `README.md`만 있었다. 최종본에 요청서가 함께 놓인다. **만약 루트에 없다면** 검토관 질문은 다음 세 곳에 이미 분산돼 있으니 그것을 요청서로 읽으면 된다 — `B_verdicts/00_VERDICT_DIGEST.md` §10(통계 6문항) · `H_prior_packs/00_STRATEGY_OPTIONS.md` §5(전략 Q1~Q5) · `D_governance/00_GOVERNANCE_DIGEST.md` §6.4·§7(거버넌스).

---

*작성 2026-09-09 (KST). 이 README의 모든 수치와 경로는 팩 안 파일을 직접 열어 확인했다. 확인하지 못한 것은 `[미확인]`으로 표기했다.*
