/* Record presentation only. Never changes the registered questions or immutable ledgers. */
(function(root){
  'use strict';
  let data={};
  const unresolved=new Map();
  const repo='https://github.com/sung-jinpark/Jin-s-investing-prediction/blob/main/';
  const titles={
    'nvda-dc-beat-2026aug':'엔비디아 8/26 실적 — 데이터센터 매출이 시장 예상보다 5% 이상 높을까?',
    'mu-margin-qoq-next':'마이크론 다음 실적 — 매출총이익률이 직전 분기보다 낮아질까?',
    'vix-25-90d':'예측일부터 90일 안에 시장 불안 지수가 종가 25를 넘을까?',
    'fomc-2026-10-28-hike':'10/28 미국 금리 결정 — 0.25%포인트 이상 인상할까?',
    'openai-s1-2027h1':'오픈에이아이 — 2027-06-30까지 공개 상장 서류를 제출할까?',
    'soxx-eoy-down15':'미국 반도체 상장지수펀드 — 연말 종가가 기준가보다 15% 이상 낮을까?',
    'fomc-2026-07-29-hike':'7/29 미국 금리 결정 — 0.25%포인트 이상 인상할까?',
    'cpi-jun2026-accel':'6월 미국 소비자물가 — 전년 대비 상승률이 5월의 4.2%를 넘을까?',
    'nfp-jul2026-below100k':'7월 미국 신규 고용 — 증가 인원이 10만 명 미만일까?',
    'nvda-beat-any-2026aug':'엔비디아 8/26 실적 — 총매출이 시장 예상보다 높을까?',
    'mu-margin-qoq-fq1fy27':'마이크론 2027 회계연도 1분기 — 매출총이익률이 직전 분기보다 낮아질까?',
    'openai-public-flip-2026':'오픈에이아이 — 2026-12-31까지 상장 서류를 공개할까?',
    'spx-up-2026-07-08':'미국 대형주 500개 지수 — 7/8 종가가 전날보다 오를까?',
    'soxx-up-2026-07-08':'미국 반도체 상장지수펀드 — 7/8 종가가 전날보다 오를까?',
    'btc-alt-mania-90d':'예측일부터 90일 안에 비트코인 신고가와 다른 가상자산 시가총액 50% 증가가 모두 나타날까?',
    'nasdaq-ath-eoy-2026':'나스닥 종합 — 연말까지 종가가 고정 기준 최고점 27,093.90을 넘을까?',
    'nasdaq-corr10-augoct-2026':'나스닥 종합 — 8~10월에 종가가 고정 기준 최고점보다 10% 이상 낮아질까?',
    'nasdaq-eoy-above-jul9-2026':'나스닥 종합 — 연말 종가가 7/9 종가 26,206.89보다 높을까?',
    'amd-eps-beat-2026q2':'에이엠디 2026년 2분기 — 조정 주당순이익이 시장 예상보다 높을까?',
    'avgo-eps-beat-fq3-2026':'브로드컴 2026 회계연도 3분기 — 조정 주당순이익이 시장 예상보다 높을까?',
    'orcl-eps-beat-fq1-2027':'오라클 2027 회계연도 1분기 — 조정 주당순이익이 시장 예상보다 높을까?',
    'adbe-eps-beat-fq3-2026':'어도비 2026 회계연도 3분기 — 조정 주당순이익이 시장 예상보다 높을까?',
    'asml-eps-beat-2026q3':'에이에스엠엘 2026년 3분기 — 주당순이익이 시장 예상보다 높을까?',
    'tsmc-eps-beat-2026q3':'티에스엠씨 2026년 3분기 — 주당순이익이 시장 예상보다 높을까?',
    'msft-eps-beat-fy27q1':'마이크로소프트 2027 회계연도 1분기 — 조정 주당순이익이 시장 예상보다 높을까?',
    'googl-eps-beat-2026q3':'알파벳 2026년 3분기 — 주당순이익이 시장 예상보다 높을까?',
    'meta-eps-beat-2026q3':'메타 2026년 3분기 — 주당순이익이 시장 예상보다 높을까?',
    'amzn-eps-beat-2026q3':'아마존 2026년 3분기 — 주당순이익이 시장 예상보다 높을까?',
    'aapl-eps-beat-fq4-2026':'애플 2026 회계연도 4분기 — 주당순이익이 시장 예상보다 높을까?',
    'cpi-jul2026-reaccel':'7월 미국 소비자물가 — 전년 대비 상승률이 3.8% 이상일까?',
    'nfp-aug2026-below100k':'8월 미국 신규 고용 — 증가 인원이 10만 명 미만일까?',
    'nfp-oct2026-below100k':'10월 미국 신규 고용 — 증가 인원이 10만 명 미만일까?',
    'cpi-oct2026-reaccel':'10월 미국 소비자물가 — 전년 대비 상승률이 9월보다 높아질까?',
    'nvda-dc-beat-2026nov':'엔비디아 2027 회계연도 3분기 — 데이터센터 매출이 시장 예상보다 5% 이상 높을까?',
    'nfp-nov2026-below100k':'11월 미국 신규 고용 — 증가 인원이 10만 명 미만일까?',
    'fomc-2026-12-09-hike':'12/9 미국 금리 결정 — 0.25%포인트 이상 인상할까?',
    'gdp-q3adv-2026-beat':'미국 3분기 경제성장률 — 첫 발표가 시장 예상보다 높을까?',
    'santa-week-2026':'미국 대형주 500개 지수 — 연말 마지막 5거래일 동안 오를까?',
    'amzn-fcf-negative-fy2026':'아마존 2026년 — 설비투자를 뺀 영업 현금흐름이 마이너스일까?',
    'ai-investment-gdp-share-2026q4':'2026년 4분기 — 설비·지식재산 투자가 국내총생산의 8.5% 이상일까?',
    'fedfunds-upper-550-2027h1':'미국 정책금리 상단 — 2027-06-30까지 5.50%에 도달할까?',
    'fedfunds-upper-hold-2026ye':'미국 정책금리 상단 — 2026년 말에 3.75% 이하일까?',
    'sox-ndx-relative-strength-2026ye':'미국 반도체 지수 — 2026년 말까지 나스닥100 대비 상대 성과가 5% 이상 낮아질까?',
    'fomc-2026-09-16-dissent':'2026-09-16 미국 금리 결정 — 성명의 지정 문구에 반대표가 1명 이상 기록될까?',
    'fomc-sep-2026ye-dot-above-375':'9월 연준 금리 전망 — 2026년 말 전망 중간값이 3.75%를 넘을까?',
    'fedfunds-upper-425-2026-12-09':'2026-12-09 미국 금리 결정 후 — 정책금리 상단이 4.25% 이상일까? (0.25%포인트 인상 2회에 해당)',
    'fomc-2027-01-27-hike':'2027-01-27 미국 금리 결정 — 금리를 올릴까?',
    'cpi-aug2026-core-below-24':'8월 미국 근원 소비자물가 — 전년 대비 상승률이 2.4% 이하일까?',
    'nfp-sep2026-negative':'9월 미국 신규 고용 — 첫 발표에서 취업자가 줄어들까?',
    'cpi-sep2026-core-above-27':'9월 미국 근원 소비자물가 — 전년 대비 상승률이 2.7% 이상일까?',
    'unemployment-44-nov2026':'11월 미국 실업률 — 4.4% 이상일까?',
    'cpi-nov2026-headline-below-28':'11월 미국 전체 소비자물가 — 전년 대비 상승률이 2.8% 미만일까?',
    'ecb-depo-300-2026-12-28':'유럽중앙은행 예금금리 — 2026년 말에 3.00% 이상일까?',
    'vix-30-touch-by-2026-11-30':'시장 불안 지수 — 2026-11-30까지 종가 30 이상인 날이 있을까?',
    'vix-13-touch-by-2026-12-18':'시장 불안 지수 — 2026-12-18까지 종가 13 이하인 날이 있을까?',
    'spx-drawdown-7pct-by-2026-11-30':'미국 대형주 500개 지수 — 2026-11-30까지 종가가 최고점보다 7% 이상 낮아질까?',
    'vix-weekly-spike-50pct-by-2026-12-18':'시장 불안 지수 — 2026-12-18까지 한 주 동안 50% 이상 오를까?',
    'xenergy-ipo-priced-by-2026-09-30':'엑스에너지 — 2026-09-30까지 공모가를 확정하고 거래를 시작할까?',
    'cerebras-ipo-priced-by-2027-01-31':'세레브라스 — 2027-01-31까지 공모가를 확정하고 거래를 시작할까?',
    'ai-ipo-2b-plus-by-2026-11-30':'인공지능 기업 — 기업공개로 20억 달러 이상 조달하는 사례가 나올까?',
    'boj-hike-2026-09-17':'일본은행 2026-09-17 회의 — 정책금리를 올릴까?',
    'nasdaq-drawdown-15pct-by-2027-03-31':'나스닥100 — 2027-03-31까지 종가가 최고점보다 15% 이상 낮아질까?',
    'hy-oas-500bp-by-2027-01-31':'미국 저신용 회사채 — 국채 대비 가산금리가 2027-01-31까지 5.00%포인트 이상일까?',
    'fomc-2026-09-16-nonunanimous':'2026-09-16 미국 금리 결정 — 통화정책 표결에 반대가 1명 이상일까?',
    'fomc-sep-2027-below-2026':'9월 연준 금리 전망 — 2027년 말 전망 중간값이 2026년 말보다 낮을까?',
    'boj-hike-2026-09-18':'일본은행 2026년 9월 회의 — 09-18 발표에서 정책금리를 올릴까?',
    'hy-oas-500bp-2026q4-2027q1':'미국 저신용 회사채 — 2026-09-10~2027-01-31 가산금리가 5.00%포인트 이상일까?',
    'adbe-eps-surprise-ge4pct-fq4-2026':'어도비 2026 회계연도 4분기 — 조정 주당순이익이 시장 예상보다 4% 이상 높을까?',
    'adbe-eps-above-guide-top-fq4-2026':'어도비 2026 회계연도 4분기 — 조정 주당순이익이 회사 전망 상단을 넘을까?',
    'nvda-rev-surprise-ge6pct-fq3-2027':'엔비디아 2027 회계연도 3분기 — 총매출이 시장 예상보다 6% 이상 높을까?',
    'nvda-rev-miss-fq3-2027':'엔비디아 2027 회계연도 3분기 — 총매출이 시장 예상보다 1% 초과 낮을까?',
    'avgo-eps-surprise-ge5pct-fq4-2026':'브로드컴 2026 회계연도 4분기 — 조정 주당순이익이 시장 예상보다 5% 이상 높을까?',
    'avgo-eps-miss-fq4-2026':'브로드컴 2026 회계연도 4분기 — 조정 주당순이익이 시장 예상보다 1% 초과 낮을까?',
    'nfp-dec2026-below-neg75k':'2026년 12월 미국 신규 고용 — 첫 발표에서 75,000명 이상 줄어들까?',
    'fedfunds-upper-450-2026-12-09':'2026-12-09 미국 금리 결정 후 — 정책금리 상단이 4.50% 이상일까?',
    'vix-40-touch-by-2027-01-15':'시장 불안 지수 — 2026-09-11~2027-01-15 종가 40 이상인 날이 있을까?',
    'vix-above20-40days-by-2027-01-15':'시장 불안 지수 — 2026-09-11~2027-01-15 종가 20 초과인 날이 40거래일 이상일까?',
    't10y2y-100bp-by-2027-01-15':'미국 국채 10년물과 2년물 금리 차 — 2026-09-11~2027-01-15 1.00%포인트 이상일까?',
    'nasdaq-comp-30000-close-2027-01-15':'나스닥 종합 — 2027-01-15 종가가 30,000 이상일까?'
  };
  const phrases=[
    ['Laplace 보정','표본이 적을 때 확률을 0%나 100%로 단정하지 않도록 하는 보정'],
    ['실행 미스','사업 실행 부진'],['가이던스 미스','회사 전망 미달'],['미스매치','기준 불일치'],
    ['컨센서스 C','시장 예상치'],['스냅샷 C','당시 저장한 시장 예상치'],['가이드라인','지침'],['가이드','회사 전망'],

    ['서프라이즈 폭','시장 예상과 실제 결과의 차이'],['상방 서프라이즈','예상보다 높은 결과'],['하방 서프라이즈','예상보다 낮은 결과'],
    ['매파 서프라이즈','예상보다 긴축적인 결정'],['서프라이즈 인상','예상하지 못한 금리 인상'],
    ['매파적','긴축적인'],['매파성','긴축 성향'],['매파 의장','긴축을 선호하는 의장'],['매파로','긴축을 선호하는 인물로'],['매파 블록','긴축 선호 위원들'],['매파 프레임','긴축이 필요하다는 해석'],['매파','긴축 선호'],
    ['비둘기 반대','완화 선호 위원의 반대'],['비둘기 코어','완화를 선호하는 핵심 위원'],['비둘기 전환','완화 방향으로 전환'],['비둘기','완화 선호'],
    ['포워드 가이던스','앞으로의 정책 방향 사전 안내'],['포워드가이던스','앞으로의 정책 방향 사전 안내'],
    ['디레이팅','이익 대비 주가 배수 하락'],['리레이팅','이익 대비 주가 배수 재평가'],
    ['딥 바잉','하락 때 매수'],['딥바잉','하락 때 매수'],['멜트업','투기 수요에 따른 급등'],['셀오프','집중 매도'],
    ['크라우딩','같은 자산에 투자금 집중'],['크레딧','신용시장'],['리드타임','주문 후 공급까지 걸리는 기간'],
    ['피크아웃','정점 통과'],['캐파','생산 능력'],['바인딩 제약','실제 생산을 제한하는 요인'],['바인딩','실제 생산을 제한'],
    ['미드텀','미국 중간선거'],['리밸런싱','투자 비중 재조정'],['백워데이션','단기 예상 변동성이 장기보다 높아진 상태'],
    ['콘탱고','장기 예상 변동성이 단기보다 높은 상태'],['코어','근원'],['노이즈','일시적 잡음'],['스팟가격','현물 가격'],['스팟 가격','현물 가격'],
    ['버퍼','완충 여력'],['리테일','일반 투자자'],['투항','손실을 감수한 대규모 매도'],['블렌드','여러 값을 혼합한'],['블렌디드','확정 실적과 추정 실적을 합친'],
    ['하드 룰','반드시 따르는 기준'],['하드룰','반드시 따르는 기준'],['하드 마감','확정 마감'],['파라미터','계산에 사용하는 설정값'],
    ['오버레이','기본 전망에 추가로 반영한 비교 경로'],['드로우다운','최고점 대비 하락폭'],['모멘텀','최근 흐름'],

    ['Mag 7','미국 대형 기술주 7개'],['Mag7','미국 대형 기술주 7개'],['SK hynix','에스케이하이닉스'],['BBB−','투자적격 중 가장 낮은 신용등급'],
    ['BBB-','투자적격 중 가장 낮은 신용등급'],['V자 회복','급락 뒤 빠른 회복'],['V자','급락 뒤 빠르게 반등하는'],
    ['BLS empsit','미국 노동통계국 고용상황 보고서'],['bls.gov empsit','미국 노동통계국 고용상황 보고서'],['in line','예상치와 비슷한'],

    ['회사 가이던스','회사 전망'],['자사 가이던스','회사가 직접 제시한 전망'],
    ['스냅샷된','기준값으로 저장된'],['스냅샷해','기준값으로 저장해'],['스냅샷 컨센서스','당시 저장한 시장 예상치'],['스냅샷 컨센','당시 저장한 시장 예상치'],
    ['U-3 실업률','공식 실업률'],['first print','최초 발표치'],
    ['(i)','(첫째)'],['(ii)','(둘째)'],['(iii)','(셋째)'],['(a)','(첫째 조건)'],['(b)','(둘째 조건)'],['(c)','(셋째 조건)'],
    ['+60K p','+60천 명'],['+90K p','+90천 명'],

    ['S&P Dow Jones Indices','에스앤피 다우존스 지수회사'],['Federal Reserve','미국 연방준비제도'],
    ['Data Center/Edge','데이터센터·주변기기 사업 분류'],['Data Center','데이터센터'],
    ['Exhibit 99.1','실적 공시 첨부문서'],['Ex-99.2','재무책임자 해설 첨부문서'],
    ['US Inflation Calculator','미국 물가 계산 자료'],['ICE BofA US High Yield Index OAS','미국 저신용 회사채의 옵션 조정 가산금리'],
    ['S&P/거래소','지수회사·거래소'],['S&P 준용','미국 대형주 지수의 사례를 적용'],
    ['|속보−컨센|','속보치와 시장 예상치 차이의 절댓값'],['leisure&hospitality','여가·숙박업'],
    ['12-high','12단 적층'],['a few','소수'],['wedge','회계 기준에 따른 수치 차이'],
    ['cadence','예측 주기'],['due','재검토 필요'],['vol','변동성'],['live','실제 결정 가능'],
    ['soxx-up','미국 반도체 펀드의 당일 상승 질문'],['q2fy26pr','해당 분기의 실적 공시'],
    ['WS-D','별도로 지정한 보조 자료'],['frontmatter','원문의 기본 정보'],

    ['S&P 500','미국 대형주 500개 지수'],['S&P500','미국 대형주 500개 지수'],['S&P','에스앤피'],['P/E','주가수익비율'],
    ['Data Center/Edge','데이터센터·주변기기 사업 분류'],['Data Center','데이터센터'],['market platform','시장별 매출 구분'],
    ['financial funds','금융자금'],['companyfacts','회사별 재무정보'],['advance estimate','첫 속보치'],['second/third/','두 번째·세 번째/'],
    ['Summary of Economic Projections','연준 경제전망 요약'],['Summary','주요 의견 요약'],
    ['Statement on Monetary Policy','통화정책 결정문'],['Employment Situation','고용상황 보고서'],
    ['confidential','비공개'],['public flip','공개 전환'],['public','공개'],['draft','초안'],['filing','공시'],
    ['frontmatter','원문의 기본 정보'],['Commentary','해설'],['earnings page','실적 자료 페이지'],
    ['Stock Trader\'s Almanac','주식시장 계절성 연감'],['ex-2종목','2종목 제외'],['ex-2','2종목 제외'],
    ['US Week Ahead','미국 다음 주 경제 전망'],['Inflation Nowcasting','현재 물가 추정'],
    ['Nowcasting','현재 지표 추정'],['Nowcast','현재 지표 추정'],['advance','속보치'],['consensus','시장 예상치'],
    ['residual seasonality','계절조정 후에도 남은 계절 효과'],['leisure&hospitality','여가·숙박업'],
    ['low-fire','해고가 적은 상태'],['transitory','일시적이라는'],['in-line','예상치와 비슷한'],
    ['financial flow fragility','자금 흐름의 취약성'],['flow fragility','자금 흐름의 취약성'],
    ['Hyperscale','초대형 클라우드 데이터센터'],['ACIE','인공지능 클라우드·산업·기업용 데이터센터'],
    ['Underweight PT','비중 축소 의견과 제시 가격'],['Set the Date','발표일 확정'],
    ['intermeeting','정례회의 사이 임시'],['full session','정상 거래시간'],['MLK','마틴 루서 킹 기념일'],
    ['conventional','범용'],['High-NA','고개구수 차세대 노광장비'],['advanced node','첨단 공정'],
    ['mid-teens','10%대 중반'],['realistic','현실적인'],['confirmed','확정'],['lumpy','시기별 편차가 큰'],
    ['underwriter','상장 주관사'],['net','순'],['setup','시장 여건'],['per','한 단위당'],
    ['median','중간값'],['vote','표결'],['Minutes','의사록'],['Section','조항'],['high','높은'],['Market Data','시장 자료'],['Series H','후기 단계 투자 유치'],['High Yield','저신용 회사채'],
    ['EU State Aid','유럽연합 국가 보조금'],['Library','자료 모음'],['Shares','주식 구조'],['Newsroom','뉴스룸'],
    ['Altcoin Season Index','비트코인 이외 가상자산 상승 확산 지수'],['Fund Manager Survey','펀드매니저 조사'],
    ['Global Fund Manager Survey','전 세계 펀드매니저 조사'],['Stage Analysis','시장 흐름 분석'],
    ['Global','전 세계'],['Semiconductor Index','반도체 지수'],['ICE BofA US High Yield Index OAS','미국 저신용 회사채의 옵션 조정 가산금리'],

    ['general(종합) + devil(데블스 애드버킷) 서브에이전트 2개 병렬','종합 조사와 반대 근거 검토를 두 조사 과정에서 나란히 수행'],
    ['general(출처 ','종합 조사(출처 '],['devil(출처 ','반대 근거 조사(출처 '],
    ['Outside View — base rate','비슷한 과거 사례에서 출발한 확률'],['Outside view','비슷한 과거 사례 검토'],
    ['Outside View','비슷한 과거 사례 검토'],['outside-view','비슷한 과거 사례 검토'],
    ['Inside View — 보정','이번 상황의 근거를 반영한 조정'],['Inside view','이번 상황의 근거 검토'],
    ['Inside View','이번 상황의 근거 검토'],['inside-view','이번 상황의 근거 검토'],
    ['Premortem — 이 예측이 크게 틀렸다면','크게 틀릴 수 있는 이유'],['Premortem — 크게 틀릴 이유 3가지','크게 틀릴 수 있는 이유 3가지'],
    ['Premortem — 틀릴 이유 3가지','틀릴 수 있는 이유 3가지'],['Premortem','틀릴 수 있는 이유 검토'],['premortem','틀릴 수 있는 이유 검토'],
    ['데블스 애드버킷','반대 근거 검토'],['데블스','반대 근거 검토'],['프리모템','틀릴 수 있는 이유 검토'],
    ['분해 트리','조건별 확률 계산'],['최종 출력','최종 판단'],['리서치 구성','조사 방법'],
    ['참조 클래스','비교한 과거 사례'],['참조군','비교한 과거 사례 집단'],['base_rates','과거 사례 조사 자료'],
    ['base rate','과거 사례의 발생 비율'],['base-rate','과거 사례의 발생 비율'],['anchor','출발 확률'],
    ['NOT FOUND','자료를 찾지 못함'],['UNCONFIRMED','공식 확인 안 됨'],['ambiguous_resolution','판정 기준이 모호함'],
    ['strict-inequality(동률=NO)','기준보다 엄격히 높아야 함(같으면 미실현)'],['strict inequality','기준보다 엄격히 높아야 함'],
    ['strict-inequality','기준보다 엄격히 높아야 함'],['strict','엄격한'],['inequality','대소 비교 조건'],
    ['initial print','최초 발표치'],['final when issued','발표되는 즉시 확정'],
    ['non-GAAP diluted EPS','회사 조정 기준 희석 주당순이익'],['GAAP diluted EPS','공식 회계기준 희석 주당순이익'],
    ['non-GAAP EPS','회사 조정 기준 주당순이익'],['GAAP EPS','공식 회계기준 주당순이익'],
    ['GAAP/non-GAAP','공식 회계기준/회사 조정 기준'],['non-GAAP','회사 조정 기준'],['비GAAP','회사 조정 기준'],
    ['GAAP gross margin','공식 회계기준 매출총이익률'],['gross margin','매출총이익률'],['GAAP GM','공식 회계기준 매출총이익률'],
    ['GAAP','공식 회계기준'],['조정 EPS','조정 주당순이익'],['diluted','희석'],['adjusted','조정 기준'],
    ['pro-forma','일회성 항목 등을 조정한'],['actual','실제 발표치'],['consensus creep','시장 예상치가 발표 직전 계속 높아짐'],
    ['컨센서스 creep','시장 예상치가 발표 직전 계속 높아짐'],['컨센 크리프','시장 예상치가 발표 직전 계속 높아짐'],['creep','계속되는 상향'],
    ['market_implied','시장 가격에 반영된 확률'],['required_snapshots','판정에 필요한 기준값 기록'],
    ['snapshots: {}','기준값 기록 없음'],['snapshots 없음','기준값 기록 없음'],['snapshots','기준값 기록'],
    ['isEarningsDateEstimate: false','집계사의 발표일 확정 표시'],['recompute_on_actual: true','실제 예측값으로 다시 계산한다는 사전 약속'],
    ['질문 검증','예측 조건 확인'],['미검증','아직 확인하지 못한 사항'],['리서치','자료 조사'],
    ['스냅샷','당시 저장한 기준값'],['컨센서스','시장 예상치'],['컨센','시장 예상치'],['가이던스','회사 전망'],
    ['해소가능','결과를 판정할 수 있음'],['해소 가능','결과 판정 가능'],['해소 불가','결과 판정 불가'],['해소','결과 판정'],
    ['캘리브레이션','예측 확률의 정확도 점검'],['Brier','예측 오차 점수'],['브라이어','예측 오차 점수'],
    ['P3 게이트','성과 검증 기준'],['P0/P1','초기·자료 조사 단계의'],['P0','초기 검증 단계의'],['P1','자료 조사 단계의'],
    ['게이트','검증 기준'],['프리플라이트','기록 전 사전 점검'],['레짐','시장 국면'],['rolling-90일','예측일부터 90일'],
    ['rolling-90','예측일부터 90일'],['rolling','예측일부터 새로 계산하는'],['윈도우','판정 기간'],
    ['서브에이전트','조사 담당'],['에이전트','조사 담당'],['파이프라인','조사·검증 과정'],['플래그','표시'],
    ['divergence','예측 방법 간 확률 차이'],['registry notes','질문 등록부 메모'],['registry deadline','질문 등록부의 판정 기한'],
    ['registry','질문 등록부'],['deadline','판정 기한'],['resolution','판정 기준'],['notes','메모'],
    ['market-daily','하루 주가 방향 예측'],['day-research','하루 시장 자료 조사'],['general research','종합 자료 조사'],
    ['general','종합 조사'],['devil','반대 근거 조사'],['source:','출처:'],['evidence','근거 부록'],
    ['v4 리포트','나스닥 주간 시나리오 보고서'],['OneDrive report 폴더','보관된 보고서 모음'],['CLAUDE.md','운영 원칙 문서'],
    ['데이터 아티팩트','저장 자료'],['회계 아티팩트','회계 처리에 따른 수치 왜곡'],['edge','시장 예상과의 차이'],['엣지','시장 예상 대비 우위'],
    ['무엣지','시장 대비 우위를 전제하지 않는'],['시그널','판단 신호'],['시그널링','사전 신호 전달'],
    ['컴퓨트','연산 자원'],['compute','연산'],['캐펙스','설비투자'],['캡엑스','설비투자'],['CAPEX','설비투자'],['capex','설비투자'],
    ['크립토','가상자산'],['알트코인','비트코인 이외 가상자산'],['알트','비트코인 이외 가상자산'],
    ['하이퍼스케일러','대형 데이터센터 사업자'],['펀더멘털','사업 실적과 기초 여건'],['멀티플','이익 대비 주가 배수'],
    ['드로다운','최고점 대비 하락폭'],['드리프트','장기 평균 상승 추세'],['무드리프트','장기 평균 상승 추세가 없다는'],
    ['배리어','기준선'],['conjunctive','두 조건 모두 충족'],['disjunctive','여러 경로 중 하나 이상 충족'],
    ['barrier-hit','기간 중 기준선 도달'],['terminal','마지막 시점의 값으로 판정'],['risk-neutral','투자자의 위험 보상 요구가 포함된 시장가격 기준'],
    ['exogenous','외부 요인에 따른'],['futures-implied','금리선물에 반영된'],['futures','금리선물'],
    ['non-SEP','경제전망을 발표하지 않는'],['비SEP','경제전망을 발표하지 않는'],['longer-run','장기 균형금리'],['longer run','장기 균형금리'],
    ['step-function bootstrap','회의 사이 금리를 단계별로 고정해 선물가격에서 역산하는 계산'],
    ['Outlook Report','경제·물가 전망 보고서'],['Summary of Opinions','주요 의견 요약'],['Outlook','경제·물가 전망'],
    ['Blackout Calendar','정책 발언 제한 기간 일정'],['Blackout','정책 발언 제한 기간'],['블랙아웃','정책 발언 제한 기간'],
    ['Voting against the monetary policy action were','이 통화정책 결정에 반대표를 던진 위원은'],
    ['Voting against the monetary policy action','통화정책 결정에 반대표를 던진 위원'],['Voting against this action','이번 결정에 반대표를 던진 위원'],
    ['Several participants favored an increase of 25 basis points at this meeting','여러 참가자가 이번 회의에서 25베이시스포인트 인상을 선호했다'],
    ['Several participants favored an increase of 25 basis points','여러 참가자가 25베이시스포인트 인상을 선호했다'],
    ['several participants favored an increase','여러 참가자가 인상을 선호했다'],
    ['labor demand consistent with full employment','노동 수요가 완전고용에 부합한다'],['we have work to do','아직 해야 할 일이 남았다'],
    ['underlying trends','기조적인 흐름'],['it may be a while','시간이 걸릴 수 있다'],['may be a while','시간이 걸릴 수 있다'],
    ['price stability','물가 안정'],['near-term','가까운 시일 내'],['low-teens','10%대 초반'],['mid-teens','10%대 중반'],
    ['peaking gross margins as more volume moves inside of supply chain agreements struck at pricing from one to two quarters ago','1~2분기 전 가격으로 맺은 공급계약 물량의 비중이 늘면서 매출총이익률이 정점에 가까워지고 있다'],
    ['sideways consolidation','큰 방향 없이 횡보'],['buyers balk','구매자의 가격 저항'],['lackluster showing','부진한 결과'],
    ['above 30%','30% 초과'],['slightly above 40%','40%를 소폭 웃도는'],['clearly above','뚜렷하게 웃도는'],
    ['BoJ set to hike as soon as September','일본은행이 이르면 9월에 금리를 올릴 수 있음'],
    ['BoJ favors quarter-point hike','일본은행이 0.25%포인트 인상을 선호'],
    ['OpenAI confidentially files for IPO','오픈에이아이가 기업공개 서류를 비공개로 제출'],
    ['September Fed decision now a coin flip as rate hike odds increase','인상 가능성이 높아지며 9월 미국 금리 결정 전망이 팽팽해짐'],
    ['The Nasdaq Just Entered Second Correction of 2026','나스닥이 2026년 두 번째 조정에 진입'],
    ['Why the iShares Semiconductor ETF (SOXX) Plunged 21%','미국 반도체 상장지수펀드가 21% 급락한 이유'],
    ['Hyperscalers tap external financing','대형 데이터센터 사업자가 외부 자금을 조달'],
    ['A History of FOMC Dissents','미국 금리 결정 반대표의 역사'],['Sets the Date','실적 발표일 확정'],
    ['Earnings Insight','실적 분석 보고서'],['Call Transcript','실적 설명회 녹취록'],['Prepared Remarks','실적 발표 사전 원고'],
    ['prepared remarks','실적 발표 사전 원고'],['Interim Report','중간보고서'],['interim','임시'],['Investor Relations','투자자 정보'],
    ['Financial Calendar','재무 일정'],['Revenue by Market','시장별 매출'],['Earnings','실적'],['Results','발표 자료'],
    ['Calendar','일정'],['Reference','참고 자료'],['release date','발표일'],['Table ','표 '],['Figure ','그림 '],
    ['federal funds rate median','정책금리 전망 중간값'],['deposit facility rate','예금금리'],['nonfarm payroll','비농업 신규 고용'],
    ['headline CPI-U','전체 소비자물가'],['core CPI-U','근원 소비자물가'],['headline','전체'],['core goods','근원 재화'],
    ['core','근원'],['shelter','주거비'],['Shelter','주거비'],['base effect','전년 비교 기준에 따른 기저효과'],
    ['base(MoM/index)','비교 기준이 되는 전월 대비 변화율·지수'],['base(MoM)','비교 기준이 되는 전월 대비 변화율'],
    ['base','기준 발생 비율'],['goods','재화'],['goodwill impairment','영업권 손상차손'],['loss contingencies','우발손실'],
    ['imputation','누락 가격 추정'],['publication-then-decay','발견·공표 뒤 효과가 약해진 현상'],
    ['freemium','무료 서비스를 먼저 제공하고 유료로 전환하는 방식'],['AI-first','인공지능 중심'],
    ['AI-influenced','인공지능 기능이 영향을 준'],['Digital Media','디지털 미디어 사업'],['Services','서비스 사업'],
    ['Intelligent Cloud','기업용 클라우드 사업'],['Underweight','비중 축소 의견'],['Buy','매수 의견'],['Sell','매도 의견'],
    ['미스','시장 예상 하회'],['miss','시장 예상 하회'],['MISS','시장 예상 하회'],['비트','시장 예상 상회'],['beat','시장 예상 상회'],['BEAT','시장 예상 상회'],
    ['tie','동률'],['tail','가능성은 낮지만 큰 영향을 주는 위험'],['proxy','대용 추정치'],['프록시','대용 추정치'],
    ['트리거','판단 조건'],['허들','비교 기준선'],['버킷','구간'],['워크다운','발표 전 예상치 하향 조정'],
    ['리비전','예상치 수정'],['모달','가장 가능성이 높은 값'],['사구간','확실한 판단이 어려운 구간'],
    ['램프','생산 확대'],['언락','제약 해소'],['리컨스티튜션','지수 구성종목 조정'],['캡되어','제한되어'],
    ['中國','중국'],['source','출처'],['caveat','유의사항'],['green','상승 상태'],['dovish','완화적인'],
    ['로스터','위원 구성'],['tally','표결 집계'],['governor','연준 이사'],['nimble','기민한 대응'],
    ['PBC','공익법인'],['SPAC','기업인수목적회사'],['DRS','비공개 상장 서류 초안'],['JOBS Act','미국 신생기업 자금조달 관련 법'],
    ['EXIT','투자 비중 축소'],['HOLD','검증 보류'],['degraded','조사 품질 저하'],['unresolved','판정 대기'],
    ['null','기록 없음'],['AND/OR','모두 또는 하나 이상 충족'],['AND','모두 충족'],['OR','하나 이상 충족'],
    ['YES','실현'],['NO','미실현'],['void','판정 제외'],['vs','대비'],['Path ','경로 ']
  ];
  const tokens={
    AMAT:'어플라이드머티어리얼즈',LRCX:'램리서치',KLAC:'케이엘에이',TER:'테라다인',ENTG:'인테그리스',ADI:'아날로그디바이시스',TXN:'텍사스인스트루먼트',MPWR:'모놀리식파워시스템즈',NXPI:'엔엑스피반도체',MCHP:'마이크로칩테크놀로지',ON:'온세미컨덕터',INTC:'인텔',SNDK:'샌디스크',CME:'시카고상품거래소',GW:'기가와트',GB:'기가바이트',Gb:'기가비트',PC:'개인용 컴퓨터',UEDA:'우에다 총재',TAKATA:'다카타 위원',HIMINO:'히미노 부총재',ASADA:'아사다 위원',SATO:'사토 위원',NIPA:'국민소득·생산계정',ESP:'예상 실적 상회 판단지표',Rank:'투자등급',ZORI:'신규 주거 임대료 지수',IATA:'국제항공운송협회',WTI:'미국 서부텍사스산 원유',RSI:'최근 상승·하락 강도 지표',M2:'광의통화량',SMH:'다른 반도체 상장지수펀드',N3:'3나노미터 반도체 공정',DDR4:'4세대 디램',DDR5:'5세대 디램',eSSD:'기업용 저장장치',OCI:'오라클 클라우드 인프라',AWS:'아마존 클라우드 서비스',MPM:'통화정책회의',NIRP:'마이너스 금리 정책',PT:'제시 가격',FMS:'펀드매니저 조사',OW:'시장 비중보다 높게 투자',Q:'분기',CQ2:'달력 기준 2분기',AHE:'시간당 평균임금',IBES:'기관별 실적 예상치 집계',NT:'대만 달러',US:'미국',PDF:'문서',HTML:'웹 문서',URL:'자료 링크',EPS:'주당순이익',GM:'매출총이익률',FCF:'잉여현금흐름',COGS:'매출원가',ASP:'평균 판매가격',SBC:'주식보상비용',
    FOMC:'미국 연방공개시장위원회',SEP:'연준 경제전망',CPI:'소비자물가',PCE:'개인소비지출 물가',PPI:'생산자물가',
    NFP:'비농업 신규 고용',GDP:'국내총생산',BLS:'미국 노동통계국',BEA:'미국 경제분석국',
    YoY:'전년 대비',MoM:'전월 대비',QoQ:'직전 분기 대비',YTD:'연초 이후',
    NVDA:'엔비디아',NVIDIA:'엔비디아',MU:'마이크론',Micron:'마이크론',AAPL:'애플',Apple:'애플',
    ADBE:'어도비',Adobe:'어도비',AMZN:'아마존',Amazon:'아마존',MSFT:'마이크로소프트',Microsoft:'마이크로소프트',
    GOOGL:'알파벳',Alphabet:'알파벳',META:'메타',Meta:'메타',ORCL:'오라클',Oracle:'오라클',
    AVGO:'브로드컴',Broadcom:'브로드컴',AMD:'에이엠디',ASML:'에이에스엠엘',TSMC:'티에스엠씨',TSM:'티에스엠씨',
    OpenAI:'오픈에이아이',BoJ:'일본은행',ECB:'유럽중앙은행',Fed:'연준',
    DC:'데이터센터',AI:'인공지능',ATH:'최고점',SOXX:'미국 반도체 상장지수펀드',SOX:'미국 반도체 지수',
    IXIC:'나스닥 종합지수',NASDAQ:'나스닥',NDX:'나스닥100',SPX:'미국 대형주 500개 지수',GSPC:'미국 대형주 500개 지수',
    VIX3M:'3개월 예상 변동성 지수',VVIX:'시장 불안 지수의 변동성',VIX:'시장 불안 지수',
    TOTAL2:'비트코인을 제외한 가상자산 전체 시가총액',TOTAL3:'비트코인·이더리움을 제외한 가상자산 시가총액',
    BTC:'비트코인',ETH:'이더리움',OTHERS:'상위 10종목을 제외한 가상자산 시가총액',
    ETF:'상장지수펀드',ETP:'상장지수상품',IPO:'기업공개',IR:'투자자 정보',SEC:'미국 증권거래위원회',EDGAR:'미국 공시 열람 시스템',
    USD:'미국 달러',EUR:'유로',TWD:'대만 달러',JPY:'일본 엔',ADR:'미국 주식예탁증서',
    CI:'신뢰구간',LLM:'자료와 논거를 해석한 예측',ML:'과거 수치로 계산한 통계 예측',
    GBM:'일정한 변동성과 평균 추세를 가정한 가격 모형',gbm:'일정한 변동성과 평균 추세를 가정한 가격 모형',
    T5:'과거 시계열 패턴을 학습한 예측 모형',t5:'과거 시계열 패턴을 학습한 예측 모형',
    bolt:'여러 시계열에서 학습한 예측 모형',c2:'다양한 시계열 패턴을 학습한 다른 예측 모형',
    IB:'투자은행',CFO:'최고재무책임자',CEO:'최고경영자',CAO:'최고회계책임자',ARR:'연간 반복매출',
    LTV:'고객 생애가치',MAU:'월간 이용자 수',AUM:'운용자산',BOM:'부품 원가',RPO:'향후 매출로 인식할 계약 잔액',
    HBM:'고대역폭 메모리',HBM4:'차세대 고대역폭 메모리',HBM3E:'고성능 고대역폭 메모리',
    DRAM:'디램 메모리',NAND:'낸드 메모리',NRV:'순실현가능가치에 따른 재고평가',
    CoWoS:'첨단 반도체 패키징 공정',ASIC:'특정 용도 전용 반도체',SoC:'시스템 통합 반도체',
    OIS:'초단기 금리 교환계약',OER:'자가주거비 추정치',NSA:'계절조정 전',SA:'계절조정 후',
    SPF:'전문 예측가 조사',ADP:'민간 고용정보 회사의 고용 보고서',ISM:'미국 공급관리협회',PMI:'구매관리자지수',
    JOLTS:'구인·이직 조사',NFCI:'미국 금융여건지수',CDS:'신용위험 보장계약 비용',HY:'저신용 회사채',IG:'투자적격 회사채',
    OAS:'옵션 영향을 조정한 가산금리',CTA:'추세 추종 자금',MAE:'평균 절대오차',RMSE:'큰 오차에 더 비중을 둔 평균 오차',
    SCA:'전략고객 공급계약',LTM:'최근 12개월',BofA:'뱅크오브아메리카',GS:'골드만삭스',JPM:'제이피모건',MS:'모건스탠리',
    CBOE:'시카고옵션거래소',FRED:'세인트루이스 연준 경제통계',FINRA:'미국 금융산업규제기구',NYSE:'뉴욕증권거래소',
    ET:'미국 동부시각',KST:'한국시각',UTC:'세계표준시',MT:'미국 산악시각',
    DTE:'만기까지 남은 일수',BEI:'채권시장 기대인플레이션',EIA:'미국 에너지정보청',P:'확률',
    CMC:'코인마켓캡',CMCAltcoin:'가상자산',TPS:'임시보호 신분',JEC:'미국 의회 합동경제위원회',
    API:'공개 자료 조회',CLI:'예측 실행 도구',HTTP:'접근 오류',UNCONFIRMED:'공식 확인 안 됨'
  };
  const series={
    'us-gaap:NetCashProvidedByUsedInOperatingActivities':'영업활동 현금흐름',
    'us-gaap:PaymentsToAcquireProductiveAssets':'생산설비 취득 지출',
    'Purchases of property and equipment, net of proceeds from sales and incentives':'유형자산 취득액에서 매각대금과 지원금을 뺀 금액',
    Y034RC1Q027SBEA:'설비투자',Y001RC1Q027SBEA:'지식재산 투자',BAMLH0A0HYM2:'미국 저신용 회사채 가산금리',
    NASDAQCOM:'나스닥 종합지수',NASDAQSOX:'미국 반도체 지수',NASDAQ100:'나스닥100',DFEDTARU:'미국 정책금리 목표 상단',
    VIXCLS:'시장 불안 지수 종가',T10Y2Y:'미국 국채 10년물·2년물 금리 차',PAYEMS:'미국 비농업 취업자 수',
    CUUR0000SA0L1E:'계절조정 전 근원 소비자물가지수',CUSR0000SA0L1E:'계절조정 후 근원 소비자물가지수',
    DCOILBRENTEU:'브렌트유 가격',SP500:'미국 대형주 500개 지수',
    'KXCPICOREYOY-26AUG-T2.4':'8월 근원 소비자물가 2.4% 초과 계약',KXFEDDECISION:'미국 회의별 금리 결정 계약',
    'KXFED-26DEC':'미국 12월까지 금리 결정 계약','CRYPTOCAP:TOTAL2':'비트코인을 제외한 가상자산 시가총액',
    altcoinMarketCap:'비트코인 이외 가상자산 시가총액',ath_change:'최고점 대비 변화율',epsTrend:'주당순이익 예상치 변화',
    'VIX_History.csv':'시장 불안 지수 일별 종가 원자료'
  };
  const sections=['예측 조건 확인','비슷한 과거 사례 검토','이번 근거에 따른 조정','조건별 확률 계산','틀릴 수 있는 이유 검토','최종 판단'];
  const escape=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const regexEscape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  function configure(value){data=value||{};unresolved.clear();return api;}
  function reviewNeeded(field,value){unresolved.set(field+'\u0000'+value,Object.freeze({field,value:String(value)}));return '설명 검토가 필요합니다. 보존된 원문에서 확인할 수 있습니다.';}
  function issues(){return Object.freeze([...unresolved.values()]);}
  function questionList(){return Array.isArray(data.questions)?data.questions:[];}
  function title(question){const q=typeof question==='string'?(questionList().find(item=>item.id===question)||{id:question}):question||{};if(titles[q.id])return titles[q.id];const presented=text(q.title||'질문 제목을 확인할 수 없습니다.',{noQuestionReferences:true});return diagnostics(presented).length?reviewNeeded('question.title',q.title||q.id):presented;}
  function sourceLabel(path){
    const raw=String(path).replace(/\\/g,'/');
    const match=raw.match(/(?:\d{4}-\d{2}-\d{2}_)?([a-z0-9][a-z0-9-]+)_r(\d+)(_evidence)?\.md$/);
    if(match){const date=raw.match(/(\d{4}-\d{2}-\d{2})_/);return `${date?date[1]+' · ':''}${title(match[1])} · ${match[2]}번째 예측${match[3]?'의 근거 자료':' 원문'}`;}
    if(/_r\d+_evidence\.md$/.test(raw))return '해당 예측의 근거 자료';
    if(/ml_auto\.md$/.test(raw))return '통계 예측 비교 자료';
    if(/market_auto\.md$/.test(raw))return '시장 예상 확률 조사 자료';
    if(/market-regime\.md$/.test(raw))return '시장 국면별 과거 사례 조사';
    if(/corporate-event\.md$/.test(raw))return '기업 상장·공시 과거 사례 조사';
    if(/volatility\.md$/.test(raw))return '시장 불안 지수 과거 사례 조사';
    if(/macro\.md$/.test(raw))return '경제·통화정책 과거 사례 조사';
    if(/portfolio_prereg_v1\.yaml$/.test(raw))return '질문별 사전 계획 원문';
    if(/CLAUDE\.md$/.test(raw))return '운영 원칙 원문';
    return '기록 원문 자료';
  }
  function text(value,context={}){
    if(value===null||value===undefined)return '';
    let result=String(value),saved=[];
    const sectionLabels=sections.slice();
    if(/^#{1,6}\s*\[5\]\s*데블스/m.test(result)){sectionLabels[5]='반대 근거 종합';sectionLabels[6]='최종 판단';}
    result=result.replace(/예상 p=/g,'예상 확률=').replace(/실제 p=/g,'실제 확률=').replace(/p\(1−p\)/g,'확률×(1−확률)');
    if(/nvda-rev-/.test(context.forecast?.question_id||context.forecast?.forecast_id||''))result=result.replace(/컨센서스가 \$109~110B로 인플레되고/g,'시장 예상치가 $109~110B로 부풀려지고').replace(/C가 실제치 이상으로 인플레/g,'시장 예상치가 실제 총매출 이상으로 높아짐').replace(/C 인플레/g,'시장 예상치가 높아진 경우').replace(/컨센 인플레/g,'시장 예상치가 과도하게 높아짐').replace(/인플레 여부/g,'과도하게 높아지는지').replace(/(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)C\b/g,'$1 × 시장 예상치').replace(/\bR\b/g,'발표 총매출').replace(/\bC\b/g,'시장 예상치');

    const protect=raw=>{const key='\u0001'+saved.length+'\u0002';saved.push(raw);return key;};
    const questionId=context.question?.id||context.forecast?.question_id||context.forecast?.forecast_id||'';
    if(/btc-alt-mania-90d/.test(questionId))result=result.replace(/P\(b\s*\|\s*a\)/g,'비트코인 종가가 최고점을 경신했을 때 다른 가상자산 시가총액이 50% 증가할 확률').replace(/P\(a\)/g,'비트코인 종가가 최고점을 경신할 확률').replace(/P\(b\)/g,'다른 가상자산 시가총액이 50% 증가할 확률');
    if(/fomc-2026-09-16-nonunanimous/.test(questionId))result=result.replace(/\bX\s*[–−-]\s*Y\s+vote\b/g,'찬성 수 – 반대 수 표결').replace(/\bY\s*≥\s*1\b/g,'반대 수가 1명 이상');
    // Link destinations are immutable: translations never alter URLs or their dates/identifiers.
    result=result.replace(/https?:\/\/[^\s<>\]]+/g,raw=>protect(raw));
    result=result.replace(/`?((?:forecasts\/\d{4}\/|data\/base_rates\/|base_rates\/|questions\/)?(?:\d{4}-\d{2}-\d{2}_)?[a-zA-Z0-9_./-]+\.(?:md|yaml|csv))`?/g,(whole,path)=>{
      const label=sourceLabel(path);let target=path;
      if(!target.includes('/')&&/^\d{4}-/.test(target))target='forecasts/'+target.slice(0,4)+'/'+target;
      if(!target.includes('/')&&context.forecast?.source_uri&&/^_r\d+_evidence\.md$/.test(target))target=context.forecast.source_uri.replace(/_r\d+\.md$/,target);
      if(target.startsWith('base_rates/'))target='data/'+target;
      if(target==='ml_auto.md'||target==='market_auto.md')target='data/base_rates/'+target;
      if(!target.includes('/')&&/_r\d+_evidence\.md$/.test(target)&&context.forecast?.source_uri){const current=context.forecast.source_uri.match(/(\d{4}-\d{2}-\d{2})_/);if(current)target='forecasts/'+current[1].slice(0,4)+'/'+current[1]+'_'+target;}
      if(!target.includes('/')&&target!=='CLAUDE.md')return label;
      return protect('['+label+']('+repo+target+')');
    });
    result=result.replace(/(?<![A-Za-z0-9])([a-z][a-z0-9.-]+\.[a-z]{2,}(?:\/[^\s)\]]+)?)/g,(_,url)=>protect('[자료 출처 보기](https://'+url+')'));
    if(!context.noQuestionReferences){
      Object.keys(titles).sort((a,b)=>b.length-a.length).forEach(id=>{
        result=result.replace(new RegExp(regexEscape(id)+'(?:_r(\\d+))?','g'),(_,round)=>'「'+titles[id]+'」'+(round?'의 '+round+'번째 예측':''));
      });
    }
    // Exact expressions whose letters have a source-specific meaning.
    result=result.replace(/\bSOX_(\d{4}-\d{2}-\d{2})\b/g,'미국 반도체 지수 $1 종가').replace(/\bNDX_(\d{4}-\d{2}-\d{2})\b/g,'나스닥100 $1 종가');
    Object.entries(series).sort((a,b)=>b[0].length-a[0].length).forEach(([from,to])=>{result=result.split(from).join(to);});
    result=result.replace(/\b(?:8-K|6-K)\s*(?:Ex(?:hibit)?[ -]?99\.[12]|EX-99\.[12])?/gi,'주요사항·실적 공시');
    result=result.replace(/\bUSDL-\d{2}-\d+\b/g,'해당 월 고용상황 보고서').replace(/\bPRNewswire\s+\d+\b/g,'회사 배포 보도자료');
    result=result.replace(/\bCIK\s*\d+\b/g,'해당 회사의 공시 등록 정보');
    result=result.replace(/\b(?:8-K|6-K)\s*(?:Ex(?:hibit)?[ -]?99\.1|EX-99\.1)?/gi,'주요사항·실적 공시').replace(/\b10-Q\b/g,'분기보고서').replace(/\b10-K\b/g,'연차보고서');
    result=result.replace(/\bEX-99\.1\b/gi,'실적 보도자료 첨부문서').replace(/\b424B\b/g,'확정 공모조건 신고서').replace(/\bS-1\/F-1\b/g,'미국·해외 발행사용 공개 상장 등록서류').replace(/\bS-1\b/g,'공개 상장 등록서류').replace(/\bF-1\b/g,'해외 발행사용 상장 등록서류');
    result=result.replace(/\b([A-Za-z]+)?\s*(FQ[1-4])\s*(FY)?(20\d{2}|\d{2})\b/g,(_,prefix,quarter,fy,year)=>`${prefix?prefix+' ':''}${year.length===2?'20'+year:year} 회계연도 ${quarter.slice(-1)}분기`);
    result=result.replace(/\bFY(20\d{2}|\d{2})\s*Q([1-4])\b/g,(_,year,quarter)=>`${year.length===2?'20'+year:year} 회계연도 ${quarter}분기`);
    result=result.replace(/\bQ([1-4])\s*FY(20\d{2}|\d{2})\b/g,(_,quarter,year)=>`${year.length===2?'20'+year:year} 회계연도 ${quarter}분기`);
    result=result.replace(/\bF?Q([1-4])['’](\d{2})\b/g,'20$2 회계연도 $1분기').replace(/\bF?Q([1-4])FY(\d{2})\b/g,'20$2 회계연도 $1분기');
    result=result.replace(/\bFY(20\d{2}|\d{2})\b/g,(_,year)=>`${year.length===2?'20'+year:year} 회계연도`).replace(/\bCY(20\d{2}|\d{2})\b/g,(_,year)=>`${year.length===2?'20'+year:year}년`);
    result=result.replace(/\bQ([1-4])\s*(20\d{2})\b/g,'$2년 $1분기').replace(/\b([1-4])Q(\d{2})\b/g,'20$2년 $1분기').replace(/\b([12])H(\d{2})\b/g,(_,half,year)=>`20${year}년 ${half==='1'?'상반기':'하반기'}`);
    result=result.replace(/\b(20\d{2})Q([1-4])\b/g,'$1년 $2분기').replace(/\b(20\d{2})H([12])\b/g,(_,year,half)=>year+'년 '+(half==='1'?'상반기':'하반기'));
    result=result.replace(/\bFQ([1-4])\b/g,'회계 $1분기').replace(/\bQ([1-4])\b/g,'$1분기').replace(/\bH1\b/g,'상반기').replace(/\bH2\b/g,'하반기');
    result=result.replace(/\bD-(\d+)\b/g,'발표 $1일 전').replace(/\bT-11\b/g,'주간 관측으로 일별 도달 가능성을 낮게 계산하는 한계');
    result=result.replace(/\br(\d+)\b/gi,'$1번째 예측').replace(/\b(\d+)R\b/g,'$1번째 예측');
    result=result.replace(/\bF1\b/g,'나스닥 최고점 경신 질문').replace(/\bF2\b/g,'나스닥 10% 하락 질문').replace(/\bF3\b/g,'나스닥 연말 종가 질문').replace(/\bC5 사전등록/g,'질문 묶음의 사전 계획').replace(/\bC5\b/g,'질문 묶음 사전 계획');
    result=result.replace(/P\/C\b/g,'풋옵션·콜옵션 거래량 비율').replace(/\b2s10s\b/g,'국채 10년물·2년물 금리 차');
    result=result.replace(/\bS([1-4])\b/g,'$1번째 가능 경로');
    result=result.replace(/(^|\n)(#{1,6})\s*\[\d+\]\s*/g,'$1$2 ').replace(/\*\*\[(\d+)\]\s*/g,'**');
    result=result.replace(/\[(\d)\]/g,(_,number)=>'「'+(sectionLabels[Number(number)]||'해당 검토')+'」');
    // The order is reviewed: longer accounting and source phrases precede simple terms.
    phrases.slice().sort((a,b)=>b[0].length-a[0].length).forEach(([from,to])=>{const left=/^[A-Za-z0-9]/.test(from)?'(?<![A-Za-z0-9_])':'';const right=/[A-Za-z0-9]$/.test(from)?'(?![A-Za-z0-9_])':'';result=result.replace(new RegExp(left+regexEscape(from)+(from==='비트'?'(?!코인)':'')+right,'g'),to);});
    result=result.replace(/\bNT\$(\d+(?:,\d{3})*(?:\.\d+)?(?:[~–−-]\d+(?:,\d{3})*(?:\.\d+)?)?)(?:\s*(bn|B|M|m|K|T|억|조)(?![A-Za-z0-9]))?/g,(_,amount,unit)=>amount+({B:'십억',bn:'십억',M:'백만',m:'백만',K:'천',T:'조',억:'억',조:'조'}[unit]||'')+' 대만 달러');
    result=result.replace(/(?:US)?\$(\d+(?:,\d{3})*(?:\.\d+)?(?:[~–−-]\d+(?:,\d{3})*(?:\.\d+)?)?)(?:\s*(bn|B|M|m|K|T|억|조)(?![A-Za-z0-9]))?/g,(_,amount,unit)=>amount+({B:'십억',bn:'십억',M:'백만',m:'백만',K:'천',T:'조',억:'억',조:'조'}[unit]||'')+' 달러');
    Object.entries(tokens).sort((a,b)=>b[0].length-a[0].length).forEach(([from,to])=>{
      result=result.replace(new RegExp('(?<![A-Za-z0-9_])'+regexEscape(from)+'(?![A-Za-z0-9_])','g'),to);
    });
    result=result.replace(/\^나스닥 종합지수/g,'나스닥 종합지수').replace(/\^미국 반도체 지수/g,'미국 반도체 지수').replace(/\^미국 대형주 500개 지수/g,'미국 대형주 500개 지수');
    result=result.replace(/(?<![A-Za-z])bp\b/g,'베이시스포인트(금리 0.01%포인트 단위)').replace(/%p\b|%p(?=[^A-Za-z]|$)/g,'%포인트').replace(/(?<![A-Za-z])pp\b/g,'%포인트');
    result=result.replace(/\bml_auto\b/g,'통계 예측 비교 자료');
    result=result.replace(/\by\/y\b/g,'전년 대비').replace(/\bcc\b/g,'환율 영향을 고정한 기준').replace(/\bn\s*=/g,'표본 수=').replace(/\bp\s*=/g,'통계적 유의성 판단값=');
    result=result.replace(/(?<![A-Za-z])P\(([^\n]*)\)/g,'확률($1)').replace(/\bp_i\b/g,'각 촉매의 발생 확률');
    result=result.replace(/\bUSD\/ADR\b/g,'미국 주식예탁증서당 미국 달러').replace(/\bUSD per ADR\b/g,'미국 주식예탁증서당 미국 달러');
    result=result.replace(/\$(\d[\d,]*(?:\.\d+)?(?:[~–−-]\d[\d,]*(?:\.\d+)?)?)\s*(B|bn|M|m|K|T)\b/g,(_,amount,unit)=>amount+({B:'십억',bn:'십억',M:'백만',m:'백만',K:'천',T:'조'}[unit])+' 달러');
    result=result.replace(/(?<=\d)B\b/g,'십억').replace(/(?<=\d)bn\b/g,'십억').replace(/(?<=\d)M\b/g,'백만').replace(/(?<=\d)K\b/g,'천');
    result=result.replace(/(\d)k\b/g,'$1천').replace(/(\d)m\b/g,'$1백만').replace(/(\d)T\b/g,'$1조');
    result=result.replace(/\bNT\$/g,'대만 달러 ').replace(/\bUS\$/g,'미국 달러 ');
    result=result.replace(/`([^`]+)`/g,'$1');
    result=result.replace(/(?<=\d)USD\b/g,' 미국 달러').replace(/(?<=\d)NT\b/g,' 대만 달러');
    result=result.replace(/\bC급/g,'세 번째 신뢰도 등급의 자료').replace(/\bD급/g,'네 번째 신뢰도 등급의 자료');
    result=result.replace(/\b[A-D]\b(?!-\d)/g,letter=>({'A':'첫째 조건','B':'둘째 조건','C':'셋째 조건','D':'넷째 조건'}[letter]));
    result=result.replace(/(?<=\d)DTE\b/g,'일 만기 옵션').replace(/(?<=\d)dma\b/g,'일 이동평균').replace(/(?<=\d)nm\b/g,'나노미터 공정');
    result=result.replace(/\b[A-D]-(\d+)\b/g,token=>{const names={A:'첫째',B:'둘째',C:'셋째',D:'넷째'};return names[token[0]]+' 근거 묶음 '+token.slice(2)+'번';});
    result=result.replace(/P\(/g,'확률(');
    result=result.replace(/(?<![A-Za-z])x(?=\s*(?:\d|확률|P\(|\())/g,'×').replace(/\s+x\s+/g,' × ');
    result=result.replace(/\bJan\b/g,'1월').replace(/\bFeb\b/g,'2월').replace(/\bApr\b/g,'4월').replace(/\bMay\b/g,'5월').replace(/\bJun\b/g,'6월').replace(/Sep2023/g,'2023년 9월').replace(/Dec2023/g,'2023년 12월').replace(/Mar2024/g,'2024년 3월');
    result=result.replace(/\bn\b/g,'표본 수').replace(/\bt\b/g,'평균 차이 검정값').replace(/\bz\b/g,'표준편차 기준 거리').replace(/σ/g,'표준편차').replace(/Φ/g,'정규분포 누적확률');
    result=result.replace(/실현\|첫째 조건/g,'첫째 조건일 때 실현').replace(/실현\|둘째 조건/g,'둘째 조건일 때 실현');

    result=result.replace(/주당순이익가/g,'주당순이익이').replace(/주당순이익를/g,'주당순이익을').replace(/매출총이익률가/g,'매출총이익률이').replace(/매출총이익률를/g,'매출총이익률을').replace(/공식 회계기준와/g,'공식 회계기준과').replace(/공식 회계기준를/g,'공식 회계기준을').replace(/신뢰구간를/g,'신뢰구간을').replace(/미실현가/g,'미실현이').replace(/실현가/g,'실현이').replace(/미실현로/g,'미실현으로').replace(/실현로/g,'실현으로').replace(/회사 전망는/g,'회사 전망은').replace(/회사 전망를/g,'회사 전망을').replace(/시장 예상치을/g,'시장 예상치를').replace(/시장 예상치이/g,'시장 예상치가').replace(/시장 예상치와/g,'시장 예상치와').replace(/과거 사례의 발생 비율를/g,'과거 사례의 발생 비율을').replace(/달러이/g,'달러가').replace(/질문와/g,'질문과').replace(/금리선물는/g,'금리선물은').replace(/조정 기준 기준/g,'조정 기준').replace(/조정 기준로/g,'조정 기준으로').replace(/인공지능로/g,'인공지능으로').replace(/회사 회사 전망/g,'회사 전망').replace(/시장 예상치 시장 예상치/g,'시장 예상치').replace(/시장 예상치가 과도하게 높아짐 리스크/g,'시장 예상치가 과도하게 높아질 위험').replace(/당시 저장한 기준값된/g,'기준값으로 저장된').replace(/희석 주당순이익라는/g,'희석 주당순이익이라는').replace(/서프라이즈/g,'예상과 다른 결과').replace(/프린트/g,'최초 발표치').replace(/인플레/g,'물가 상승').replace(/디스물가 상승/g,'물가 상승세 둔화').replace(/물가 상승레이션/g,'물가 상승').replace(/디스물가 상승레이션/g,'물가 상승세 둔화').replace(/애그리게이터/g,'여러 자료를 모은 출처').replace(/기준로/g,'기준으로').replace(/기준와/g,'기준과').replace(/시장 불안 지수 3개월/g,'3개월 시장 불안 지수').replace(/투자자 정보은/g,'투자자 정보는');

    return result.replace(/\u0001(\d+)\u0002/g,(_,index)=>saved[Number(index)]);
  }
  function criteria(question){
    const q=question||{};
    let value=q.resolution||'';
    // These symbols denote economic values, rather than paths A/B/C in forecast bodies.
    if(/^(?:adbe|avgo)-eps-(?:surprise|miss|above)/.test(q.id||''))value=value.replace(/\bG_high\b/g,'회사 전망 상단').replace(/\bA\b/g,'발표 주당순이익').replace(/\bC\b/g,'시장 예상치');
    if(/^nvda-rev-/.test(q.id||''))value=value.replace(/\bR\b/g,'발표 총매출').replace(/\bC\b/g,'시장 예상치');
    return text(value,{question:q});
  }
  function method(round){
    const value=String(round?.method||'');
    if(value==='p1-pipeline/2agents'||value==='skill/2agents')return '종합 조사와 반대 근거 검토를 각각 수행한 예측';
    if(value==='v4-report-derived')return '나스닥 시나리오 보고서의 근거와 조건별 판단을 바탕으로 한 예측';
    if(value==='quick-research')return '당일 공개 자료와 시장 상황을 빠르게 확인한 예측';
    if(!value)return round?.model?'인공지능이 작성한 예측 · 별도 산출 방법 기록 없음':'산출 방법 기록 없음';
    return reviewNeeded('forecast.method',value);
  }
  function inline(value){
    const links=[];
    let source=String(value).replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(_,label,url)=>{
      const key='\u0003'+links.length+'\u0004';links.push('<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer">'+escape(label)+'</a>');return key;
    });
    source=source.replace(/https?:\/\/[^\s<>\]]+/g,url=>{const key='\u0003'+links.length+'\u0004';const suffix=url.match(/[).,;]+$/)?.[0]||'';const href=suffix?url.slice(0,-suffix.length):url;links.push('<a href="'+escape(href)+'" target="_blank" rel="noopener noreferrer">근거 자료 보기</a>'+escape(suffix));return key;});
    source=escape(source).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(?<!\*)\*([^*]+)\*(?!\*)/g,'<em>$1</em>');
    return source.replace(/\u0003(\d+)\u0004/g,(_,index)=>links[Number(index)]);
  }
  function html(value){
    const lines=String(value??'').replace(/\r\n/g,'\n').split('\n');
    let out=[],paragraph=[],list=null,fence=false,tree=[];
    const flushParagraph=()=>{if(paragraph.length){out.push('<p>'+paragraph.map(inline).join('<br>')+'</p>');paragraph=[];}};
    const closeList=()=>{if(list){out.push('</'+list+'>');list=null;}};
    const flush=()=>{flushParagraph();closeList();};
    for(let index=0;index<lines.length;index++){
      const line=lines[index],trim=line.trim();
      if(/^```/.test(trim)){flush();if(fence){out.push('<div class="records-reasoning-tree">'+tree.map(row=>'<div>'+inline(row)+'</div>').join('')+'</div>');tree=[];}fence=!fence;continue;}
      if(fence){tree.push(line);continue;}
      if(!trim){flush();continue;}
      const heading=trim.match(/^(#{1,6})\s+(.+)$/);
      if(heading){flush();const level=Math.min(5,Number(heading[1].length)+1);out.push('<h'+level+'>'+inline(heading[2])+'</h'+level+'>');continue;}
      if(/^[-*_]{3,}$/.test(trim)){flush();out.push('<hr>');continue;}
      if(trim.startsWith('|')&&index+1<lines.length&&/^\s*\|[\s:|\-]+\|\s*$/.test(lines[index+1])){
        flush();const cells=row=>row.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(cell=>cell.trim().replace(/\\\|/g,'|'));
        const head=cells(line);out.push('<div class="records-table-scroll"><table><thead><tr>'+head.map(cell=>'<th scope="col">'+inline(cell)+'</th>').join('')+'</tr></thead><tbody>');index++;
        while(index+1<lines.length&&lines[index+1].trim().startsWith('|')){const row=cells(lines[++index]);out.push('<tr>'+row.map(cell=>'<td>'+inline(cell)+'</td>').join('')+'</tr>');}
        out.push('</tbody></table></div>');continue;
      }
      const bullet=trim.match(/^([-+*]|\d+\.)\s+(.+)$/);
      if(bullet){flushParagraph();const kind=/^\d/.test(bullet[1])?'ol':'ul';if(kind!==list){closeList();list=kind;out.push('<'+kind+'>');}out.push('<li>'+inline(bullet[2])+'</li>');continue;}
      if(trim.startsWith('>')){flush();out.push('<blockquote>'+inline(trim.replace(/^>\s?/,''))+'</blockquote>');continue;}
      closeList();paragraph.push(line);
    }
    flush();if(fence&&tree.length)out.push('<div class="records-reasoning-tree">'+tree.map(row=>'<div>'+inline(row)+'</div>').join('')+'</div>');
    return '<div class="records-prose">'+out.join('')+'</div>';
  }
  function diagnostics(value){
    const visible=String(value??'').replace(/https?:\/\/[^\s)\]]+/g,'');
    return [...new Set(visible.match(/\p{Co}|\b(?:[rR]\d+|[vV]\d+(?:\.\d+)*|[a-z][a-z0-9]+(?:_[a-z0-9]+)+|ml_auto|frontmatter|market_implied|required_snapshots|snapshots|MPM|GAAP|EPS|FQ[1-4]|FY\d+|P[0-3]|ex-2)\b|\b(?:r\d+|P[0-3]|(?:forecast|question|research|source|model|prompt|schema|method)_[a-z0-9_]+|[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}|\w+\.(?:md|yaml|jsonl|csv))\b/gu)||[])];
  }
  const api={configure,text,title,criteria,method,html,diagnostics,issues};
  root.RecordsCopy=Object.freeze(api);
})(typeof window==='undefined'?globalThis:window);
