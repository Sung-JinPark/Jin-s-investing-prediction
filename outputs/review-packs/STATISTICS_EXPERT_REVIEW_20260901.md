# 통계 비교 차트 전수 전문가 검수 — 최종 보고서

- 기간: 2026-08-31 ~ 2026-09-01 (KST)
- 산출 PR: [#114](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/114) (본검수) · [#121](https://github.com/Sung-JinPark/Jin-s-investing-prediction/pull/121) (E항목 완결)
- 상태: **전 항목 머지·배포·라이브 검증 완료**
- 부록: A(결론 전/후 18건 대조) · B(화면 공시 추가 11건)

---

## 1. 요청과 범위

사용자 요청: "지금 통계에 있는 그래프들 전체적으로 통계적 그리고 경제적 전문가 관점으로 맞는 그래프인지 전체적으로 검수. 앞서서 경제·통계·투자 관점 여러 레포트·논문 등 선행 조사 → 정밀 검사 설계 계획 → 조정."

대상: 통계 비교(#statistics) 뷰의 매크로 차트 25종 + IPO 참고 블록 7종 + 검수 중 머지된 타 세션 신규 차트 3종(PR #102).
생성기: `src/ai_fc/statistics_lab.py` (검수 전 3,937줄 전수 감사).

**사용자 승인 결정 3건**
1. 시대 비교 결론은 **같은 경과월 비교로 교체** + 닷컴 정점/말기 값 병기
2. valuation_proxy **분모를 비금융 기업 세후이익으로 교체** (분자·분모 모집단 정합)
3. 수정 범위: ①통계 오류 ②차트 설계 ③사용자 공시 ④계약·검증기 정리 **전부**

---

## 2. 선행 조사 (문헌 표준 → 적용)

| 주제 | 문헌 표준 | 출처 | 적용 |
|---|---|---|---|
| 금리 곡선 | 침체 연구·Fed 확률모델은 10y−3m (10y−2y는 시장 관행) | Estrella–Mishkin, NY Fed, SF Fed | `T10Y3M` 시리즈 추가 — 차트 4선, 결론 병기 |
| 집계 P/E | 분자·분모 모집단 일치 필수; 이익률 레짐·해외매출·금리 무시가 공인된 한계 | AQR, Current Market Valuation | 분모 `CPATAX`(전체 경제) → `W328RC1Q027SBEA`(비금융 세후이익, IVA·CCAdj) + 한계 caveat |
| 성장 수준 계열 추세 | 로그-선형 OLS가 표준 (수준 OLS는 이탈률 과대) | 계량 표준 | 가계 자산 추세 이탈 로그 OLS 전환 + 월 단위 축 정합 |
| 신용잔고 | 시총 대비 정규화가 표준; Z.1 분기 대용 ≠ FINRA 월간 | GuruFocus/FINRA | 대용치 한계 화면 공시 |
| M2 비율 | 장기 정규화 지표, 단기 신호 아님; RRP 등 기관 유동성 누락 | MacroMicro | 명목·누락 한계 공시 |
| 원자재→CPI | 선행성은 시기 의존, 최근 약함 — 고정 리드 주장 곤란 | NY Fed, CEPR | 제목 서술형 + 시기의존 문구 |
| IPO 지표 | Jay Ritter 표가 절대 기준 | Ritter IPO Data (IPOs-Tech.pdf) | 큐레이션 수치 40개 전량 대조 → **40/40 일치** |
| 시대 규모 비교 | 명목 달러 27년 비교는 무효 — 규모(GDP) 정규화 | 신용 문헌 일반 | 회사채 잔액·순발행 GDP 대비 % 변환 (E항목, #121) |

---

## 3. 발견 4계층과 수정 내역

### ① 통계 오류 (수치가 틀림)

**A. "닷컴 같은 시점" 결론이 실제로는 다른 경과월 비교** — 최우선.
현재 사이클 endpoint(경과 33~42개월)를 닷컴 endpoint(57~59개월)와 비교하며 "같은 시점"이라 표기하고 있었다.
→ `months_elapsed()`/`matched()` 헬퍼 신설, **13개 결론 재작성**: 같은 경과월 값 + 닷컴 말기 값 병기 + 데이터 구동 비교어(높/낮 삼항).
대상: policy_rate · valuation_proxy · nasdaq_per_m2 · nasdaq_per_household · m2_nasdaq · margin_credit_proxy · consumer_credit_growth · profit_growth · household_debt_service · unemployment_rate + (#102의) structures_buildout · corporate_bond_issuance · investment_share_of_gdp.

그림이 실질적으로 바뀐 예:
- 가치평가: (전) 사실상 29.8배 vs 닷컴 말기 43.7배만 비교 → (후) "현재 29.8배로 **닷컴 같은 36개월차의 27.4배보다 높음** (말기 43.7배)"
- 제조시설 건설: (전) 현재 71을 말기 103과 "견줍니다" → (후) "**같은 41개월차의 220보다 낮음** (말기 103)"
- 나스닥/M2: (전) 201 vs 말기 406 → (후) 같은 42개월차 206과 **사실상 동일**

**B. valuation_proxy 분모 교체**: 분자(비금융 기업주식 시가 NCBEILQ027S)에 맞춰 분모를 전체 경제 이익(CPATAX)에서 비금융 세후이익(W328RC1Q027SBEA, IVA·CCAdj 일치)으로. CPATAX는 profit_growth 전용으로 유지.

**C. 가계 자산 추세 이탈: 수준 OLS → 로그-선형 OLS.** 성장 잔액 계열에 수준 선형추세는 추세를 체계적으로 과소추정해 이탈률을 부풀림. 전환 후 수치가 크게 변함: 주식 +41% → **−5%**, 현금 +23%, 채권 +18%. 고정 문장("주식의 이탈이 가장 커")이 새 수치와 모순 → 결론을 argmax 데이터 구동으로 재작성.

**D. 같은 차트 축 버그**: period가 분기 인덱스인데 대시보드가 M+n(월) 라벨 — 월 환산으로 통일.

### ② 차트 설계

- **E. 회사채 잔액·순발행 (PR #121)**: 조 달러 저량 + 십억 달러 연율 유량을 한 축에(unit `trillions_and_billions_usd`) → **둘 다 명목 GDP 대비 %**. 결과: 명목 "8.0조 vs 1.8조"(4.4배)가 **25.2% vs 20.5%**(1.2배)로, 순발행은 **방향 반전** — 닷컴(GDP의 3.6%)이 현재(1.5%)보다 많았음.
- **F. 10y−3m 병기**: T10Y3M 2선 추가(닷컴/현재) — 총 4선.
- **G. 주택·제조 경기 패널**: %YoY + 확산지수 혼합 단위 → 지표별 단위 명시(reading_guide).
- **H. 유가·구리 패널**: 제목 서술형("유가·구리와 두 달 뒤 CPI 나란히 보기") + 시기의존 caveat.

### ③ 사용자 공시

**I. caveat가 화면에 안 가던 문제**: 투영(projection)이 caveat 필드를 제거 → "FINRA 아님" 같은 경고가 사용자에게 전달 안 됨. 투영에 caveat 유지 + 대시보드 카드마다 **"이 수치의 한계" 접힘 블록** 렌더. 차트별 공시 11건 추가(부록 B): Z.1 대용/FINRA 아님, 명목 비교, 소표본, OECD 지수(≠KOSPI), 지표별 기준일 상이, 저량/유량 비합산 등. 검증기도 caveat를 필수 필드로 강화(투영 포함).

### ④ 계약·검증기 정리

- **J.** 계약 yaml 죽은 섹션 제거: yahoo_chart, nyu_stern, kospi_external_semiconductor_pulse, historical_event_studies; recession_panel housing을 실제 사용 시리즈(HOUST)로 정정 + 축 주석.
- **K.** breadth 검증기 하드코딩 기대값 → 빌더와 같은 방식의 재계산 대조(overlay 조건부).
- **L.** 죽은 레거시 빌더 916줄 + 고아 헬퍼 11개 삭제.
- **M.** 무의미(vacuous) FRED 단언 → 실질 검사로 교체.
- **N.** Ritter 대조: 1995–99·2023–25 큐레이션 수치(건수·첫날수익률·P/S·흑자비중·적자EPS비중) **40/40 일치** — 수동 큐레이션 파일 무수정 원칙 준수.

---

## 4. 데이터 재생성 방식 (FRED 키를 다루지 않고)

신규 FRED 시리즈(W328·T10Y3M)는 원장(ledger) 충전이 필요하나 로컬에 키가 없음(GitHub Actions 시크릿 전용). 키 평문을 취급하지 않기 위해 **브랜치 한정 임시 워크플로**(자기 브랜치에만 push, `${{ secrets.FRED_API_KEY }}` 사용)로 CI에서 충전 — 총 6회 실행, 각 역할 완료 후 **머지 전 삭제**. `HEAD:main` 하드코딩된 기존 statistics-refresh는 불사용(브랜치 코드가 main에 밀리는 사고 방지).

## 5. 병행 세션 머지 경합 대응

- **PR #102**(ai-buildout 3개 차트)가 검수 도중 먼저 머지 → 7개 파일 충돌 해소: 계약 yaml은 main 기반 재구성(#102 시리즈 수용 + 검수 편집 유지 + main의 중복 `federal_reserve_z1` 키 정리), 관측 원장은 (source,series,date,rev) 키 union — 추가분이 정확히 T10Y3M 7,922행 + W328 126행뿐임을 검증. #102의 3개 차트 결론에서 동일한 endpoint 오류를 발견해 함께 수정.
- **PR #119/#120**(SPX/연방부채 전 구간 차트, yahoo 잔재 제거)이 #121 진행 중 머지 → 영수증 원장 union(main 589 + 43), 관측 원장 자동병합 중복 키 0 확인.

## 6. 검증

| 항목 | 결과 |
|---|---|
| 전체 테스트 스위트 | #114 시점 975 passed → #121 시점 **991 passed, 7 skipped** |
| Ritter 원본 대조 | 40/40 일치 (IPOs-Tech.pdf pypdf 추출) |
| 로컬 브라우저 검증 | 29개 카드 caveat 접힘 렌더, 새 결론·4선·라벨, 콘솔 오류 0 |
| 라이브 배포 검증 (#114) | statistics.json 8/8 항목 통과 |
| 라이브 배포 검증 (#121) | 6/6 항목 통과 (GDP% 단위·라벨·결론·caveat·타 세션 신규 차트 공존) |

## 7. 미변경으로 남긴 것 (알려진 한계)

- **replay 해시 불일치**: V5.2 아티팩트의 build는 generated_at 포함 해시 / verify는 제외 — **기존 버그**, 이번 범위 밖(문서화만).
- IPO 참고 블록 수치는 수동 큐레이션 — 직접 수정 금지 원칙 유지(대조만).
- 옵션 내재확률 등 market_implied 관련 표기는 이번 검수 범위 밖.
- corporate_bond_pressure(HQMCB10YR 스프레드) 등 나머지 차트는 검수 결과 수정 불요 판정.

## 8. 정리(하우스키핑)

- 임시 워크플로 2종 모두 머지 전 삭제 확인.
- 머지된 원격 브랜치(claude/stats-expert-review, claude/stats-review-bond-gdp) 삭제 — 저장소 관례와 일치.
- worktree `stats-review` → `worktrees/retained-merged/`로 이동.

## 9. 커밋 지도

| PR | 주요 커밋 | 내용 |
|---|---|---|
| #114 | 9ddb9576 | 검수 본작업 (A~D·F~N) |
| #114 | eec3dba8 / ac9547d8 | 기계가독 계보·source_ids 정합 |
| #114 | 559bab3b | 추세 이탈 결론 데이터 구동화 |
| #114 | 2e8bff6f | #102 병합 통합 (원장 union) |
| #114 | (직전 커밋) | #102 3개 차트 결론 matched 통일 |
| #121 | ad0aed62 | 회사채 GDP % 변환 (E항목) |
| 공통 | data: 커밋 6건 | CI 원장 충전·payload 재생성 |
