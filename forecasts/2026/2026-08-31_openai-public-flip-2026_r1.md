---
forecast_id: 2026-08-31_openai-public-flip-2026_r1
question_id: openai-public-flip-2026
question_snapshot: "OpenAI(또는 그 상장 목적 법인)의 S-1이 2026-12-31까지 SEC EDGAR에 공개(public) 파일링으로 전환·접수될 확률은?"
timestamp: 2026-08-31 18:10 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 12
ci80: [5, 24]
window_end: null
snapshots:
  confidential_filing: "**2026-06-08 비공개(confidential) draft S-1 제출 — 회사가 직접 확인.** 'We expect it to leak so we are just announcing it'"
  company_statement: "'We have not decided on timing yet; it may be a while because there are things we want to do that are likely easier as a private company' (2026-06-08)"
  edgar_check: "2026-08-31 EDGAR 직접 조회 — company=openai 25개 엔티티 전수 확인 결과 24개가 제3자 SPV·피더펀드(Form D), 1개는 무관한 OPENAIRPLANE INC. openai+group/inc/holdings x type=S-1 전부 'No matching companies'. **본체 공개 S-1 없음** (JOBS Act DRS는 공개 전환 전까지 EDGAR 미게시이므로 비공개 제출 사실과 모순 없음)"
  structure: "2025-10 구조조정으로 영리 부문이 OpenAI Group PBC로 전환 — IPO 호환 구조"
  reported_timeline: "CFO Sarah Friar가 2026년 8월 직원들에게 2027년 상장 예상 전달 [미검증, 2차 출처]"
market_implied: null
edge: null
sources_count: 8
---

## [0] 질문 검증

판정 가능하고 기준이 기계적이다 — 2026-12-31까지 EDGAR에서 **공개 S-1/F-1**이 확인되면 YES.

**중요한 사실 확인**: OpenAI는 이미 **2026-06-08에 비공개 draft S-1을 제출했고 회사가 직접 확인했다.** EDGAR에서 본체의 공개 S-1이 검색되지 않는 것은 이와 **모순되지 않는다** — JOBS Act상 비공개 제출(DRS)은 공개 전환 전까지 EDGAR에 게시되지 않기 때문이다. 이 구분을 놓치면 "아직 아무것도 제출하지 않았다"는 잘못된 전제로 예측하게 된다.

따라서 질문은 "제출할 것인가"가 아니라 **"이미 제출된 비공개 초안이 4개월 안에 공개로 전환되는가"**이다.

## [1] Outside View — base rate (anchor: 20%)

저장소 `data/base_rates/corporate-event.md`는 "비공개 S-1 → 공개 전환 통상 1~6개월"(Airbnb 3개월, Coinbase 2개월, Uber 4개월, Rivian 2개월)을 담고 있으나 **두 가지 문제가 있다.**

1. **이 파일은 2026-06-08 비공개 제출 사실을 반영하지 않았다**(수집일 2026-07-08). 즉 이미 발생한 이벤트를 미발생으로 취급한다.
2. **생존 편향.** 인용된 사례는 전부 **실제로 상장까지 간 회사들**이다. 같은 파일이 이미 반례를 담고 있다 — WeWork(공개 후 철회), Cerebras(공개 S-1에서 상장까지 1.5년), Databricks(2027로 후퇴), Stripe(10년+ 비상장). 조건부 표본을 무조건부에 적용하면 안 된다.

"비공개 제출 후 12개월 내 공개 전환 비율"이라는 무조건부 통계는 **NOT FOUND**(체계적 집계가 공개되지 않음).

규정상 상한은 계산할 수 있다 — **JOBS Act상 공개 전환은 로드쇼 개시 15일 전이 마지노선**이므로 공개 전환 시점은 대체로 상장일 −1~3개월이다. 2026-12-31까지 공개 전환이 일어나려면 상장이 **늦어도 2027년 1분기~상반기 초**여야 한다.

생존 편향을 제거하고 규정 제약을 반영해 **anchor 20%**.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| **회사가 명시적으로 지연을 시사** — "may be a while", "비상장 상태가 하기 쉬운 일들이 있다". 상장 의지 표명이 아니라 유보 표명이다 | 하락 | −6%p |
| CFO가 2026년 8월 직원들에게 **2027년** 상장 예상을 전달했다는 보도 [미검증] — 사실이면 2026년 내 공개 전환은 규정상 상한과 충돌 | 하락 | −4%p |
| **약 $70억 규모 직원 주식 자사주 매입($852B 밸류에이션)** [미검증] — IPO의 주요 동인인 직원 유동성을 내부에서 해소해 상장 압박을 낮춘다 | 하락 | −3%p |
| 사적 자본 조달 능력 — $122B 규모 Series H [미검증]. 자본시장 접근에 IPO가 불필요 | 하락 | −2%p |
| 비영리 구조조정·특수관계자 거래에 대한 SEC 코멘트 라운드가 길어질 수 있는 구조 | 하락 | −2%p |
| **비공개 제출 자체는 진행 중** — 준비가 실재하며, SEC 코멘트가 빨리 정리되면 연내 전환도 물리적으로 가능 | 상승 | +5%p |
| 2025-10 PBC 전환 완료로 상장 호환 구조는 이미 갖춰짐 | 상승 | +2%p |
| AI 섹터 자금조달 환경이 우호적인 동안 상장을 서두를 유인 | 상승 | +2%p |

순 조정 **−8%p** → 12%.

## [3] 분해 트리

| 경로 | 확률 | 연내 공개 전환 조건부 | 기여 |
|---|---|---|---|
| 2027년 상장 목표 유지(보도대로) | 0.65 | 0.06 | 4% |
| 2026년 4분기 조기 상장으로 선회 | 0.10 | 0.75 | 8% |
| 상장 무기한 연기 | 0.20 | 0.01 | 0% |
| 철회 | 0.05 | 0.00 | 0% |
| 합계 | | | **12%** |

## [4] Premortem — 틀릴 이유 3가지

1. **시장 창구가 열려 회사가 서두르는 경우.** AI 밸류에이션이 정점 근처이고 자금 수요가 크다. 경영진이 창구를 놓치지 않으려 4분기 상장으로 선회하면 공개 전환은 10~11월에 일어날 수 있다.
2. **2027년 타임라인 보도가 틀린 경우.** CFO 발언은 2차 출처 경유로 1차 확인에 실패했다. 이 근거로 −4%p를 깎았는데, 보도가 부정확하면 근거가 사라진다.
3. **반대 방향 — 12%도 높은 경우.** 회사가 공개적으로 "may be a while"이라고 말했고 자사주 매입으로 유동성 압박까지 해소했다. 2027 상장이면 규정상 공개 전환은 2027년이 되어야 자연스럽다. 그렇다면 6~8%가 맞다.

## [5] 최종 출력

- 최종 확률: **12%** (80% CI: 5~24%)
- **핵심 근거 3줄**:
  1. 비공개 S-1은 **이미 2026-06-08에 제출**됐으므로 질문은 "제출 여부"가 아니라 "4개월 내 공개 전환 여부"다.
  2. 회사가 명시적으로 "may be a while"이라 밝혔고, 자사주 매입으로 IPO의 주요 동인인 직원 유동성을 스스로 해소했다.
  3. JOBS Act상 공개 전환은 상장 1~3개월 전이므로, 연내 전환은 2027년 1분기 상장을 함의하는데 보도된 타임라인(2027년)과 충돌한다.
- **관찰 지표 2개**:
  1. **EDGAR 본체 공개 파일링 등장** — 이 질문의 직접 신호. 월 1회 조회로 충분하다.
  2. **인수단(underwriter) 선정·로드쇼 일정 보도** — 로드쇼가 잡히면 15일 전 공개 전환이 규정상 강제되므로 즉시 70% 이상으로 상향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- CNBC "OpenAI confidentially files for IPO" (2026-06-08, 회사 확인) — https://www.cnbc.com/2026/06/08/openai-confidentially-files-for-ipo-prepping-wall-street-for-ai-debut.html
- Fortune OpenAI 비공개 S-1 제출 (2026-06-09) — https://fortune.com/2026/06/09/openai-files-confidential-s-1-sec-ipo/
- SEC EDGAR 회사 검색 (2026-08-31 직접 조회: 본체 공개 S-1 부재 확인, 25개 엔티티 전수 확인) — https://www.sec.gov/cgi-bin/browse-edgar?company=openai&type=S-1&action=getcompany
- SEC JOBS Act 비공개 제출(DRS) 규정 — https://www.sec.gov/corpfin/announcement/draft-registration-statement-processing-procedures-expanded
- 저장소 내부: `data/base_rates/corporate-event.md` (비공개→공개 전환 1~6개월 — **2026-06-08 제출 미반영, 생존 편향 있음**)

**[미검증]** 표기: CFO Sarah Friar의 2027년 상장 발언, 약 $70억 자사주 매입, $852B 밸류에이션, $122B Series H는 **전부 2차 매체 경유이며 1차 확인에 실패**했다. 이들 항목이 하방 조정의 상당 부분을 지지하므로, 확률의 신뢰도는 이 미검증 항목들에 의존한다는 점을 명시한다. "비공개 제출 후 12개월 내 공개 전환 비율"의 무조건부 통계는 **NOT FOUND**.
