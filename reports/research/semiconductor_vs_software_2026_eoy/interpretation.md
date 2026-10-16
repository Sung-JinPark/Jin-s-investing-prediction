# 반도체 vs 소프트웨어: 원문에 근거한 상대 판단

기준시각은 **2026-10-12 10:38:50 KST**, 가격 기준은 미국 **10월 9일 확정 종가**, 지평은 **12월 31일**이다. SOXX와 IGV를 비교한다. 이 문서는 기업 공시·기관 견해를 현재 판단에 연결하는 연구 입력이며, 종목별 실적을 ETF 이익이나 학습된 연말 승률로 대체하지 않는다. 수치와 날짜는 [relative_evidence.json](relative_evidence.json)에 보존했다. 앞선 연구의 09:16:14 KST 기준 자료와 가정을 수정하지 않았다.

**현재 실적·다음 분기 매출의 가시성은 반도체, 최근 가격 강세는 소프트웨어에 유리하다. 연말 상대수익의 승자는 검증되지 않았다.** 기존 시나리오의 반도체 우위는 가정 안에서만 성립하고, 실제 가격 자료로 학습한 모형은 최근 소프트웨어 강세를 반영하지만 표본 밖 성능이 단순 기준보다 나빴다. 이 불일치를 감추거나 실패한 모형을 평균내어 정밀 승률로 바꾸지 않는다. 반도체는 높은 가격 기대·설비투자 사이클·수출규제에 노출되고, 소프트웨어의 보안·데이터·AI 구현 분야에는 이미 실제 계약과 현금 창출을 확인할 수 있다.

## 실제 비교 대상과 가격에 반영된 기대

기존 발행사 자료의 SOXX 상위 5개는 AMD·Intel·Micron·NVIDIA·Broadcom, 합계 40.22%다. IGV 상위 5개는 Palo Alto·Palantir·CrowdStrike·Microsoft·Oracle, 합계 42.94%다. SOXX를 NVIDIA 단독, IGV를 투자비 없는 기존 SaaS 단독으로 해석하면 비교가 틀어진다. 보유종목 수가 많아도 상위 집중도와 공유 AI 수요·금리 노출 때문에 독립 위험이 충분히 분산됐다고 단정할 수 없다. [SOXX](https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf), [IGV](https://www.ishares.com/us/products/239771/ishares-north-american-techsoftware-etf)

동일 발행사·동일 10월 8일 표기의 P/E는 SOXX 51.42, IGV 36.83이다. 분모는 **각 기업의 최근 확정 회계연도 EPS이며 음수 P/E를 제외**한다. TTM·선행 이익·정상화 이익이 아니다. 양쪽의 서로 다른 회계기간과 적자 기업 제외 효과가 있으므로 이 숫자만으로 IGV가 28% 싸다거나 SOXX가 과대평가됐다는 결론을 만들 수 없다. 공통 분모를 확보하기 전에는 이익수익률 차이·PEG·ETF 단위 DCF를 정밀 가치 산출치로 제시하지 않는다.

9월 30일 NAV 총수익의 YTD는 SOXX +89.02%, IGV +0.68%; 3분기는 각각 -11.26%, +17.46%; 9월 한 달은 +11.23%, -3.38%다. 연초부터의 반도체 강세, 여름 소프트웨어 회복, 9월 반도체 재강세가 함께 존재한다. 그래서 1개월 모멘텀·3개월 반전·YTD 과열을 한 방향 신호로 합칠 수 없다. 10월 9일 가격과 9월 30일 수익률은 서로 다른 기준일이며, 남은 기간 수익률에 비례 환산하지 않는다. 이러한 동적 발행사 페이지는 데이터 기준일을 확인했지만 과거 게시시각·배포 보관본이 없어 완전한 publication-vintage 증명은 제한된다.

## 실제 가격·머신러닝 결과와 종합 판단

[quantitative_ml.json](quantitative_ml.json)의 실제 조정가격 기록은2008년1월2일부터2026년10월9일까지4,723개 공통 거래일이다. 10월9일까지 최근57거래일 총수익은 SOXX+1.280%, IGV+22.707%, 최근21거래일은+8.182%, +11.334%다. 이는 최신 가격 흐름에서는 **소프트웨어가 우세**함을 보여준다. 위의9월30일 NAV 수익률과는 측정 기간·시장가격/NAV·조정 데이터 기준이 다르다. 57거래일 구간의 SOXX/IGV 총수익 배율 변화-17.462%와 산술 수익률 차이-21.427%p는 다른 값이다.

연말까지 남은57거래일을 target으로 학습한 Ridge·로지스틱 회귀·랜덤포리스트를 시간순 expanding window로 평가했다. 일별 기점3,280개는57일 label이 중첩돼 독립 표본이 아니다. 겹치지 않는 기점은58개이며 이것도 같은 시장 국면에 노출돼 완전한 독립을 보장하지 않는다. 학습 label은 각 평가 시작일보다 먼저 끝나도록 purge하고, scaler는 학습 구간에만 맞췄다.

| 57거래일 평가 | 단순 기준 | 학습 모형 | 판단 |
|---|---:|---:|---|
| 평균 절대 오차, 상대 로그 수익 | expanding mean0.07566 | Ridge0.08507 | 더 나쁨 |
| Brier, SOXX 상대우위 사건 | expanding 빈도0.25279 | 로지스틱0.31032 | 더 나쁨 |
| Brier, SOXX 상대우위 사건 | expanding 빈도0.25279 | 랜덤포리스트0.27584 | 더 나쁨 |

위 오차는 확률과 수익의 단위가 다르므로 서로 직접 비교하지 않는다. 상수0.5 확률의 Brier0.25와 상대 로그수익0의 MAE0.07541도 학습 모형보다 좋았다. 현재 모형의 방향은 소프트웨어를 가리키지만 **예측력이 확인되지 않은 탐색 출력**이다. 따라서 현재 출력으로 소프트웨어를 검증된 연말 승자로 정하거나 기존 시나리오를 공식 교정하지 않는다. 원래 거래일별 정보 전달·가격 조정 vintage가 없어 엄격한 point-in-time 게이트도 차단했다.

자료가 정당화하는 결론은 세 층으로 나뉜다. 사업 수요의 원문 근거는 반도체에 강하고, 현재 가격 모멘텀은 소프트웨어에 강하며, 연말 가격의 확률 우위는 검증되지 않았다. 기대 변화와 평가배수의 반증 경계를 확인하는 의사결정 자료로 사용한다.

## 반도체: 매출 가시성이 유리한 이유와 반증

| 경로 | 실제 확인 | 상대 판단 | 반증·가격 위험 |
|---|---|---|---|
| AI 연산·네트워크 | NVIDIA FY27Q2 매출96.221bn, 다음 분기108bn±2%; Broadcom AI반도체16.7bn, 다음 분기21.7bn; AMD Q2데이터센터+107% | 대규모 AI 예산이 공급자 매출로 이미 연결됨 | 고객 집중·공급 병목·제품 전환·맞춤형 칩 경쟁·수출규제. 높은 매출 성장도 기대를 넘지 못하면 주가 하락 가능 |
| 메모리 | Micron FY26Q4 매출54.229bn, 다음 분기61.5bn±1.5bn; 영업CF43.97bn | AI 시스템의 메모리 수요와 현금 창출 확인 | 현재 86.8% GAAP gross margin은 정상 장기 수준으로 고정하지 않음. HBM-only 매출과 일반 DRAM/NAND를 별도 확보해야 함 |
| 장비·패키징 | AMAT FY26Q3 매출+25%, 다음 분기10.25bn±0.5bn; Lam June quarter6.722bn, 다음8.10bn±0.4bn | 설치·생산 확대가 장비 수요로 연결됨 | AMAT 중국 매출28%, Lam26%; 수출규제와 고객 투자 지연. 장비 설치·매출과 현금 회수 시차 |
| 비AI 수요 | TI 산업·데이터센터·자동차 중심 Q2매출+23%; AMD게임-31% | 산업·자동차 회복 근거는 있으나 전면 회복 아님 | 소비·게임·산업 수요의 차이를 AI 수요로 덮으면 경기 민감 위험을 과소평가 |

출처: [NVIDIA](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027), [Broadcom SEC](https://www.sec.gov/Archives/edgar/data/1730168/000173016826000076/avgo-08022026x8kxex99.htm), [AMD](https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results), [Micron SEC](https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm), [AMAT](https://ir.appliedmaterials.com/news-releases/news-release-details/applied-materials-announces-third-quarter-2026-results), [Lam](https://investor.lamresearch.com/2026-07-29-Lam-Research-Corporation-Reports-Financial-Results-for-the-Quarter-Ended-June-28,-2026), [TI](https://www.ti.com/about-ti/newsroom/news-releases/2026/2026-07-22-ti-reports-second-quarter-2026-financial-results-and-shareholder-returns.html).

반도체 이익 비교도 정상화가 필요하다. AMD의 전년 비교에는 MI308 수출규제 관련 재고비용800m이 포함돼 있다. Intel은 Q2 GAAP 영업이익1.796bn이지만 순손실11.033bn에 escrow 주식의 비영업 평가손실12.529bn이 포함된다. Intel 조정 FCF-8.419bn에는 대규모 SCIP 파트너 정산도 반영된다. 이를 순수 영업 손실이나 GPU 산업 현금흐름으로 부르면 틀린 설명이다. [Intel](https://www.intc.com/news-events/press-releases/detail/1776/intel-reports-second-quarter-2026-financial-results)

## 소프트웨어: 실재하는 수익화와 ETF를 단순화할 수 없는 이유

| 경로 | 실제 확인 | 상대 판단 | 반증·가격 위험 |
|---|---|---|---|
| 보안 | CrowdStrike ARR+25%, 분기FCF377.4m; Palo Alto 매출+34%·NGSARR+63% | AI 확대와 방어적 보안 예산의 수요 확인 | 인수·기저·주식보상·무형자산 상각 분리. PANW GAAP 영업172m vs전년497m; FY27 NGSARR성장22–23% 전망 |
| 데이터·구현 | Snowflake product revenue+37%, FY27 전망6.070bn으로 상향; Palantir 매출+93%, GAAP 영업margin47% | 애플리케이션 수익화가 미래의 약속에만 머물지 않음 | 소비 최적화·대형 고객·정부 계약·높은 기대. Snowflake GAAP 영업손실263m과 SBC 관련456m 병존 |
| 워크플로·기존 SaaS | ServiceNow cRPO+21%, AIACV1bn초과; Salesforce cRPO+14%, AgentforceARR1.5bn초과; Adobe매출+13% | 실제 계약·기존 플랫폼에 AI를 붙이는 경로 확인 | ACV·ARR은 분기 매출 아님. CRM Agentforce 정의 확대와 인수 기여; 사용량·성과형 가격의 기존 좌석 매출 잠식은 별도 검증 필요 |
| 클라우드 플랫폼 | Oracle IaaS+121% vsSaaS+10%; Microsoft Azure+43% | 인프라와 앱 성장 차이. 플랫폼형 소프트웨어에는 반도체 수요와 공통 노출 | Oracle 분기FCF-5bn·ATM주식20bn발행. Microsoft 투자·lease 재분류. IGV를 무설비투자 자산으로 부를 수 없음 |

출처: [CrowdStrike](https://ir.crowdstrike.com/news-releases/news-release-details/crowdstrike-reports-second-quarter-fiscal-year-2027-financial), [Palo Alto](https://investors.paloaltonetworks.com/news-releases/news-release-details/palo-alto-networks-reports-fiscal-fourth-quarter-and-fiscal-10), [Snowflake](https://investors.snowflake.com/news/news-details/2026/Snowflake-Reports-Financial-Results-for-the-Second-Quarter-of-Fiscal-2027/default.aspx), [Palantir SEC](https://www.sec.gov/Archives/edgar/data/1321655/000132165526000039/a2026q2ex991pressrelease.htm), [ServiceNow](https://investor.servicenow.com/news/news-details/2026/ServiceNow-Reports-Second-Quarter-2026-Financial-Results/default.aspx), [Salesforce](https://investor.salesforce.com/news/news-details/2026/Salesforce-Delivers-Record-Second-Quarter-Fiscal-2027-Results/default.aspx), [Adobe SEC](https://www.sec.gov/Archives/edgar/data/796343/000079634326000147/adbeex991q326.htm), [Oracle](https://www.oracle.com/news/announcement/q1fy27-earnings-release-2026-09-10/), [Microsoft](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast).

**현금흐름의 이름도 같지 않다.** TI FCF는 CFO-capex에 CHIPS 보조금을 더하고, Micron은 순투자와 조정 FCF를 쓴다. ServiceNow 분기 FCF634m은 CFO587-capex114+인수 관련비용161m이다. Palantir 조정 FCF는 SBC 관련 급여세를 더한다. 회사의 조정 FCF를 동일한 소유주 현금흐름으로 합산하거나 비교 ETF에 가중 평균하지 않는다. SBC는 현금 유출이 아니어도 주당 지분 희석·이를 상쇄하는 매입 비용을 야기할 수 있으므로 GAAP와 발행주식 수를 함께 봐야 한다. 단순 `CFO-capex-SBC`도 보수적 비용 대용치일 뿐 자동으로 정확한 owner earnings가 되는 것은 아니다.

## 10월 시황과 금리 조건

[Fed 9월 16일 성명](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm)은 정책금리를25bp 인상한3.75–4.00% 목표 범위를 제시했다. [BLS 10월 2일 발표](https://www.bls.gov/news.release/archives/empsit_10022026.htm)의 9월 고용은+29,000명·실업률4.2%, 7·8월 합산 고용은60,000명 하향 수정됐다. 둔화하는 고용과 높은 할인율이 함께 존재하므로 경기 회복·금리 하락을 동시에 확정 가정하면 안 된다. 이 자료는 당시 발표 vintage이며 이후 수정은 사용하지 않는다.

[Goldman Sachs 10월 2일 자료](https://www.goldmansachs.com/insights/the-markets/ai-is-becoming-a-stock-pickers-market)는 9월30일 대화다. AI 투자 관심이 구현·데이터·보안으로 확장되고 core SaaS의 제품 적합성·가격은 여전히 검증 중이라고 평가한다. 이 기관 견해는 소프트웨어 반론을 뒷받침하지만 수익률 확률은 아니다. 대화의10년물5.25%초과 언급은9월30일 맥락이며10월9일 확정 수익률로 기록하지 않았다. [Fidelity 8월10일 견해](https://institutional.fidelity.com/advisors/insights/series/fidelity-market-signals-weekly/ais-next-test-delivering-results)는 지출액보다 마진·현금흐름·투자수익을 구별하는 단계라고 설명한다. 같은 리포트의 재인용을 새 독립 증거로 세지 않는다.

| 조건 | 상대 논리에 주는 영향 | 확인할 자료 |
|---|---|---|
| AI 공급자 전망 상향·투자 지속·장기금리 안정 | 반도체 실적 우위 유지 가능 | 실제 인식 매출·다음 분기 전망·총투자/lease·제품 전환 |
| AI 데이터·보안 유기 성장 가속·현금 전환 개선·금리 하락 | 소프트웨어 평가배수/수익 전망 개선 가능 | 인수 제외ARR/cRPO·GAAP마진·희석 주식 수·소비량 |
| 장기금리 상승·수익 기대 미달 | 두 섹터 모두 압박. 누가 더 민감한지는 현금 지급 시점과 성장·배수에 달림 | 역사적 추정/DCF가 필요하며 소프트웨어 자동 방어력 가정 금지 |
| AI 투자 지연·일반경기 급락 | 반도체 수요·공급 사이클 위험 증가. IGV 플랫폼에도 같은 투자·고객 위험 존재 | 고객 주문 취소·재고·공사/전력 지연·RPO상대방/인식 시점 |

## 수학적 해석: 작은 우위가 뒤집히는 경계

가격 수익을 이익과 평가배수로 분해하면 `R = (1+g)(1+m)-1+d-f·T/365`다. `g`는 해당 지평에서 시장이 가격에 반영할 이익 능력의 변화, `m`은 평가배수 변화, `d`는 지급 가정 배당, `f`는 연간 보수다. 여기의 g·m은 현재 확보한 기업 성장률에서 자동으로 계산된 ETF NTM EPS가 아니라 앞선 보고서에서 보존한 연구 가정이다.

가정 가중치(상승0.30·기준0.45·하락0.25)를 유지하면 SOXX4.60596%, IGV2.93659%, 차이1.66937%p다. 소프트웨어가 모든 시나리오에서 같은 폭으로 평가배수 변화를 개선한다고 가정하면 `m_IGV,j → m_IGV,j+δ`, `ΔE[R_IGV]=δ·Σw_j(1+g_IGV,j)`다. 분모가1.021이므로 **δ약1.635%p만으로 기존 차이가 사라진다**. 이것은 순위 전환 경계 계산이지 IGV가 그렇게 재평가될 확률이 아니다. 동일하게 양쪽 이익·배수 가정과 가중치를 바꿔 순위의 민감도를 확인해야 한다.

DCF의 금리 민감도는 `D = -∂lnV/∂r`, 1차 가격 변화는 `ΔlnV ≈ -D·Δr`로 설명할 수 있다. 하지만 두 ETF의 실제 공통 정상화 현금흐름·위험 프리미엄·duration을 확보하지 못했으므로 임의 D를 측정 사실로 사용하지 않는다. 금리 스트레스의 계수는 명시적 가정으로, 역사적 회귀 계수는 추정 구간·불확실성·시장 베타와 함께 표시해야 한다.

현재 기업 표본은 서로 다른 최신 분기이며 하나의 공통 AI 투자 사이클에 노출된다. 이를 독립 학습 관측으로 넣은 뒤 승률을 낼 수 없다. 실제 역사적 가격을 쓴 머신러닝은 별도 시간순 검증했고 단순 기준을 넘지 못했다. 현재 기업 수치만으로 이 실패를 보정하거나 섹터 승률로 공식 승격하지 않는다. 내부 Brier·실적 이벤트 적중률도 이런 연말 ETF 상대수익 예측력을 검증하지 않는다. 200,000회 Monte Carlo에서 나온83.19%는 선택한 시나리오·분포·상관 가정 안의 반도체 우위 빈도다. 현실의 검증된 승률이나 샘플 수로 높아진 시장 예측 신뢰도가 아니다.

## 연말 촉매와 최종 반증 조건

NVIDIA의8월26일 콜을 담은 회사 호스팅 [기록](https://investor.nvidia.com/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf)은 다음 실적 콜11월17일·GTC Berlin10월21일을 예고한다. 이 corrected PDF의 게시·수정시각은 미확인이다. 동적 공식 달력에는 [Lam10월21일](https://investor.lamresearch.com/events?item=95), [Microsoft10월28일](https://www.microsoft.com/en-us/investor/default?l=5), [Oracle12월14일](https://investor.oracle.com/faq/default.aspx)이 표기돼 있다. 모든 일정 자료의 원 게시시각을 확보하지 못했으므로 일정 참고로만 사용하며 결과를 미래 정보로 가져오지 않는다.

반도체의 시나리오 우위가 유지되려면 실제 AI·메모리·장비 매출이 공시 전망에 부합하고, 다음 분기 수요도 유지되며, 연말 평가배수 하락이 이익 변화보다 크지 않아야 한다. 소프트웨어의 실제 최근 강세가 연말까지 이어질 조건은 보안·데이터·구현 기업의 인수 제외 계약 성장과 현금 전환이 기대를 넘고, 기존 SaaS의 가격·잠식 우려가 완화되며, 상대 평가배수가 개선되는 경우다. 반도체의 이익 전망 하향이나 소프트웨어의 약1.64%p 추가 배수 변화라는 작은 가정 변화만으로도 기존 시나리오의 우위는 사라진다. 따라서 최종 결론은 **실적 가시성은 반도체, 최근 가격은 소프트웨어, 연말 승자는 미검증**이다. 실패한 ML 출력과 가정 분포를 합쳐 확정 순위나 정밀 승률을 만들지 않는다.
