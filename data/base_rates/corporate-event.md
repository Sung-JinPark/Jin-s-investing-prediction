# Base Rates — corporate-event 도메인

### 비공개(confidential) S-1 → 공개 전환 소요 (진행되는 경우)
- **base rate**: 통상 1~6개월 — Airbnb 3개월(2020-08→11), Coinbase 2개월(2020-12→2021-02), Uber 4개월(2018-12→2019-04), Rivian 2개월
- **출처**: 각 사 발표·SEC EDGAR·언론 (수집일: 2026-07-08)
- **신뢰도**: 검증 (사례), 체계적 통계는 NOT FOUND
- **사용 질문**: openai-s1-2027h1
- 반례: WeWork 2019 (공개 후 철회), Cerebras (공개 S-1 2024-09 → 상장 2026-05, 1.5년), Stripe (10년+ 비상장), Databricks (2027로 후퇴)

### 규제: 공개 전환은 로드쇼 15일 전이 마지노선 (JOBS Act)
- 함의: 공개 전환 시점 ≈ 상장일 − 1~3개월. 상장 일정을 알면 전환 시점 역산 가능
- **신뢰도**: 검증 (일반 규정)
- **사용 질문**: openai-s1-2027h1

### OpenAI 비공개 S-1 제출 — 2026-08-31 사실 갱신 (기존 항목 무효화 주의)
- **2026-06-08 OpenAI가 SEC에 비공개(confidential) draft S-1을 제출했고 회사가 직접 확인했다.** 회사 코멘트: "We expect it to leak so we are just announcing it"
- 회사의 타이밍 입장: "We have not decided on timing yet; it may be a while because there are things we want to do that are likely easier as a private company"
- EDGAR 직접 조회(2026-08-31): company=openai 25개 엔티티 전수 확인 결과 24개가 제3자 SPV·피더펀드(Form D), 1개는 무관한 OPENAIRPLANE INC. 본체 공개 S-1 **없음**. 단 **JOBS Act DRS는 공개 전환 전까지 EDGAR에 게시되지 않으므로 비공개 제출 사실과 모순되지 않는다**
- 2025-10 구조조정으로 영리 부문이 OpenAI Group PBC로 전환 — 상장 호환 구조 완비
- **출처**: CNBC 2026-06-08 https://www.cnbc.com/2026/06/08/openai-confidentially-files-for-ipo-prepping-wall-street-for-ai-debut.html · Fortune 2026-06-09 · SEC EDGAR 직접 조회 (수집일: 2026-08-31)
- **신뢰도**: 검증 (회사 확인 + EDGAR 직접 조회)
- **사용 질문**: openai-public-flip-2026, openai-s1-2027h1
- **기존 "비공개 S-1 → 공개 전환 1~6개월" 항목 사용 시 필수 caveat**: 인용 사례(Airbnb 3개월·Coinbase 2개월·Uber 4개월·Rivian 2개월)는 **전부 실제 상장까지 간 회사**로 생존 편향이 있다. 같은 파일의 반례(WeWork 철회, Cerebras 1.5년, Databricks 2027 후퇴, Stripe 10년+ 비상장)가 무조건부 표본을 보여준다. "비공개 제출 후 12개월 내 공개 전환 비율"의 체계적 집계는 **NOT FOUND**
- **규정 상한**: JOBS Act상 공개 전환은 로드쇼 개시 15일 전이 마지노선 → 공개 전환 시점은 대체로 상장일 −1~3개월

### 미국 EPS 컨센서스 상회율 (2026-08-31 갱신)
- **S&P 500**: Q2 2026 **86%**(2021년 이후 최고) · 1년 80% · **5년 78%** · 10년 76%. 동률(tie) **3%로 별도 집계**되므로 strict-inequality 질문(동률=NO)에 그대로 사용 가능
- **워크다운이 평소보다 약하다**: Q3 2026 부정 가이던스 비율 **36%**(35/98) vs 5년 평균 58% · 10년 60%. 다음 분기 허들이 높아졌다는 뜻
- **총계 서프라이즈 지표는 현재 오염됨**: 헤드라인 +26.5%(집계 이래 최고)는 Alphabet(지분증권 미실현이익 $98B)·Amazon($53.4B Anthropic) 회계 아티팩트. **두 종목 제외 시 +10.8%, Mag 7은 +66.2% → +4.4%**. 메가캡 서프라이즈 폭 모델링에는 +4.4%를 쓸 것
- 비트해도 주가는 하락 중: Q2 2026 긍정 서프라이즈 기업 평균 주가 −0.3%(발표 ±2일), 5년 평균 +1.0%
- **출처**: FactSet Earnings Insight 2026-08-28 (수집일: 2026-08-31) https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_082826.pdf
- **신뢰도**: 검증 (1차 PDF 직접 추출)
- **사용 질문**: avgo-eps-beat-fq3-2026, orcl-eps-beat-fq1-2027, tsmc-eps-beat-2026q3, msft-eps-beat-fy27q1, googl-eps-beat-2026q3, meta-eps-beat-2026q3
- **종목별 편차가 크다 — 그룹 기저율을 그대로 쓰면 안 된다**: MSFT 8/8(평균 +8.2%, 최소 +3.9%) · TSMC 4/4(평균 +8.1%) · GOOGL 명목 8/8이나 GAAP 오염으로 깨끗한 분기 약 5개 · META 7/8이나 **직전 분기 −13% 미스** · ORCL **5/8로 최저**, 직전년 동일 분기 1센트 미스 · AVGO 7연승이나 **서프라이즈 중앙값 +1.74%로 동률 리스크 최대**
