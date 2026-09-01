# AI 빌드아웃 계측 레이어 설계도 (v1, 2026-08-31)

사용자가 제시한 "AI 버블" 논지 7개 절을 저장소의 두 표면(**통계 카테고리**, **예측 레이어**)에
어떻게 편입할지 정하는 설계 문서. 조사 근거: 정찰 3 + 공공소스 6 + 종합 1 에이전트,
그리고 아래 §3의 자체 재현.

---

## 1. 선결론

1. **논지 7개 절 중 기계 측정이 가능한 것은 3개다** — §2(ROI 부재: SEC XBRL), §5(투자/GDP: BEA),
   §6(금리 임계: FOMC 성명). §1·§3은 바스켓을 동결해야만, §4는 영구히 서술 앵커,
   §7(포트폴리오 처방)은 CLAUDE.md상 시스템 범위 밖(개인 맞춤 투자조언 금지).
2. **첫걸음은 신규 원천 온보딩이 아니다.** 이미 승인된 FRED 경로에 BEA 시리즈 3개를 추가하는 것만으로
   논지 §5 전체가 공식 데이터로 재현된다. 정책 YAML 변경 0, 신규 워크플로 0.
3. **코드가 강제하는 차단이 있다.** `authoritative_statistics.py:34` `_SECRET_QUERY_KEYS =
   {api_key, apikey, key, token, access_token, secret, registrationkey, user_id, userid}` 가
   영수증 URI에 비밀 쿼리를 금지한다 → **BEA(`UserID=`)·Census(`key=`)·EIA(`api_key=`)·
   BLS(`registrationkey=`) 키드 API는 넷 다 영수증 생성 불가.** 정책이 아니라 코드 사실이며,
   무키 벌크 엔드포인트만이 유일한 합법 경로다. (검증: 코드 직접 확인)
4. **통계 랩은 "닷컴 1995–1999 vs 현재 2023–" 2시대 비교 DB다.** 닷컴 대응 계열이 없는 지표
   (데이터센터 건설 2014-01+, 하이퍼스케일러 XBRL 2009+, BTOS 2023+)는 여기 넣으면 안 되고
   다른 레인으로 보내야 한다. 이 원칙 하나가 아래 배치 전부를 결정한다.

---

## 2. 이미 있는 것 (재구축 금지)

| 자산 | 위치 | 상태 |
|---|---|---|
| FRED 33시리즈 수집·영수증·정규화 원장 (37,741행) | `statistics_lab.py:52` `FRED_SERIES` | 라이브, 주간 |
| raw→영수증→원장 파이프라인 전체 | `authoritative_statistics.py` (726줄) | **완성. 신규 원천은 재사용만** |
| Fed Z.1 zip 다운로드·파싱 | `statistics_lab.py:676` `_parse_z1` | `FL663067003`만 추출 중 — **같은 zip에 회사채 시리즈 존재** |
| 하이퍼스케일러 4사 capex·OCF·D&A·debt_issued 원시 팩트 (112레코드) | `ai_capital_cycle.py:24` | **팩트만 저장, 파생비율 0개** |
| dualdb 8시대·33계열·285,289행 + role 택소노미 | `dualdb/` | 라이브. **role 집계 코드 0개** |
| 22개 권위 차트 (ipo·liquidity·rates·valuation·credit·economy) | `dotcom_statistics_latest.json` | 발행 중, `_site/statistics.json` **84,927 / 120,000 B** |
| 철도 마니아 앵커 | `context_bridge.py:332` `CURATED_DEEP` | 프롬프트 주입 중 |
| 이벤트 정의(PRICE_BUST/CAPITAL_CYCLE_BREAK/FINANCING_STRESS) | `reports/md/claude_ai_bubble_..._260804.md:60` | **사전등록됐으나 미구현** — 아래 질문들이 이 공백을 메움 |

---

## 3. 자체 재현한 수치 (설계 근거)

무키 fredgraph로 GDP·Y034RC(정보처리장비)·Y001RC(지식재산생산물) 1947Q1~2026Q2 취득 후 계산:

| 정의 | 1995Q1 | 2000Q4 | 2020Q2 | 2026Q2 |
|---|---:|---:|---:|---:|
| **D1** 장비/GDP | 2.41% | **2.91%** | 1.94% | **2.45%** |
| **D5** (장비+IPP)/GDP | 5.31% | **6.95%** | **7.50%** | **8.21%** |

**설계에 미치는 함의 3가지**
- 논지의 "7% 임계 → 현재 8%"는 **D5 정의에서만** 성립한다. 하드웨어만 보면 현재는 닷컴 정점보다 **낮다**.
- 2020Q2 7.50%는 분모(GDP) 붕괴가 만든 **명백한 위양성** — 임계 규칙을 신호로 쓰면 안 되는 증거.
- 2000Q4의 6.95%는 2013년 포괄개정의 R&D 자본화 소급 적용 뒤에야 계산 가능한 값 → **당대에는 관측 불가능**.
  따라서 "7%가 정점을 알렸다"는 사후 구성물이다.

→ **차트는 단일 숫자를 제시하지 않고 D1·D5 두 선을 강제 병기한다.** 이것이 이 레이어의 존재 이유다.

## 3-1. 논지 정량 주장 검증 결과 (에이전트 조사, 요약)

| 주장 | 실제 | 판정 |
|---|---|---|
| 철도 투자 = UK GDP 7% | Mitchell 추계 피크 **6.7%**(1847) | 과장 |
| 철도주 +100% → −70%, 10년 | Campbell&Turner **+101.7% → −66.7%, 4.7년** | 부분 오류 |
| BoE 6% 인상이 철도 버블 붕괴 트리거 | 6% 도달 1847-09, 주가 피크 **1845-08** (25개월 선행) | **인과 역전** |
| 닷컴 IT 지출 = GDP 7% | BEA 투자 기준 4.40%, 상무부 IT산업 부가가치 8.3% | **7%는 어느 공식 정의도 아님** |
| Fed 4.5%→6.5% | 실제 **4.75%→6.50%**, NASDAQ 피크가 최종 인상보다 **2개월 선행** | 부분 오류 + 인과 역전 |
| AI 부채 $150B/$244B | "AI 관련"이 공식 택소노미에 없음, 유통치 $121B~$570B로 제각각 | **재현 불가** |
| S&P 내 AI 20% | 바스켓 정의에 따라 **17.5%~36.0%** | 정의 의존 |

**데블스 애드버킷**: Campbell & Turner 원저자의 결론은 "철도주는 버블이 아니었다"이다.
정량 주장 5개 중 3개가 전부 더 극적인 쪽으로 반올림돼 있다 — 서사 편향의 지표다.

---

## 4. 두 표면 (엄격 분리)

### 4-A. 통계 카테고리 (발행·서술·권위원천 필수)

전제: **닷컴 대응 계열이 없으면 넣지 않는다.**

| # | chart_id | category | 내용 | 원천 | 닷컴 |
|---|---|---|---|---|---|
| **S1** | `investment_share_of_gdp` | economy | D1·D5 2개 선 + 민감도 caveat | `GDP, Y034RC1Q027SBEA, Y001RC1Q027SBEA` (FRED, 무키) | ✅ 1947~ |
| S2 | `software_and_rnd_investment` | economy | D5 내부 분해 — "AI 아닌 것"을 보이게 함 | `B985RC1Q027SBEA, Y006RC1Q027SBEA` | ✅ |
| S3 | `corporate_bond_issuance` | credit | 비금융기업 회사채 잔액·순발행 | Z.1 `FL103163005.Q`, `FA103163005.A` (**이미 받는 zip**) | ✅ |
| S4 | `structures_buildout` | economy | 컴퓨터·전자 제조업 구조물 + 전력·통신 구조물 | Census C30 `privtime.xlsx` (무키·CC0) | ✅ 1993-01~ |
| ~~S5~~ | ~~`datacenter_construction`~~ | — | 데이터센터 건설 | Census C30 | ❌ 2014-01~ → **S4 caveat로만 언급** |

새 중분류(`buildout`)는 만들지 않는다 — `dashboard.js` MID_CATEGORIES·필터배열·테스트 문자열
3곳 동기화 검증이 없어 오탈자 시 영구 은닉된다. 차트 3개 이상 쌓인 뒤 별건.

### 4-B. 예측 레이어 (해소가능 질문)

현재 병목은 데이터가 아니라 **해소 표본**(원장 9건 / P3 게이트 50건)이다. 논지의 실질 기여는 여기다.

| # | question_id | 판정 원천 | domain |
|---|---|---|---|
| **Q1** | `hyperscaler-fcf-negative-2026` | SEC companyfacts CIK0001018724, **태그명 고정** | earnings |
| Q2 | `oracle-fcf-negative-fy2027` | CIK0001341439 | earnings |
| **Q3** | `ai-investment-gdp-share-2026q4` | BEA NIPA T5.3.5 L10+L16 ÷ T1.1.5 L1, **advance 빈티지 고정** | macro |
| **Q4** | `fedfunds-upper-550-2027h1` (+짝질문 `-hold-2026ye`) | FOMC 성명 | macro |
| Q5 | `hyperscaler-registered-debt-2026h2` | EX-FILING FEES `ffd:TtlOfferingAmt`, **CIK 5개 동결** | corporate-event |
| Q6 | `server-useful-life-shortening-2027` | 10-K/10-Q 전문검색 (XBRL 탐지 불가) | corporate-event |
| Q7 | `sox-ndx-relative-strength-2026ye` | FRED NASDAQSOX ÷ NASDAQ100 | market-regime |

**등록하지 않는 질문**: 집중도 임계(무료·재배포가능 판정원천 없음), 토큰/ROI(공식 측정 부재),
전력 임계(정의 분쟁 확실). 신규 driver 태그: `ai-financing`.

---

## 5. 리스크

- **R1 키드 API 차단** (§1-3) — 무키 벌크만 사용. 우회하려면 `sanitized_uri` 이식이 별도 승인 사안.
- **R2 라이선스** — FRED는 퍼블릭도메인 아님(`SP500`=S&P DJI, `NASDAQCOM`=Nasdaq OMX 제한).
  BEA/BLS/Fed/Census 원천만 안전. 재배포 금지: Nasdaq 비중파일·SSGA·PJM·ICE BofA·FINRA margin.
- **R3 정의 취약성** — 같은 분기가 정의만 바꾸면 2.45%~9.00%. → 민감도 병기 강제, 바스켓 동결.
- **R4 빈티지** — BEA는 advance→second→third→연례→포괄개정. 임계 질문은 **최초 공표 빈티지 고정** 문구 필수.
- **R5 look-ahead 금지** — "7% 임계"는 사후 구성물 + n=1 + 2020Q2 위양성. **신호로 쓰지 않는다**(base rate 참조만).
- **R6 불변성** — 질문 판정기준은 첫 예측 후 변경 불가 → 태그명·라인번호·CIK를 **등록 전에** 확정.
- **R7 테스트 하드커플링** — `test_statistics_lab.py` `baseline` dict(미등록 시 KeyError),
  chart 개수 assert **3곳**(`:453`==32, `:641`==22, `:703`==22), `website_data_lineage_v1.yaml`
  `statistics.consumers` 정확일치, `current_conclusions` 누락 시 `missing_conclusions`.
- **R8 예산** — `_site/statistics.json` 84,927/120,000 B. 차트당 2.5~3.5KB → **한 번에 5차트 이하**.
- **R9 계약↔코드 이중관리** — `statistics_lab_v1.yaml`은 런타임 미파싱, 이미 5건 불일치
  (SP500·CBBTCUSD·NASDAQSOX·SPASTT01KRM661N·HOUST). 신규 배치에서 같이 정정.

---

## 6. 단계별 이행

| Phase | 내용 | 신규 온보딩 | 예상 |
|---|---|---|---|
| **0** | **S1 차트** — FRED 3시리즈 추가 + 차트 + 계약·계보·테스트 갱신 | **없음** | 반나절 |
| 1 | Q1·Q3·Q4(+짝)·Q7 질문 등록 | 없음 (코드 0줄) | 반나절 |
| 2 | S3 회사채 — `_parse_z1` 2줄 (기존 영수증 재사용) | 없음 | 반나절 |
| 3 | SEC 파생비율(capex/OCF·FCF·리스부채) → `ai_capital_cycle` 참고 레인 | 없음 | 1~2일 |
| 4 | S4 Census C30 collector | 신규 collector (정책 변경 불요) | 2~3일 |
| 5 | 발행사별 채권 발행(`ffd:TtlOfferingAmt`) → Q5 자동 판정 | 신규 파이프라인 | 3~5일 |
| 6 | BTOS AI 채택률 → base rate 레인 (통계 랩 금지) | 신규 fetch | 1~2일 |

**하지 않을 것**: 철도 era 승격 · 시총가중 집중도 발행 · FINRA margin · Nasdaq 비중파일 ·
SSGA 재배포 · Cloudflare Radar · OpenRouter · Stooq(봇체크 우회 금지) ·
대용량 벌크(FSDS/EIA-930/NipaDataQ)의 영수증 원장 적재 · BEA Digital Economy(폐지됨).

---

## 7. 사용자 결정 필요

- **D-1**: Phase 0의 BEA 취득 경로 — (a) 기존 33시리즈와 동일한 fredgraph(권고, 코드 최소),
  (b) 원생산자 `apps.bea.gov/national/Release/TXT/NipaDataQ.txt`(35MB, 저장소 팽창 R8·E11).
  `reports/md/bank_credit_layer_contract_260805.md` §4.1이 "신규 자동수집은 원생산자 사용"을
  명시하므로 (a)를 택할 경우 `docs/DECISIONS.md`에 유예 사유를 기록해야 한다.
- **D-2**: Phase 1 질문 tier 배분 — Q4는 저확률(현 목표범위 3.50~3.75%, +175~200bp 필요)이라
  `lite`로 두되, 정보량 있는 짝질문을 함께 등록할지.
