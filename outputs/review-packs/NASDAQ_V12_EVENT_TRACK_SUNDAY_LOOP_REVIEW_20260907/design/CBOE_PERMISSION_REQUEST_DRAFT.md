# CBOE 콘텐츠 사용 허가 요청 — 초안

> **초안입니다. 발송하지 않았습니다.** 대외 커뮤니케이션이고 회신 조건의 수용 여부도 판단이 필요하므로 저장소 소유자가 직접 검토·발송합니다.
>
> 배경과 근거: `docs/DECISIONS.md` 12-1(조사), 12-4b(결정), 12-5(대체 경로 조사 결과).

## 보내기 전에 확인할 것

**신청 자체가 양면적입니다.** 현재 위치는 CBOE 약관의 `"fair use" under the Copyright Act of 1976` 유보에 기대는 **회색지대**입니다. 신청해서 허가를 받으면 회색지대가 명시적 허가로 바뀌지만, **명시적 거절을 받으면 그 모호성이 사라져 제거 외 선택지가 좁아집니다.** 묻지 않는 편이 나을 수 있다는 뜻이며, 이 판단은 소유자 몫입니다.

- 접수처: `permissions@cboe.com`
- 절차 근거: <https://www.cboe.com/use-of-content/> — "you must receive approval in advance", "typically review and respond to requests within five business days, but is under no obligation"
- 수수료 유무: **문서에 명시 없음(NOT FOUND)**. 회신에서 유상 조건이 붙을 수 있습니다.
- 승인 시 조건: "such approval will be contingent upon your execution of a license agreement"

## 초안 (영문)

> **Subject:** Request to Use Cboe Content — non-commercial personal research project (delayed/EOD index data, open website)
>
> Hello,
>
> I am writing to request permission to use Cboe content, per the process described at cboe.com/use-of-content.
>
> **Who I am.** I am an individual maintaining a personal, non-commercial forecasting research project. There are no paying users, no subscriptions, no advertising, and no revenue of any kind associated with it.
>
> **What content I use.** End-of-day and delayed data only:
> - `VIX_History.csv` (daily VIX OHLC history)
> - `VIX9D_History.csv` (daily VIX9D history)
> - delayed options quotes from the public `cdn.cboe.com/api/global/delayed_quotes/options/` endpoint
>
> I do not use, and do not request, real-time data.
>
> **How I use it.** The data is used to compute statistics — historical base rates, volatility percentiles, and probability estimates for pre-registered forecasting questions. The results are published on a public website. Specifically:
> - Access is openly available to the public, with **no authentication system and no login**.
> - There is **no trading functionality** of any kind.
> - The material is provided **for informational purposes only**, and carries an explicit notice that it is not investment advice.
>
> I note that these three conditions correspond to the "Delayed Open Website" License described in §19(b) of the Cboe Market Data Policies (effective July 1, 2026), and I would like to ask whether that category, or another appropriate one, is available to a non-commercial individual project of this kind.
>
> **What is displayed.** Predominantly derived statistics rather than raw series — for example the probability that VIX closes above a threshold within a given window, and percentile ranks of current levels against history. A small number of individual closing values appear as context for those statistics.
>
> **Attribution.** I am happy to carry whatever attribution and copyright notice you require, in whatever form you specify, and to make any changes to the presentation that approval is conditioned on.
>
> **What I am asking.** Whether the above use is permitted, and if so under what license category, attribution requirement, and any applicable fee. If it is not permitted in its current form, I would welcome guidance on what would need to change — I would rather adjust or remove the usage than continue outside your terms.
>
> Thank you for your time.
>
> [이름]
> [연락처]
> [프로젝트 URL]

## 회신 시나리오별 대응

| 회신 | 대응 |
|---|---|
| 승인 (조건부 포함) | 조건을 `DECISIONS.md`에 기록하고 요구된 attribution·표시 변경을 구현. 라이선스 계약 체결은 소유자 |
| 유상 조건 제시 | 비용 대비 가치를 소유자가 판단. 비용을 감수하지 않을 경우 아래 "거절" 경로 |
| 거절 | VIX 계열 의존 제거가 불가피. `vix-25-90d`의 판정 출처와 base rate 산출에 영향 — 질문 재정의 또는 폐기 검토 필요 |
| 무응답 | 5영업일은 목표일 뿐 의무가 아님. 현행 회색지대 유지 여부를 소유자가 판단 |

## 거절 시 영향 범위 (미리 파악해 둔 것)

- `vix-25-90d` — 판정 출처가 "CBOE 공식 VIX 종가 데이터"로 registry에 고정돼 있다. 판정기준은 첫 예측 이후 변경 금지이므로 **질문 폐기(void) 후 새 질문**이 필요하다.
- `data/base_rates/volatility.md` — VIX 기반 기저율 전체
- `src/ai_fc/market/options_bl.py` — 옵션 내재확률 (대안 없음, 조사 결과 무료 공개 표시 가능한 미국 지수 옵션 소스는 존재하지 않음)
- `timeseries_v2/v4/v5` — VIX·VIX9D를 특징으로 사용

대안은 이미 조사했고 **전부 위치를 악화시킵니다**(12-5). FRED는 CBOE 저작권이 따라오면서 AI/ML 금지 조항이 추가되고, Yahoo는 자동 수집을 명시 금지하며, VIX9D는 대안 자체가 없습니다.
