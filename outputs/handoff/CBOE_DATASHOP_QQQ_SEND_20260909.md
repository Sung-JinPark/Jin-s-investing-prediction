# CBOE DataShop 질의 — 발송본 (2026-09-09)

> **이 문서는 사용자가 직접 보내는 것이다.** 나는 발송하지 않았고 보낼 수도 없다(외부 커뮤니케이션·금전거래는
> 저장소 소유자 사항, DECISIONS 12-5). 아래 §1을 그대로 복사해 보내고, 회신이 오면 §3 양식으로 기록해 달라.
> 근거 초안: `docs/design/v13_cboe_datashop_qqq_request_260907.md`(2026-09-07) · 조사 `docs/review/V12_INTRADAY_LEGAL_SOURCE_SURVEY_20260907.md`.

## 0. 초안에서 바뀐 것 — 질문 하나를 추가했다

2026-09-09 실측에서 **우리가 이미 보유한 Cboe 지수 CSV(VVIX·SKEW·VIX3M·VIX9D)의 표시 권리 라벨이 3중으로
모순**임이 드러났다:

| 출처 | 라벨 |
|---|---|
| `data/timeseries_v4/ledgers/raw_receipts.jsonl` | `repository_raw_allowed` |
| `data/timeseries_v6/registry/sources.yaml` | `private_raw_derived_public` |
| `docs/DECISIONS.md` 12-1 | CBOE ToU §2가 `display`·`publish`·`distribute`·`derivative work`를 **명시적 금지** |

`docs/generated/licenses.generated.md`에는 CBOE 행이 아예 없고 "Pending manual reviews"에만 있다. 즉 **이미 가진
데이터로 파생 확률을 공개 표시해도 되는지가 미해결**이다. 구매 질의와 같은 편지에서 함께 묻는 것이 효율적이라
질문 3을 추가했다. 이 답이 오기 전까지 옵션 지수 형상 피처의 **표시**는 금지(연구는 가능) 상태로 둔다.

## 1. 발송 본문 (그대로 복사)

**To:** Cboe DataShop 지원/영업 (datashop.cboe.com 문의 폼 또는 안내된 주소)
**Subject:** Historical QQQ options data — coverage, derived-display terms (§2b), and terms for already-public index CSVs

> Hello,
>
> I maintain a personal, non-commercial forecasting research project and would like to purchase historical
> **QQQ (Invesco QQQ Trust) options** data from DataShop. I have three questions before ordering.
>
> **1. Coverage.** I need history spanning **2007 through 2014** (and ideally to present) — options trades/NBBO
> quotes and, if available, your IV / greeks "Calcs" at end-of-day resolution to start. Can you confirm QQQ
> options coverage over that period and which product(s) provide the IV/greeks?
>
> **2. Derived-display terms (§2b).** My use is: (a) internal research/back-analysis of the historical data with
> deterministic numerical models, and (b) potentially displaying *derived* quantities on a public,
> non-commercial website — specifically model-computed probabilities and volatility statistics, clearly labeled
> as informational and not investment advice. I would **not** redistribute raw quotes, and the display would not
> be reverse-engineerable to the raw feed. Under §2b of the Historical Market Data Subscriber Agreement, does
> this derived display qualify, and does it require selecting a "redistribution" option at order time? I want to
> be sure I order the correct license from the start.
>
> **3. Publicly downloadable Cboe index CSVs.** Separately, I have been using the freely published daily index
> history files from `cdn.cboe.com` (VVIX, SKEW, VIX3M, VIX9D). Could you confirm the terms that apply to those
> specific files for (a) internal research and (b) publishing *derived* statistics — e.g. a model-computed
> probability that references VVIX as an input — on a public non-commercial site with attribution? I want to
> record the correct terms rather than assume them.
>
> I am purchasing **QQQ (an OPRA-listed ETF option)** specifically — not the NDX index option — to stay within a
> single Cboe agreement without a third-party index-owner overlay. Please let me know if that understanding is
> correct.
>
> I am happy to carry any attribution you require. Thank you.
>
> [이름] · [연락처] · [프로젝트 URL]

## 2. 보내기 전 확인 (소유자)

- 이름·연락처·프로젝트 URL 채우기.
- 예산 감각: EOD IV/그릭스 약 $500/월급, 일중(1분/틱)은 애드혹 $1.5~2.5k. **회신을 받는 것만으로는 비용이 들지 않는다.**
- 이 편지는 `docs/cboe_permission_request_draft.md`(permissions@cboe.com 콘텐츠 사용 편지)와 **다른 건**이다. 둘 다 미발송 상태이며, 지금 보내는 것은 DataShop 편지다.

## 3. 회신 기록 양식 (DECISIONS 12-8 형식)

회신이 오면 다음을 남긴다 — 원문을 그대로 보관해야 이후 표시 판단의 근거가 된다.

```markdown
## 2026-XX-XX — V12-D4: CBOE DataShop 질의 발송·회신 (사용자 실행)

**발송.** 일시 YYYY-MM-DDTHH:MM+09:00 · 수신처 <주소/폼> · 본문 outputs/handoff/CBOE_DATASHOP_QQQ_SEND_20260909.md §1 그대로.
**회신.** 일시 ... · 요지 ...
**§2b 판정.** 파생표시 (허용 | 조건부 허용 | 불가) — 조건: ...
**보유 지수 CSV 판정.** 연구 (허용|불가) · 파생표시 (허용|조건부|불가) — 조건: ...
**증빙.** 약관 캡처 파일 경로 + sha256 ...
**후속.** 라이선스 대장(docs/generated/licenses.generated.md) 갱신 · 표시 게이트 해제 여부 · 구매 여부.
```

기록 위치: `docs/DECISIONS.md` 말미 + 증빙 파일은 `data/intraday/receipts.jsonl`(디렉터리 신설) 또는
`data/licenses/` 아래. 캡처 파일은 커밋하되 **원자료(옵션 틱·쿼트)는 커밋하지 않는다**.

## 4. 회신 시나리오별 다음 행동 (설계도 P5와 연결)

| 회신 | 다음 행동 |
|---|---|
| §2b 파생표시 OK + 지수 CSV 표시 OK | 라이선스 대장 갱신 → 옵션 지수 형상 피처의 **표시** 게이트 해제. 구매는 P4(무료 피처블록) 결과 조건부 |
| 연구만 허용, 표시 불가 | 연구는 진행하되 파생 확률은 **내부 산출물(T0)** 로만. 라이브 카드에 옵션 유래 수치 금지 |
| QQQ 커버 부족·고가 | 옵션 표면 갈래 후순위. 봉인 아카이브 내 무료 피처블록(기간스프레드·달러·EBP)에 집중 |
| 무응답 4주 | 재발송 1회 후 P5를 '무기한 보류'로 기록하고 무료 경로만 진행 |
