# Cboe DataShop — QQQ 옵션 이력 사용·구매 질의 (초안, 2026-09-07)

> **초안입니다. 발송·구매하지 않았습니다.** 외부 커뮤니케이션·금전거래는 저장소 소유자가 직접 검토·실행합니다.
> 이 문서는 D4(다른 데이터=옵션표면) 갈래의 **QQQ 프록시 경로** 준비물이다.
> 근거: 조사 문서 `docs/review/V12_INTRADAY_LEGAL_SOURCE_SURVEY_20260907.md` §2·§5.
> 기존 `docs/cboe_permission_request_draft.md`(VIX·무료 EOD·오픈웹사이트)와 **별개** — 그건 permissions@cboe.com 콘텐츠-사용 편지, 이건 DataShop 이력 데이터 구매·라이선스.

## 0. 왜 QQQ 프록시인가 (제3자 오버레이 회피)

- NDX(Nasdaq-100 **지수**) 옵션은 OPRA 배포지만 지수 소유자가 Nasdaq이라, Cboe 가입자 계약 §3d·§16(제3자 수익자)상
  **Nasdaq 별도 라이선스 오버레이**가 얹힐 수 있다.
- **QQQ(Nasdaq-100 추종 ETF) 옵션**은 OPRA 통합 소스의 일반 상장옵션이라 **Cboe 단일 계약으로 커버**되고 제3자 오버레이가
  없다. NDX 대용 프록시로 신뢰가능(동일 기초·높은 상관). → **QQQ로 진행하면 라이선스가 단순·깨끗하다.**
- 결과 해석 caveat: QQQ는 ETF라 배당·트래킹 오차·미국형 조기행사 특성이 NDX 유럽형 지수옵션과 미세하게 다르다 — 파생층에 명기.

## 1. 요청/질의 대상·용도

- 스토어: Cboe DataShop (datashop.cboe.com). 계약: Historical Market Data Subscriber Agreement (v.20220527).
- 대상: **QQQ 옵션** 과거 이력 — 트레이드·NBBO 쿼트 + IV/그릭스(Calcs), 설계창 **2007-2014** 커버(DataShop 2004+).
- 해상도: 1차 **EOD IV/그릭스**(비용 최소, $500/월급)로 시작. 일중(1분/틱)은 정밀도 필요 시 확장(애드혹 $1.5–2.5k/월·요청).
- 용도: (a) 내부 연구·재분석(결정론 수치모델의 VRP·IV 스큐 base rate — dualdb §8 예외), (b) 잠재적 파생층 표시(라이브 카드 '참고 의견' 확률, §2b 조건부).

## 2. 발송 전 확인할 것 (소유자 판단)

- **§2b 파생표시 조건** 3가지 충족 확인: ① 주문 시 '재배포권(redistribution)' 옵션 선택, ② 표시물이 원자료를 역설계 불가한 파생물일 것, ③ 지수/금융상품이 아닐 것. QQQ 파생확률 표시가 이 셋을 만족하는지 명시 질의.
- **가격 티어**: EOD 구독 vs 애드혹 이력 vs 일중 — 예산 결정.
- **회신 리스크**: 명시적 거절 시 옵션표면 갈래가 좁아진다(대안 OptionMetrics는 학술게이트/고가). 다만 DataShop은 구매형이라 거절보다 '구매 가능/불가' 성격.

## 3. 질의 초안 (영문 — datashop 지원/영업)

> **Subject:** Historical QQQ options data — internal research use, and derived-display terms under §2b
>
> Hello,
>
> I maintain a personal, non-commercial forecasting research project and would like to purchase historical **QQQ (Invesco QQQ Trust) options** data from DataShop. I have two questions before ordering.
>
> **1. Coverage.** I need history spanning **2007 through 2014** (and ideally to present) — options trades/NBBO quotes and, if available, your IV / greeks "Calcs" at end-of-day resolution to start. Can you confirm QQQ options coverage over that period and which product(s) provide the IV/greeks?
>
> **2. Derived-display terms (§2b).** My use is: (a) internal research/back-analysis of the historical data with deterministic numerical models, and (b) potentially displaying *derived* quantities on a public, non-commercial website — specifically model-computed probabilities and volatility statistics, clearly labeled as informational and not investment advice. I would **not** redistribute raw quotes, and the display would not be reverse-engineerable to the raw feed. Under §2b of the Historical Market Data Subscriber Agreement, does this derived display qualify, and does it require selecting a "redistribution" option at order time? I want to be sure I order the correct license from the start.
>
> I am purchasing **QQQ (an OPRA-listed ETF option)** specifically — not the NDX index option — to stay within a single Cboe agreement without a third-party index-owner overlay. Please let me know if that understanding is correct.
>
> I am happy to carry any attribution you require. Thank you.
>
> [이름] · [연락처] · [프로젝트 URL]

## 4. 회신 시나리오

| 회신 | 대응 |
|---|---|
| EOD IV/그릭스 2007-2014 구매가능 + §2b 표시 OK | EOD부터 구매(연구 착수), 표시는 파생층 게이트(V13) 통과 후 |
| §2b 표시 불가(연구만) | 연구는 진행, 라이브카드 표시는 보류(파생확률 내부만) |
| 일중만·EOD 없음/고가 | EOD 대안(OptionMetrics 직접 상업 라이선스) 재검토 or 예산 상향 |
| QQQ 커버 부족/거절 | 옵션표면 갈래 후순위화, V12b(경로)·V13-VOL(변동성)에 집중 |

## 5. 이 갈래의 위치 (정직)

포스트모템 재편상 옵션표면(C1)은 **V12b(T-B)·V13-VOL(T-C)가 소진된 뒤**의 경로다(사전확률 중~높이나 두 1순위 뒤). 따라서
**리드타임 확보용으로 질의는 지금 보낼 수 있으나**(회신까지 시간이 트랙 결정과 무관하게 흐름), 실제 구매·착수는 V12b/V13
1차 결과 후로 미뤄도 손실 0. 발송 여부·시점은 소유자 결정.
