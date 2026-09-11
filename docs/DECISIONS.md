# 결정 기록 (Decision Log)

> 헌법(CLAUDE.md)이 "사용자만 결정"으로 지정한 항목의 결정 이력. 각 결정은 위임 근거를 명시한다.

## 2026-07-15 — AUDIT-260715 §8 결정 5건

**위임 근거**: 사용자 지시 "너가 생각하는 최적의 효율로 스스로 판단해서 다 진행해" (2026-07-15) — Claude가 §10 보고서의 권고안을 그대로 채택.

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 8-1 | 시나리오 확률 (D-1/D-2) | **(c) 3분할** — 상승-ATH돌파 / 상승-ATH미달 / 조정. 확률은 모델 산출을 직접 상속: **50 / 16 / 34** (P(S1)=종점>ATH≈50%, P(S1)+P(S2)=F3 66%, P(S3)=34%) | 결과공간 완전분할 + 단조성 제약 자동 충족. 판단 개입 최소화 — 사후 합리화 여지 제거 |
| 8-2 | 블라인드 예측 채점 (D-6) | **(c)+(b)** — 원장은 전량 채점(투명), r2는 메타 오버라이드(`calibration/research_status_overrides.csv`)로 failed 표기 → 대표 Brier·게이트는 `v_brier_primary`(failed 제외) 기준. 신규 예측은 `research_status` 자동 태그 | 사건 #5(무예측 만료 제외)와 논리 일관. primary는 표본이 작아져 게이트가 늦어짐 = 보수적. 파일·원장 무수정 (C1·C2) |
| 8-3 | LPPL 정본 (D-9) | **(c) 병기** — raw(2026-10)와 보정(2027-05)을 항상 라벨과 함께 병기, 리스크 판단은 보정값+미드텀 시즌성 기준. 순환성(닷컴 1사이클 역산 상수) 고지 유지 | 시스템이 스스로 편향으로 규정한 값의 단독 사용 금지 |
| 8-4 | base rate 신선도 (D-5) | **N=7일, 경고만** (차단 없음) — `due` 출력에 빈티지 경고 | ML 신선도 7일과 정합. 차단은 수동 경로의 유연성을 해침 |
| 8-5 | 분위수 밴드 주입 (Q4) | **(a) 존치 + 한계 명문화** — 역산 복원 실측(괴리 2%p)을 04 #23·재현 테스트로 고정, divergence 트리거는 "부분 독립" 신호로 재정의 | Outside view 가치 > 부분 앵커링 비용. 은폐가 아니라 계량된 수용 |

주: 8-1의 50/16/34는 2026-07-15 모델 산출값의 함수 — ml 재실행으로 앙상블이 갱신되면 시나리오 확률도 같은 규칙으로 재산출한다 (규칙이 정본, 숫자는 파생).

| 8-6 | 수치 모델 백테스트 예외 명문화 (P4 검증 렌즈 지적 — 모듈이 존재하지 않는 CLAUDE.md 조항을 인용) | CLAUDE.md 원칙 5에 예외 조항 신설: 결정론 수치 모델의 과거 적합 허용, 근거는 사용자 제공 dualdb 스펙 v1.0 §8. 조건 3개(참조 지위·하이퍼파라미터 caveat·LLM 개입 시 예외 불가) 부착 | 스펙 §8이 이미 사용자 승인 문서 — 헌법에 반영해 인용 근거 정합화 |
| 8-7 | LPPL 워크포워드의 정직 결론 채택 | 닷컴 실측: 정점 1개월 전에야 수렴 + 경계히트 17/21로 편향 보정 무의미 → **LPPL을 조기경보 도구에서 강등**, raw/보정 병기하되 리스크 판단 근거에서 제외 (v3.1은 이미 미드텀 시즌성 기준으로 이행) | 자체 검증이 자기 도구를 기각한 사례 — 은폐하지 않고 채택 |
| 8-3′ | **8-3 개정 포인터** (RE-AUDIT R-1, 2026-07-15) | 8-3의 "리스크 판단은 보정값 기준" 문구는 **8-7에 의해 대체됨** — 병기 원칙은 유지하되 보정값은 '비활성화(아티팩트)' 라벨 필수, 리스크 판단 근거로 불사용. quant 렌더러에 코드 게이트 내장(재실행 침식 방지). 8-3 원행은 결정 로그 append 정신에 따라 무수정 | 폐기된 결정 문구가 하류 문서에 공존(R-1)하는 것을 차단 |
| 8-8 | **집계·클램프 명문 규약** (상용 시스템 조사 A-6, 2026-07-15) | ① 공식 확률 = LLM 파이프라인 rN (K>1 활성 시 K회 고정 중앙값) — quant·ML·시장내재는 base rate 참조·divergence 견제이며 최종 확률에 산술 결합하지 않음 ② 확률 클램프 1~99% (스키마 강제 — 극단 캡핑 관례) ③ 결합 함수는 고정 중앙값, geomean-of-odds 전환은 표본 축적 후 비교 검토 | Samotsvety/GJP/상위 봇 공통의 '문서화된 고정 프로토콜' 관례 이식 |
| 8-9 | **배관 선행 원칙** (2026-07-15) | K회 실행 시트(`AI_FC_REASONING_RUNS`, 기본 1)와 섀도 extremization 열(`shadow_extremized`, α=√3 표시 전용)을 **지금 배관하되 비활성** — K>1 활성은 P2 게이트 후 사용자 결정(C9), 실 보정은 해소 100+ ML 게이트 뒤. 섀도 열 덕에 게이트 도달 시점에 '보정했다면'의 성능 비교 데이터가 이미 존재 | AIA 실증: 앙상블·사후보정이 최대 단일 개선 — 게이트 준수와 준비를 양립 |

## 2026-07-20 — v2 고도화 라운드 결정 3건 (스펙 aifc_v2_upgrade_planmode_260720 v1.0)

**위임 근거**: 사용자가 외부 검토 확정 스펙을 제시하고 플랜모드 계획을 승인 (2026-07-20). 스펙 §2 헌법 제약 하에서 실행.

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 9-1 | **WS3 이산화 보정 = ML 게이트 비저촉 판정** | GBM 일간 스텝 재추정과 T5 브라운 브리지 보정(p=exp(−2·d₀·d₁/σ_w²))은 **닫힌형 결정론 수식 — 파라미터 학습·가중치 갱신 0** → ML 게이트(해소 100+/200+) 비저촉. σ_w는 경로 내 증분 std 추정치(모델 적합 아님) | 스펙 §2-5 명시 위임. 게이트의 보호 대상은 '데이터에서 학습되는 자유도'이며 결정론 변환은 해당 없음 (GBM 시뮬 자체와 동일 지위) |
| 9-2 | **divergence 판정 기준값 = 보정값 전환** | `due`의 15%p 괴리 판정과 ml_history 기록 확률을 **보정값**(T5 브리지·GBM 일간) 기준으로 전환. raw 주간값은 ml_auto.md·detail에 상시 병기 (추적성) | T-11(주간 이산 과소추정)이 divergence의 구조적 원인 일부였음 — 편향 있는 기준값으로 괴리를 재는 것이 더 큰 왜곡. 전환 시점 명기로 시계열 단절 추적 가능 |
| 9-3 | **WS1 등록 필터 규약** | created ≥ 2026-07-21 질문은 notes `등록필터:` 마커 필수 — (a) base rate/시장내재 [35,65] 밖 또는 (b) 정보 우위 논거. 집행: forecast 프리플라이트 오류 + sync W2 경고. 기존 질문 grandfather. 정본: questions/FACTORY_GUIDE.md | 기해소 2건(코인플립, Brier 0.25·0.29)의 실측 교훈 — 판별 불가 질문은 표본을 늘려도 게이트 증명에 기여하지 못함. 수치 진위 검증은 사람 몫(코드는 기재 강제만) |
| 9-4 | **v3.5 신뢰 계층 결정 2건** (사용자 승인 2026-07-20) | ① WS-T5 FRED 경로 개선 포함 — curl 폴백(기본 UA — 실측상 서버가 파이썬 TLS+커스텀 UA만 필터, curl 기본 요청은 정상 응답. 공개 데이터·주 1회·robots 준수 = 정상 접근 복원) ② OpenTimestamps **실행** (스펙 기본 미실행을 뒤집음) — 로컬 환경 제약(AppControl·OpenSSL3)으로 **CI 스탬프 봇**(ots-stamp.yml)이 .hashes 변경마다 스탬프·커밋백 | 공증 완성형(제3자 시계) + Yahoo 단일 의존 완화. 증명 등급 체계는 tools/verify_track_record.py가 정본 |
| 9-5 | **^IXIC 1995~2004 종가 정본 = FRED NASDAQCOM 승격** (감사 260720 F-01, 사용자 포괄 승인 "발견사항 다 진행" 2026-07-20) | 닷컴·2004 구간 price_daily의 close/adj_close 2,519행을 FRED 값으로 교체 (source='fred-close+yahoo-ohlcv' — OHLC·volume은 Yahoo 유지). 교차 불일치 3.11%→0.10%, 센티널 6점 전부 유지, cross-check 테스트 **무수정 PASS 전환** (§10.4 준수 — 데이터 정합으로 해소) | 증거: 센티널 3자 대조에서 양 벤더 앵커 일치 → 비앵커 괴리는 revision vintage 차이. 연준 재배포의 기관 출처 규율 채택. Stooq 제3소스는 JS 검증 게이트로 접근 불가(우회 안 함 — 원칙). 잔여 한계는 KNOWN_LIMITS 32 |

## 2026-08-01 — LLM provider 거버넌스

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 10-1 | OpenAI provider 도입 | Responses API adapter와 shadow 병렬 경로만 도입. **공식 생산자는 Anthropic 유지** | 트랙레코드 연속성과 hindsight 금지 |
| 10-2 | 모델 식별 | 날짜가 포함된 snapshot만 허용하고 이동 alias는 거부 | 재현성·버전별 점수 분리 |
| 10-3 | 공식 전환 | 고유 해소 10+ paired 비교·비용 보고·사용자 승인·`approvals.csv` 정확 일치 전에는 CI가 차단 | ADR-003, Grand Blueprint WP-15 |

## 2026-08-03 — OpenAI 공식 자동 갱신 승인

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 10-4 | 공식 자동 생산자 전환 | 저장소 소유자의 명시 지시로 신규 자동 갱신에 `openai:gpt-5.6-terra`를 사용. 기존 Anthropic 예측은 그대로 보존하고 소급 재예측·재분류하지 않음. 10-3의 paired 10+ 대기 조건은 이번 직접 승인으로 예외 처리하되 모델 계보·비용 원장·회당/월간 한도·롤백 경로를 강제 | 사용자 지시 “open api key 로 investing fetch나 업데이트 다 진행할 수 있도록” (2026-08-03), `calibration/approvals.csv` |
| 10-5 | 자동 운영 한도 | 주 1회, due 최대 1건, 2 research profiles(데블스 포함), 회당 $1.50, OpenAI/전역 월 $10, 검색 4회·출력 토큰 상한. 시장 원천 fetch는 결정론 수집기를 유지하고 OpenAI는 근거 조사·예측에 사용 | 비용 통제와 출처 재현성 |

## 2026-08-31 — ADR-002 임베드 용량 예산 확정

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 11-1 | 자기완결 임베드 예산 | `DASHBOARD_RAW_BUDGET_BYTES`를 **900 KiB → 1.5 MiB(1536 KiB)**로 상향 | 블루프린트 Q4/ADR-002의 선호안(정적 JSON 분리)은 **임베드에 적용 불가** — `reports/dashboard.html`은 fetch가 없어 분리가 곧 삭제다. 900 KiB에서는 압축 셸 579 KB + 본문 제외 데이터 214 KB가 **계약의 86%를 선점**해 추론 본문에 129 KB(회차당 6.9 KB 기준 18건)만 남았고, 감사 스냅샷이 존재 이유인 내용을 떨어뜨리고 있었다. 1.5 MiB는 활성 질문당 본문 1건(29문항 992 KB)을 여유 37%로 담고 활성 50문항까지 견딘다 |
| 11-2 | 인라인 본문 상한 | `EMBED_INLINE_BODY_LIMIT` 12 → **40** (정상 운영에서 작동하지 않는 backstop) | 상한은 병리적 단일 본문에 대한 안전장치로만 남긴다. 초과분은 구조 필드와 불변 `source_uri`를 유지하고 `embed_body_budget`로 공시 |
| 11-3 | 미채택 대안 | 본문 압축 사전(`FORECAST_BODY_DICTIONARY`) 확장은 보류 | 코퍼스 전체 절감 후보가 8.6 KB인데 임베드가 담는 몫은 약 2 KB로, `dashboard.js`의 `BODY_DICTIONARY` 동기화 위험 대비 이득이 낮다. 필요 시 예비 여유로 남긴다 |
| 11-4 | 승인 | 저장소 소유자 직접 승인 (2026-08-31) | 블루프린트 Q4의 승인 주체는 사용자이며, 예산 구조를 두 차례 보고 후 "최적의 방법으로 진행" 지시 |

- Pages 경로(`data.json`·`/api/data`)는 종전대로 **전 컬럼·전 본문**을 유지한다. 본 결정은 자기완결 임베드에만 적용된다.
- 성장 벡터는 이번 라운드에서 이미 축소됐다: append-only 거버넌스 섹션의 렌더 필드 투영(`EMBED_RENDERED_FIELDS`), band-calibration 원시 행 아카이빙, 해소·상위 회차 본문 제외.

## 2026-08-31 — 블루프린트 Q3 조사 결과 (데이터 재배포·표시 권리)

블루프린트 미결정 Q3 "CBOE·Nasdaq Data Link·Google News 재배포/표시 권리 | 약관 원문 확인 | Codex 조사→사용자"의 **조사 기록**이다. 결정이 아니라 결정을 위한 자료이며, 승인 주체는 사용자로 남는다. 아래는 문서에 적힌 내용의 보고이며 법률 의견이 아니다.

**저장소 실제 사용 현황 (2026-08-31 코드 대조)**

| 소스 | 사용 모듈 | 용도 |
|---|---|---|
| CBOE | `market/options_bl.py` · `market/runner.py` · `timeseries_v2/market_archive.py` · `timeseries_v4/source_store.py` · `timeseries_v5/features.py` | `VIX_History.csv`·`VIX9D_History.csv` 다운로드, delayed options quotes, 파생 통계·base rate 산출 후 공개 페이지 표시 |
| Google News RSS | `ml/sentiment.py` · `ml/runner.py` · `inventory.py` | 헤드라인 수집 → FinBERT 감성 → 집계 지수(−1~+1)와 샘플 헤드라인 제목을 공개 표시 |
| **Nasdaq Data Link** | **없음** | **미사용 — Q3 범위에서 제외 가능** |

**조사 판정 (원문 취득 2026-08-31)**

| # | 소스 | 판정 | 근거 |
|---|---|---|---|
| 12-1 | CBOE | **명시적 금지** | Terms of Use §2(Last Updated 2022-11-16)가 허용하는 것은 "view, print and download **one copy** … for your **personal non-commercial use**"뿐이고, `display`·`publish`·`distribute`·`create a derivative work`·`store … in an electronic retrieval system`·`use to verify or correct other data`를 사전 서면 동의 없이 금지 목록에 열거한다. "Materials" 정의에 `databases`·`text` 포함. 비상업 면제 없음 |
| 12-2 | Google News RSS | **명시적 금지** | 피드 응답 본문의 `<copyright>` 엘리먼트가 "solely for the purpose of rendering Google News results within a **personal feed reader** for personal, non-commercial use. **Any other use of the feed is expressly prohibited.**" 별도 약관 페이지는 404(NOT FOUND) — 라이선스가 피드에 내장돼 있다. 추가로 `news.google.com/robots.txt`가 `/rss/`를 모든 UA에 disallow하고 `anthropic-ai`·`ClaudeBot` 등에 `Disallow: /` |
| 12-3 | Nasdaq Data Link | **해당 없음** | 저장소가 사용하지 않음. (참고: 게시 약관은 Order Form 체결을 전제해 무료·익명 티어를 규율하는 문서가 NOT FOUND인 회색지대) |

**문서가 답하지 않는 지점 (사람 판단 영역)**

- CBOE 조항이 스스로 열어둔 유일한 통로는 `"except to the extent that such use constitutes 'fair use'"`다. 비상업·개인용·파생 통계 중심이라는 이 프로젝트의 성격이 여기 해당하는지 문서는 답하지 않는다.
- 사실 데이터(숫자 자체)의 저작물성은 ToS 계약 위반과 별개 층위이나 문서가 다루지 않는다.
- Google 피드는 제목/본문을 구분하는 문구가 없다. 실측상 본문은 애초에 제공되지 않으나(`<description>`이 링크 마크업뿐), 이는 제목 표시가 허용된다는 뜻이 아니라 본문 복제 경로가 없다는 사실일 뿐이다.

**문서에 명시된 정식 경로**

CBOE는 `permissions@cboe.com`으로 사용 목적·스크린샷·배포 계획·기간을 보내면 5영업일 내 회신을 목표로 하며, 승인 시 라이선스 계약 체결을 조건으로 한다(Use of Cboe Content). 세 소스 중 문서가 절차를 명시한 유일한 곳이다.

**미결 — 사용자 결정 사항**

이 기록은 Q3의 조사 단계를 닫을 뿐이며, 다음은 결정되지 않았다: (a) 현행 사용을 유지할지, (b) CBOE에 사용 허가를 요청할지, (c) 공개 표시 범위를 줄일지(예: 원값 비표시·파생 통계만), (d) Google News RSS 수집을 중단하거나 대체 소스로 옮길지. 데이터 원천 변경은 `vix-25-90d`의 판정 출처와 base rate 산출에 직접 영향을 주므로 임의로 변경하지 않았다.

### 2026-08-31 — Q3 후속 결정 (12-4)

앞선 Q3 조사 기록(12-1~12-3)에 대한 사용자 결정.

| # | 소스 | 결정 | 근거 |
|---|---|---|---|
| 12-4a | **Google News RSS** | **수집 중단** | 세 소스 중 문서가 가장 명확하다 — 라이선스가 피드 응답 본문에 내장돼 "personal feed reader" 용도로 한정하고 그 외 사용을 명시 금지하며, `robots.txt`가 `/rss/`를 전 UA에 disallow 한다. CBOE와 달리 fair use 같은 예외 단서도 없다. 반면 손실은 가장 작다 — 감성 지수는 base rate 문맥 신호일 뿐 어떤 질문의 판정 출처도 아니다 |
| 12-4b | **CBOE** | **대체 경로 조사 후 판단 (보류)** | 데이터를 잃지 않고 문제를 닫을 수 있는 유일한 경로다. 다만 FRED 등 재배포처도 원출처 저작권 시리즈를 별도 표기하므로 실제로 더 나은지는 조사 전까지 불명이다. 조사 결과를 별도 기록한다 |
| 12-4c | Nasdaq Data Link | 조치 없음 | 저장소가 사용하지 않음 (12-3) |

**12-4a 구현 범위 — 수집만 끊고 기록은 보존한다.**

- `ml/sentiment.py`에서 네트워크 수집 경로(`fetch_headlines`·`score_feed`·분류기 로더·Google News 검색 쿼리)를 제거했다. `run_all_feeds()`는 빈 목록을 반환한다.
- **모듈을 지우지 않았다.** `data/ml_history/*.jsonl`은 append-only이고 이미 수집된 감성 행이 들어 있으며 `base_rates.py`·`db/queries.py`·리포트 렌더러가 이를 참조한다. `FeedSentiment`와 `FEED_KEYS`를 남겨 과거 기록을 계속 읽는다.
- **빈 결과를 0.0으로 기록하지 않는다.** `sentiment_overall`은 관측이 없으면 `None`이다. 0.0을 적으면 "중립 감성을 관측했다"는 거짓이 원장에 남는다.
- 리포트의 감성 섹션은 수집이 없을 때 지수 대신 중단 사실과 사유를 낸다. 과거 기록이 있는 실행을 다시 렌더하면 종전 표를 그대로 낸다.

과거 수집분은 삭제하지 않는다 — 불변 기록이며, 소급 삭제는 이 프로젝트가 금지하는 사후 조작에 해당한다.

### 2026-08-31 — 12-4b 후속: CBOE 대체 경로 조사 결과 (12-5)

12-4b가 지시한 조사를 마쳤다. **결론: 이전은 위치를 개선하지 않으며 대부분 악화시킨다. 소스는 CBOE에 유지한다.**

| 후보 | 판정 | 근거 (원문 취득 2026-08-31) |
|---|---|---|
| **FRED (VIXCLS)** | **더 나쁨** | ① 시리즈 노트가 "Copyright, 2016, Chicago Board Options Exchange, Inc. Reprinted with permission." — **CBOE 저작권이 그대로 따라오고 고지 유지 의무까지 생긴다**. ② FRED 스스로 "The Bank cannot give you such permission" 명시. ③ **AI/ML 사용 금지 조항이 같은 페이지에 3회** — "Use the FRED Services or FRED Content in connection with the development or training of any software program or system or machine learning, including … large language models". CBOE 약관에는 이런 조항이 **없다**. ④ store·cache·archive 및 DB 편입 금지 — 저장소 커밋과 충돌. ⑤ §III("인용하면 게시 가능")와 FAQ#3·Full ToU("소유자 허가 필수")가 서로 모순 |
| **Yahoo Finance** | **더 나쁨** | 자동 수집을 명시적으로 금지("robots, spiders, scrapers, data mining tools … without our express, prior permission"). CBOE 약관에는 이 문언이 없다. `^VIX9D`가 존재하는 유일한 무료 경로이나 취득 근거가 없다 |
| **Stooq** | 부적격 | 이용약관 문서 자체가 **NOT FOUND**(404) = 허가 근거 없음. 게다가 봇 검증으로 자동 취득이 현재 작동하지 않는다 |
| **datasets/finance-vix (PDDL 선언)** | **명백히 더 나쁨** | 데이터를 **같은 `cdn.cboe.com` URL**에서 가져오면서, README가 근거를 자백한다 — "Given size and factual nature of the data … **would imagine this was public domain** and as such have licensed the Data Package under the PDDL". 소유하지 않은 데이터에 제3자가 추측으로 부여한 라이선스에 의존하는 기록이 남는다 |
| **정부·거래소 중립 소스** | **존재하지 않음** | VIX는 사실 기록이 아니라 CBOE 소유 산출 지수다. Market Data Policies: "All proprietary rights … in the Data … shall remain the sole and exclusive property of Cboe". 모든 경로가 CBOE로 수렴한다 |

**시리즈별 결론**

| 필요 시리즈 | 결론 |
|---|---|
| VIX 일간 종가 | CBOE 유지. FRED로 옮기면 CBOE 저작권은 따라오면서 **AI/ML 금지·캐시 금지가 추가**되어 순손실 |
| **VIX9D** | CBOE 유지 — **대안 자체가 없다**. FRED 검색 결과 0건, 가장 짧은 것이 30일물(VIXCLS)이고 나머지는 3개월물 |
| 옵션 내재확률 | CBOE 유지. **무료로 공개 표시가 허용되는 미국 지수 옵션 소스는 존재하지 않는다** — 벤더 정책이 아니라 OPRA Vendor Agreement라는 시장 구조상 제약이라 호스트를 바꿔도 해소되지 않는다 |

**대신 발견한 실질적 경로 — CBOE 자체 정책에 이 프로젝트 형태와 일치하는 라이선스 카테고리가 있다.**

`Market_Data_Policies.pdf`(Effective 2026-07-01) §19(b) "Delayed Open Website" License:

> "A Data Recipient may provide access to Delayed Data via an open website under the 'Delayed Open Website' License only if: (a) access is openly available to the public and there is no authentication system requiring login through a unique ID and password combination; (b) there is no trading functionality available; and (c) the Index Delayed Data is being provided for informational purposes only."

이 프로젝트는 세 조건에 문언상 부합한다(공개·로그인 없음·거래 기능 없음·정보 제공 목적). 다만 이는 **Data Agreement 체결자에게 적용되는 규정**이므로 자동으로 주어지는 권리가 아니라 **따라갈 수 있는 경로**다.

**따라서 위치를 실제로 개선하는 유일한 조치는 호스트 변경이 아니라 허가 취득이다.** `permissions@cboe.com`으로 Request to Use Cboe Content를 제출하는 절차가 문서에 명시돼 있고(5영업일 회신 통례, 의무 아님), 요청서 초안은 `docs/cboe_permission_request_draft.md`에 준비했다. **발송은 저장소 소유자가 직접 한다** — 대외 커뮤니케이션이며 회신 조건 수용 여부도 소유자 판단이다.

**미해결로 남는 것 (문서로 해소 불가)**

- CBOE 약관의 `"fair use" under the Copyright Act of 1976` 유보가 이 용도를 포섭하는지 — 법률 검토 영역
- 허가의 유상/무상 여부 — **NOT FOUND**
- 회신이 **명시적 거절**일 경우 fair use 모호성이 사라져 제거 외 선택지가 좁아진다는 점 — 신청 자체의 양면성

### 2026-08-31 — 12-6: FRED 자동 수집을 공식 API 전용으로 전환

블루프린트 Q3 조사에서 `fredgraph.csv` 스크랩이 약관 위반임을 확인해 전환했다.
**결정: FRED 자동 수집은 API 키를 쓰는 공식 API로만 한다. 스크랩 폴백은 두지 않는다.**

FRED 약관(취득 2026-08-31)은 자동 수집을 금지하면서 단서를 단다:

> "data mining, mirroring, robots, scraping, or similar data-gathering or extraction
> methods" … **"except as expressly allowed by the terms of use applicable to the FRED API"**

`fredgraph.csv`는 그래프 페이지용 엔드포인트라 이 단서에 해당하지 않는다. 공식 API는 해당한다.

**폴백을 두지 않은 이유**: 키가 없을 때 조용히 스크랩으로 되돌아가면 준수 경로가 사실상
무력해진다. 키 부재는 `FredApiError`로 실패시킨다 — 실패는 눈에 보이지만 조용한 우회는 보이지 않는다.

**구현에서 지킨 두 가지**

1. **키는 영수증에 남기지 않는다.** 네트워크에 쓰는 URL에는 키가 들어가지만, 소스 영수증·해시에
   기록하는 URL은 `fred_api.observations_public_url()`이 돌려주는 키 없는 형태다. 이 구분이 흐려지면
   `security-check`가 잡아야 할 시크릿이 저장소에 커밋된다.
2. **호출부 파서를 바꾸지 않는다.** API는 JSON을 주지만 기존 수집기는 `fredgraph.csv` 모양
   (헤더 1줄 + `날짜,값`, 결측 `.`)을 파싱한다. `observations_to_csv()`가 그 모양으로 렌더한다.
   결측을 0으로 바꾸지 않는다 — 관측되지 않은 구간이 관측된 0으로 둔갑한다.

**전환한 곳 / 남긴 곳**

| 대상 | 처리 | 사유 |
|---|---|---|
| `quant/feed.py`(M2SL) · `statistics_lab.py` · `market_extensions.py` · `realty_income.py` | **API 전환** | 현재분 수집 경로 |
| `timeseries_v2/market_archive.py` · `v4/source_store.py` · `v5/sources.py` · `v6/public_archive.py` | **보류** | PIT 아카이브 수집기 — URL이 기록된 스펙에 들어 있고 provenance 해시에 포함된다. 바꾸면 과거 영수증과 대조가 끊긴다. 별도 처리 필요 |

**운영 요건 (전환의 필연적 귀결)**: 폴백을 없앴으므로 FRED를 부르는 워크플로에 `FRED_API_KEY`가
없으면 수집이 멈춘다. 전환 시점에 키가 배선된 워크플로는 timeseries 계열 3개뿐이었고, 실제로 API를
부르게 된 `investing-refresh`·`scenario-refresh`·`statistics-refresh`·`ai-regime-refresh` 4개는
누락 상태였다. 4개 모두 job-level `env`로 배선했다.

**후속 수정 (같은 날, 배포 검증 중 발견)**: 전환 직후 `statistics_lab.py`는 전송만 API로 바뀌고
**영수증의 `request_url`은 여전히 `fredgraph.csv`를 기록**하고 있었다(3곳). 영수증의 존재 이유가
"이 바이트가 어디서 왔는가"인데, 이제 쓰지 않고 약관도 금지하는 경로를 가리키고 있었다 —
감사자가 보면 아직 스크랩 중이라고 읽는다. 실제 취득 URL(키 없는 공개형)로 교체하고, 이를 강제하던
소스 계약 2건(`fred_market_signals.yaml`·`statistics_lab_v1.yaml`)의 `endpoint`도 함께 맞췄다.
정책의 `allowed_domains`에는 `api.stlouisfed.org`가 이미 있어 별도 확장은 필요 없었다.
`market_extensions`·`realty_income`은 처음부터 올바르게 기록하고 있었고, `quant/feed`의 영수증은
Yahoo용이라 무관하다. 미활성 사전 스펙(`fred_nfci_d0`·`fred_stlfsi4_d0`)은 대상이 아니다.

**미해결 (문서로 해소 불가 — 소유자 판단 영역)**

- 12-5는 FRED의 **AI/ML 사용 금지 조항**("in connection with the development or training of any
  software program or system or machine learning, including … large language models")을 이유 중
  하나로 CBOE→FRED 이전을 기각했다. 그런데 M2SL·BAMLH0A0HYM2 등 **FRED가 원 게시자인 시리즈**는
  계속 쓴다. 두 판단이 모순은 아니다 — 12-5는 *이미 다른 곳에서 얻는 데이터를 FRED로 옮겨* 제약을
  **추가**하는 문제였고, 여기는 대안 없는 시리즈다. 그러나 **이 조항이 본 시스템의 사용 형태를
  포섭하는지는 미해결**이다. 이 저장소는 학습을 하지 않지만(CLAUDE.md 하드 게이트) 조항 문언은
  "development … of any software program or system"까지 넓다. 법률 검토 영역이며 KNOWN_LIMITS 대상.
- 약관의 store·cache 금지와 저장소 커밋(PIT 아카이브)의 충돌도 같은 층위에서 미해결로 남는다.

### 2026-09-01 — 12-8: 제약 소스의 무료·공개 대체 전수 조사

사용자 지시("무료 opensource로 가져올 수 있는거 전부 다 대체제 찾아와서 db가져와")로
저장소가 실제로 부르는 외부 호스트를 전수 조사했다. **모든 판정은 엔드포인트 실호출 +
약관 원문 확인 기준이며, 추정은 판정으로 쓰지 않았다.**

**먼저 정정할 사실 하나** — 조사 중 발견: `statistics_lab`의 Yahoo 수집(6종 일별 시리즈)은
**이미 죽어 있었다**. `73d0e804`(authoritative 통계 원장·소스 게이트 도입)가 새 빌더
`build_statistics_lab`으로 갈아타면서 `_build_statistics_lab_legacy`를 호출에서 뺐고, 그
안에 있던 `DAILY_MARKET_SERIES` 루프도 함께 도달 불가가 됐다. 산출물로 확인된다 —
2026-08-18 07:44 아카이브는 소스 60건에 `KOSPI_DAILY` 포함, 08:26 아카이브부터 30건에
미포함, 현재 35건 중 **Yahoo 유래 0건**. 즉 통계 파이프라인은 게이트 도입의 부수효과로
**이미 Yahoo를 떠난 상태**였다. 다만 코드는 남아 있어 읽는 사람에게는 살아 있는 의존으로
보인다 — KNOWN_LIMITS 36.

**살아 있는 Yahoo 의존은 `cross_asset` 하나뿐이다**: `^IXIC`, `O`(리얼티인컴), `BTC-USD`, `DHI`.

**대체 후보 판정 (실호출 + 약관 원문)**

| 대상 | 후보 | 실호출 | 판정 |
|---|---|---|---|
| TAIEX | **TWSE 공식 OpenAPI** | 200, 일별 OHLC(ROC 역법) | ✅ **채택 가능**. 대만 정부자료개방수권조관 제1판 = CC BY 4.0 호환 — 재배포·파생·상업 허용, **AI/ML 제한 없음**, 키 불필요. 조건은 출처 표시 |
| 금 | LBMA 공식 가격 | 200, 913KB 전이력 | ❌ **기각**. "A licence from IBA is required in order to obtain, use or redistribute real-time or historical benchmark data" — 받아지는 것과 써도 되는 것은 다르다 |
| BTC | Coinbase Exchange | 200, 일별 캔들 | ❌ **기각**. "cannot redistribute, display, or disseminate the Market Data—or any … works based on, referring to, or derived from the Market Data" — 파생물 명시 금지 |
| KOSPI | 공공데이터포털 KRX | 401 (키 필요) | ⚠️ **보류**. 무료지만 소유자 명의 서비스키 등록이 선행돼야 한다 |
| KOSPI | KRX data.krx.co.kr | 403 | ❌ 직접 접근 차단 |
| (전체) | Stooq | 200이나 **JS 증명 게이트** 본문 | ❌ **우회하지 않는다** — 저장소 원칙(9-5과 동일 판단) |
| SOX · S&P500 | — | — | ❌ **독립 대체 없음**. 각각 Nasdaq·S&P 소유 지수로, 무료 재배포 허용 경로가 존재하지 않는다 (12-5에서 VIX가 CBOE로 수렴한 것과 같은 구조) |
| `O`·`DHI` 개별주 | — | — | ❌ **대체 불가**. `cross_asset`은 **배당조정 종가**(`adjusted`)로 총수익률을 계산하는데, 정부·중앙은행 소스는 개별 종목의 조정 종가를 제공하지 않는다 |

**이미 깨끗한 소스 (조치 불필요)**: sec.gov·data.sec.gov, federalreserve.gov,
home.treasury.gov·api.fiscaldata.treasury.gov, philadelphiafed·clevelandfed·newyorkfed,
bls.gov, cftc.gov, fec.gov, financialresearch.gov — 전부 미국 정부 저작물.

**결론**: 실제로 교체 가능한 것은 TAIEX(TWSE) 하나이고, 그 경로는 현재 죽어 있어 되살릴 때
쓰면 된다. 나머지는 ① 이미 대체됨(통계 파이프라인), ② 약관이 금지(금·BTC), ③ 원 소유자로
수렴해 대안 부재(SOX·S&P500·개별주), ④ 키 등록 대기(KOSPI)로 갈린다. **"무료로 받아진다"와
"무료로 써도 된다"가 갈라지는 지점이 이번 조사의 핵심이며, LBMA·Coinbase가 그 사례다.**

**남는 결정 (소유자)**

- KOSPI 일별이 필요하면 공공데이터포털 서비스키 등록.
- ~~`cross_asset`의 `^IXIC`·`BTC-USD`를 FRED로 옮길지~~ → **실행 (2026-09-01, 12-9)** — 약관상
  개선이지만 **살아 있는 분석 산출물의 수치가 바뀐다**(아카이브 비교 불연속). 9-5에서
  ^IXIC 정본을 FRED로 승격한 전례가 있어 방향은 일관되나, 실행은 별도 판단이다.

### 2026-09-01 — 12-9: cross_asset의 NASDAQ·BTC 수집을 FRED 공식 API로 이관

12-8이 소유자 결정으로 남긴 건을 사용자가 승인했다("최적의 방안을 제시하고 그대로 진행해").
**결정: `cross_asset`의 `^IXIC`·`BTC-USD` 수집을 Yahoo에서 FRED(`NASDAQCOM`·`CBBTCUSD`)로
옮긴다. `O`·`DHI`·`IYR`·배당은 Yahoo에 남긴다 — 배당조정 개별주의 무료 공개 대체가 없다(12-8).**

**전환 전 실측 (커밋된 데이터끼리 대조 — 네트워크 호출 없음)**

| 대조 | 표본 | 결과 |
|---|---|---|
| ^IXIC(Yahoo 앵커) vs NASDAQCOM | 일별 중첩 19일 (2026-07-31~08-28) | **완전 일치 0.0000%** |
| BTC-USD(Yahoo 앵커) vs CBBTCUSD | 동일 19일 | \|중앙값\| 0.054%, 최대 −0.319% (2026-08-19) |
| 닷컴 월간(2001-03~2006-03) 재지수(100기준) | 61개월 | \|중앙값\| 0.03pt, 최대 −1.20pt (2003-07) |

**판단 근거**

1. **NASDAQ은 무손실 + 교정이다.** 현대 일별은 완전 일치. 닷컴 월간의 최대 1.2pt 이동은
   오차가 아니라 **9-5가 이미 정본으로 판정한 값으로의 수렴**이다 — dualdb는 그 시대를
   FRED로 쓰는데 cross_asset만 Yahoo로 남아 있던 비일관이 해소된다.
2. **BTC는 벤더 정의 차이다.** Yahoo는 집계가, CBBTCUSD는 Coinbase 단일 거래소 종가.
   최대 0.32%의 이동과 정렬 시작일 후퇴(2014-09-17 → 2014-12-01, 정렬 관측 약 50건 감소)를
   수반한다. 최대 낙폭(−83%, 2017→2018)은 두 창 모두에 포함돼 불변. limitations에 명기.
3. **약관 위치**: Yahoo는 자동 수집을 명시 금지(12-5·12-8), Coinbase 직접은 파생물 금지(12-8),
   FRED API는 자동 수집을 명시 허용하는 유일한 경로(12-6). CBBTCUSD는 FRED 원게시가 아니라
   Coinbase 재배포이므로 KNOWN_LIMITS 34의 '원게시+대안부재' 논거가 그대로 적용되지는 않으나,
   세 제약 경로 중 명시 허용 API가 있는 유일한 선택지다. 그 긴장은 34가 이미 등재한 층위다.

**구현 규약**

- `quant/feed.fred_price_series_detail`: 월봉은 **달력 월초일 라벨 + 월말 종가**로 렌더 —
  Yahoo 월봉과 같은 의미이며, 소스가 갈린 월간 교집합이 바 라벨 일자 차이(Yahoo=첫 거래일)로
  비지 않도록 `cross_asset`의 월간 키 전체를 월초일로 정규화했다.
- 영수증 URL은 키 없는 공개형(12-6 규약). 결측 `.`은 건너뛴다 — 0으로 만들지 않는다.
- 휴면 스키마 업그레이드 함수(`upgrade_cross_asset_dotcom_counterfactual`)도 같은 소스로
  교체 — 재실행 시 Yahoo로 회귀하는 문을 닫는다.
- snapshot `sources`·`limitations`가 전환 시점·크기를 스스로 서술한다.

**배포 실측 후속 (같은 날, run 33450114842)**: 첫 실전 실행이 예고와 다른 모양으로 실패해
잠복 버그 하나를 드러냈다. 실패 사슬 — ① 같은 asof(08-28)의 경로추적 행이 Yahoo 시절 값으로
이미 기록돼 있었고, 새 소스로 재도출한 BTC 값이 달라 중복-불일치 raise(원장이 덮어쓰기를 거부한
것 자체는 올바른 동작), ② 그런데 no-op 가드가 그 예외를 **삼키고 같은 asof 전체 재빌드로**
떨어졌고, ③ 재빌드가 같은 asof의 파생 민감도 아카이브 불변 가드에 충돌해 중단됐다.
두 불변 가드는 설계대로 작동했다 — 결함은 예외를 변장시킨 가드 구조였다. 수정 2건:
**기록된 날은 최종**(재도출·비교 없이 no-op; 부분 기록만 오류 — 행은 기록 시점 소스의 관측이며
소스가 바뀌면 재도출 동일성의 전제가 사라진다), **가드는 latest 읽기 실패만 무시**(추적 오류는
전파). 중단 전에 쓰인 영수증 번들(`2026-08-28_b9fa8e4f`)은 실제 수행된 fetch의 내용주소 기록이라
그대로 둔다 — 커밋된 데이터 삭제가 오히려 규약 위반이다.

**운영 파급 (정직 고지)**

- FRED는 발행 지연이 있어(통상 1영업일) snapshot `asof`가 종전보다 하루 늦을 수 있고,
  머지 직후 첫 실행은 기존 asof보다 새 데이터가 늦어 **no-op일 수 있다** — 결함이 아니다.
- 과거 아카이브는 불변으로 남으므로 전환일 전후 스냅샷의 BTC 수치는 벤더가 다르다.
  비교 시 이 항목을 인용할 것.

### 2026-08-31 — 12-7: 뉴스 감성 수집을 GDELT로 재개

12-4a로 Google News RSS 수집을 중단한 뒤, 약관이 이 용도를 허용하는 대체 소스를 조사해 재개했다.

**조사 결론: 자동 수집·파생 집계 공개·제목 표시 셋을 모두 명시적으로 허용하는 소스는 GDELT 하나뿐이다.**

GDELT 약관 전문 (gdeltproject.org/about.html#termsofuse, 취득 2026-08-31):

> "all datasets released by the GDELT Project are available for unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee."
> "You may redistribute, rehost, republish, and mirror any of the GDELT datasets in any form. However, any use or redistribution of the data must include a citation to the GDELT Project and a link to this website."

**AI/ML 사용 제한 조항이 없다** — FRED를 기각한 사유(12-5)와 정반대다. API 키 불필요, `api.gdeltproject.org`에 robots.txt 자체가 없다. 5개 토픽 전부 임의 키워드 질의로 커버된다.

**기각한 후보와 사유**

| 후보 | 사유 |
|---|---|
| CNBC · MarketWatch · Seeking Alpha | 피드는 200을 주지만 약관이 자동 수집·파생값 공개를 명시 금지. **비영리가 방어가 안 된다** — Seeking Alpha "public *or* commercial", CNBC/Versant "whether for profit or for no profit". MarketWatch는 robots.txt 논거까지 선제 차단하고 "headlines, article summaries"를 Content 정의에 포함 |
| Reuters · AP | 피드 자체 소멸 + 명시 금지 |
| Yahoo Finance | RSS 조항은 표시를 허용하나 일반 조항의 자동 수집 금지를 해제하지 않는다. 12-5의 기각과 일관 |
| NewsAPI · Finnhub · Alpha Vantage · Currents | 파생값 공개를 명시 금지. Finnhub은 **"derived results"**를 명시. NewsAPI 무료 티어는 개발환경 전용 |
| 정부 소스 (Fed·BLS·SEC·BEA) | 법적으로 가장 깨끗하나 **감성 지수라는 산출물이 성립하지 않는다** — Fed press_all 20건 중 매크로 관련 2건, 나머지는 은행 제재·합병 승인. 토픽이 좁은 수준이 아니라 신호가 원천적으로 없다 |
| **Tiingo** | 무료 티어에 **뉴스가 아예 없다**(가격표·제품페이지·각주 3곳 교차확인). 게다가 ToS가 2026-08-05에 개정돼 무료 티어는 데이터의 **영속 저장 자체를 금지**한다(휘발성 메모리·임시 캐시만). 제목 표시는 "Display Redistribution"이라는 **별도 유료 상품**이다 |
| **EODHD** | "prohibited from: … **displaying** … the Information or Services, **whether in its original or repackaged form**" — 표시 동사를 직접 금지하고 "repackaged"로 파생형까지 덮는다. 무료·유료 **전 플랜이 `Personal use`** 표기라 돈을 내도 상업 권리가 생기지 않는다. 무료는 뉴스 1건당 5콜이라 **하루 4요청** |
| Marketaux | 금지 조항은 **없으나**(SILENT-GREY) 허가 자체가 "personal, non-commercial use"까지만 미치고 ToS에 API·데이터 조항이 없다. 침묵은 허가가 아니다 |
| Common Crawl (CC-NEWS) | 재배포 금지 조항이 **없지만** 허가도 없다. CC가 명시적으로 책임을 원 게시자에게 넘긴다 — "may be subject to separate terms of use … from the owners of such Crawled Content" |

**재사용할 교차 발견 — "무료 개인용 티어"는 이 프로젝트에 사실상 닫혀 있다.** 조사한 9곳 중
Finnhub·Alpha Vantage·Tiingo·EODHD 네 곳이 개인용 자격을 **사업자 소속 여부**로 판정한다
(Alpha Vantage "on behalf of a corporation, firm, partnership", Tiingo "representing an organization
or business", Finnhub "deduct this expense as a business expense", EODHD의 Professional User 정의).
저장소 소유자가 법인 대표이므로 이 테스트들은 **불리하게 걸린다**. 다음에 새 소스를 검토할 때
"비영리라서 괜찮다"는 논거를 먼저 버리고 시작해야 한다 — 12-4a에서 CNBC·Seeking Alpha가
"public *or* commercial"·"whether for profit or for no profit"로 같은 문을 닫은 것과 같은 층위다.

**부수 확인**: 흔히 인용되는 "GDELT는 CC BY"는 **사이트 어디에도 없다**. 실제 근거는 위에 옮긴
고유 문단이며, 인용 의무도 CC BY가 아니라 그 문단에서 나온다.

**미해결로 남는 층**: GDELT가 색인하는 상위 기사의 저작권에 대해 GDELT 약관은 침묵한다. 다만 취득 근거의 질은 Google News보다 명백히 낫다 — 그쪽은 피드에 금지 문언이 있고 robots.txt가 막았는데, GDELT는 배포를 명시 허용하고 경로를 막지 않으며 AI/ML 제한도 없다.

**운영 조건 (허가의 대가와 실측 제약)**

- **인용 의무**: `sentiment.ATTRIBUTION`("출처: The GDELT Project — https://www.gdeltproject.org/")을 감성 지수가 표시되는 모든 산출물에 싣는다. 관측이 없는 경우의 리포트에도 싣는다. **선택이 아니라 허가의 조건이다.**
- **API 불안정 (완화했으나 해소되지 않음)**: rate limit 수치가 비공개다. 피드 간 8초 간격 + 4회 재시도(5/10/15초 백오프)를 넣고 90초 냉각 후 재측정해도 **5개 중 3개 성공**이었다. 같은 질의가 잠시 뒤 성공하므로 질의 문법이 아니라 유량 문제다. 부분 성공은 성공한 피드만으로 가중평균하며, 이는 관측 표본이 줄었다는 뜻이지 값이 틀렸다는 뜻은 아니다. 연구가 제안한 `data.gdeltproject.org` 벌크 폴백(실측 전량 200)은 이번에 넣지 않았다 — 필요해지면 다음 단계.
- **전량 실패 시 None**: 12-4a 규칙 그대로 `sentiment_overall`은 0.0이 아니라 None이다.
- **영어 고정**: `sourcelang:english` — 필터 없이 돌리면 중국어 헤드라인이 섞이고 FinBERT는 영문 모델이다.
- **제목 정규화**: GDELT는 제목을 토큰화해 보관해 구두점 앞에 공백이 들어간다("No . 1 Pick"). `normalize_title()`로 정리한다. 아포스트로피는 GDELT 단계에서 이미 소실돼 복원 불가.
---

## 2026-08-31 — BEA 투자 계열의 취득 경로를 fredgraph로 유예 (사용자 결정)

`docs/design/ai_buildout_measurement_design_260831.md` Phase 0으로 통계 카드
`investment_share_of_gdp`를 추가하며, BEA 원계열 3종(`GDP`, `Y034RC1Q027SBEA`,
`Y001RC1Q027SBEA`)을 **기존 승인 경로인 fredgraph(무키 CSV)** 로 취득한다.

**선례와의 긴장.** `reports/md/bank_credit_layer_contract_260805.md` §4.1은 "신규 자동
수집은 fredgraph가 아니라 원생산자(Fed Board H.8/H.6/Z.1) 공식 다운로드를 사용하며,
기존 `fred_market_signals: approved` 상태를 신규 레이어가 상속하면 안 된다"고 규정한다.
이 결정은 그 선례를 이번 배치에 한해 적용하지 않는다.

**유예 사유.**
1. BEA 공식 API는 인증키를 쿼리스트링(`UserID=`)으로 요구하는데,
   `src/ai_fc/authoritative_statistics.py:34` `_SECRET_QUERY_KEYS`가 영수증 URI의 비밀
   쿼리를 거부한다 → **BEA 키드 API는 현재 코드로 영수증 생성이 구조적으로 불가능**하다.
2. 남은 원생산자 경로인 `apps.bea.gov/national/Release/TXT/NipaDataQ.txt`는 35MB이며,
   `official_store/raw/`가 content-addressed 커밋 대상이라 릴리스마다 35MB가 git 이력에
   누적된다(현재 감당 상한의 실증은 Z.1 zip 8MB).
3. FRED는 BEA 원계열을 변형 없이 중계하며, 본 배치의 3계열은 기존 33계열과 동일한
   수집·영수증·정규화 경로를 그대로 사용한다(신규 원천 온보딩·정책 YAML 변경 0).

**남는 부채.** 원생산자 직접 취득으로 옮기려면 (a) `timeseries_v5/sources.py`의
`sanitized_uri` 패턴을 authoritative 레인에 이식하거나, (b) 대용량 벌크를 영수증 레인이
아닌 파생 슬라이스 보존 레인으로 분리하는 설계가 선행되어야 한다. 둘 다 별도 승인 사안이다.

**주의.** FRED 경유라도 라이선스는 원천마다 다르다. 본 배치의 3계열은 BEA(미국 정부
저작물)이라 안전하나, 기존에 발행 중인 `SP500`(S&P DJI)·`NASDAQCOM`(Nasdaq OMX)은
별개의 기존 노출이며 이 결정과 무관한 별도 감사 안건이다.

**후속 (같은 날, 12-6에 의해 대체)**: 병렬 트랙의 12-6이 fredgraph 스크랩 자체를 약관
위반으로 확인하고 FRED 자동 수집을 공식 API 전용으로 전환했다. 이 항목의 "fredgraph로
유예" 결정은 그에 따라 소멸하며, BEA 3계열(`GDP`·`Y034RC1Q027SBEA`·`Y001RC1Q027SBEA`)은
다른 FRED 계열과 함께 API 경로(`fred_api.observations_csv`, 영수증에는 무키 공개 URL)로
취득된다. 원생산자 직접 취득 대비 트레이드오프 논거는 여전히 유효하다.

## 2026-09-01 — R8-D3: V8 다변량 시계열의 연구 참고 표면 공개 (display-promotion)

**결정.** 봉인 게이트를 통과한 V8(`shadow.mf_dfm_varx_calibrated_v8`)의 latest 포인터가
`sealed_gate_pass ∧ operational_pass`를 만족하는 동안, 대시보드 `#timeseries` 슬롯에
연구 참고(research_reference) 표면을 표시한다. 근거 지시: 사용자 메시지 2026-09-01
("예측 레이어 바뀐것으로 … GATE 성공시키고 싶은데 … 아직 사이트에 배포가 안되고 있잖아
다변량 시계열 데이터가"). 설계서: `docs/design/v8_publication_48h_loop_260901.md`.

**이것이 아닌 것.**
- 챔피언 승격 아님 — `promotion` 계약(automatic_champion=false, minimum_shadow_sessions=126,
  explicit_owner_approval) 무변경. V8은 공식 예측·시나리오와 결합되지 않는 격리 연구 표면.
- 재학습 아님 — 봉인 평가는 모델 버전당 1회로 종결(R8-D2). 표시 레이어만 추가되며
  `src/ai_fc/timeseries_v8/`(model_code_hash 의존 집합)은 1바이트도 바뀌지 않는다.

**fail-closed 규약.** HOLD(신선도 초과·게이트 불일치·해시 불일치) 시 숫자는 서버 단계에서
제거되고 기존 검증 대기 화면이 렌더된다. read-model 가드가 `visible ⟺ 두 게이트 동시 통과`,
`reference_opinion_only=true`, HOLD 숫자 은닉을 CI에서 강제한다.

**기록.** method_changes r19 (`method:timeseries-v8-research-reference-display:2026-09-01:r19`).

## 2026-09-02 — V9-D5: 신용·유동성 vintage 수집 트랙 개시 (사용자 결정)

**결정.** V9 G3 보고의 권고안대로 blocked 피처의 ALFRED 네이티브 vintage 수집 트랙을
개시한다. 승인 근거: 사용자 지시 2026-09-02 ("다 푸시부터 배포까지하고 다음단계 까지 설계 후
진행해") — G3 보고가 제시한 V9-D5(a) 권고에 대한 진행 지시. **V9-D4(E1 홀드아웃 소모)는
별개 사안으로 계속 보류** — 명시 승인이 아니므로 소모하지 않는다.

**수집 대상 (ALFRED vintage 실측 2026-09-02, 공식 API).** TOTCI(첫 vintage 1996-12-06)·
TOTLL(1996-12-06)·WRMFNS(2002-10-31) — 설계창(2007–2014) 완전 적격 3계열만.
예금(2012-08)·VXNCLS(2014-04)·MMMFFAQ027S(2013-06)·NFCI(2011-05)는 온셋 부족으로 보류.

**선례와의 긴장 (BEA 유예 선례 형식으로 명시).**
`reports/md/bank_credit_layer_contract_260805.md` §1은 신규 자동 수집에 원생산자(Fed Board
H.8/H.6) 공식 다운로드를 지정했다. 이 결정은 그 조항을 이번 트랙에 적용하지 않는다 —
사유: ① Board 다운로드에는 first-release vintage 이력이 없어(현행 vintage만 제공) PIT
요건(available_at ≤ origin, first-release 불변 객체)을 기계적으로 충족할 수 없고,
② DECISIONS 12-6이 FRED 공식 API를 유일 준수 자동수집 경로로 확정했으며, ③ V9 계약이
`required: alfred_vintage_collection`으로 이 경로를 명시 요구한다. 은행 계약의 나머지
규율(approved 상속 금지·WRMFSL 금지·주기 분리·reference_only)은 전부 승계한다.

**approved 상속 아님.** `fred_market_signals: approved`(current-vintage 레인)를 상속하는
것이 아니라 이미 `vintage_observation` 역할로 등록된 alfred 레인(V1 정본 스토어)에
시리즈를 추가한다. `fred_market_signals.yaml`의 "historical current-vintage rows are not
valid for backtests" 조항이 이 트랙의 필요성을 계약으로 뒷받침한다.

**KNOWN_LIMITS 34 고지.** FRED 약관의 AI/ML 문언·store/cache 조항 vs PIT 아카이브 커밋
긴장은 미해결(소유자·법률 판단 영역)이다. 본 트랙은 기존 V1 스토어 관행(NFCI 91만 행 등)의
연장선에서 커밋 부피를 늘리는 행위임을 소유자에게 고지한다.

**구현.** V1 로스터 `financial_optional` 확장 + `timeseries-collect-series` CLI(전체 창 1회
백필) + `timeseries-vintage-backfill.yml`(브랜치 커밋, collect→fit→forecast→verify 순서
계약). 상세: `docs/design/v9_credit_liquidity_vintage_track_260902.md`. 수집 완료 후 피처
승격(F2~F4)은 별도 사전등록 개정 커밋으로만 한다 — 수집 ≠ 등록.

## 2026-09-02 — Pages 배포시점 V5.2 재봉인 (미래 탐색 fail-closed 간헐 차단 해소)

**문제 (실측 2026-09-02).** scenario-refresh cron(30 1 * * 2-6)의 GitHub 지연/누락 →
커밋된 V5.2 후보가 전일 상태로 남음 → 이후 보호 경로를 움직이는 커밋(수동 dispatch의
data/cross_asset·data/scenarios 갱신, PR 머지 등)이 후보의 `protected_before` 대비
`compare_protected_append_only`를 `changed`로 만들어 pages 빌드에서 런타임 게이트 닫힘 →
`future_paths.json`의 semantic_reference가 null이 되고 프런트는 semantic mismatch fetch
오류로 "전망 데이터를 불러오지 못했습니다" 화면. 수동 scenario-refresh dispatch(run
33592600416)로만 복구되는 구조였다.

**결정 1 — 배포시점 재빌드.** `pages.yml`이 `_site` 생성 전에
`scenario-v5-2-build --force && scenario-v5-2-verify --replay`를 실행한다.
근거: ① 두 명령은 시크릿 0, 커밋된 데이터만 입력(FRED 키는 scenario-refresh의
`ai_fc scenario` 단계에만 필요) — 실측 빌드 47s + replay 검증 46s로 pages 총 빌드
~1분 → ~2.5분. ② `data/scenarios/candidates/`는 PROTECTED_PATHS가 아니고
`build_candidate`가 빌드 전후 보호 해시 불변을 자가 검증하므로 봉인 규약과 충돌 없음.
③ 산출물은 러너 워킹트리에만 존재(_site 입력 전용, 커밋 없음) — 배포 커밋에서 동일
명령으로 결정론 재현 가능(replay 검증이 같은 잡에서 강제). ④ 재빌드 실패는
continue-on-error로 배포를 막지 않는다(통계·v8 표면 갱신과 디커플). 데이터가 진짜
낡은 경우(cron 2+거래일 연속 누락 → age 게이트)는 재빌드로도 열리지 않으며 이는 설계
의도대로 닫힌다.

**결정 2 — 게이트 닫힘의 정직한 라우팅.** `split_future_paths`는 display 게이트가 닫힌
후보(경로 배열·semantic reference가 애초에 없음)에 `deferred_paths.required` 마커를 달지
않고 요약을 인라인한다. 프런트는 실패가 예정된 fetch 대신 renderFlow의 게이트 사유
분기에 도달한다. fail-closed 설계(후보 실패가 요청된 차트를 조용히 대체하지 않는다)는
그대로 — 어떤 차트도 대체 표시하지 않는다.

**비결정 (소유자 승인 대기).** 게이트 닫힘 화면에 "마지막 유효 후보 차트 + 기준일
라벨 + 게이트 사유"를 표시하는 완화(B안)는 fail-closed 표시 규약의 변경이므로
소유자 승인 항목으로 분리 제안만 한다 — 이 커밋은 구현하지 않았다.

## 2026-09-03 — R8-D4: 봉인 평가 지표 공개 확대 + 봉인창/전체창 분리 공시 (사용자 승인)

**결정.** 이미 1회 실시된 V8 봉인 평가(run `tsv8-sealed-64345a816b4857171915d5b8`,
disclosure #1)의 **요약값을 더 투영**해 `#timeseries` 검증 성적 탭에 공개한다.
승인 근거: 사용자 지시 2026-09-03 "2단계 다 승인이야. 진행해" — 계약
`sealed_evaluation.requires_explicit_user_signoff: true` 충족. 계약
`maximum_disclosures_per_model_version: 1`은 **평가 실행 횟수**를 묶는 조항이며,
이번 작업은 재평가·재조정 없이 같은 run의 산출 요약을 더 보여주는 것이다.

**핵심 시정 — 원장에 결과 블록이 둘이고, 화면은 그 구분 없이 전체창을 '봉인'이라 불렀다.**
- `summary` = 1,011원점 / 2007-01-05~2026-05-14. 이 중 626원점(기간별)이
  `development_window`(2007-01-01~2018-12-31) 안 — **모델을 고른 구간**이다. gate PASS.
- `sealed_summary` = 385원점 / 2019-01-04~2026-05-14, 실제 봉인창. status **hold**,
  사유 `필수 위기 국면 누락: great_financial_crisis_2008`(봉인창에 2008 원점 0개).
- R8-D2 승인 범위 문자열은 `contract_freeze_and_single_sealed_2019_plus_evaluation`으로
  2019+를 가리킨다. 따라서 **봉인창(385원점)을 out-of-sample 기준선으로 앞세우고**,
  전체창은 '개발기간 포함' 사실과 함께만 대조용으로 병기한다.

**공개 범위.** 봉인창 4기간 개선율·80%/50% 구간 적중률·DM p값·비교 기준선, 전체창
4기간 개선율·적중률(개발기간 포함 명시), 국면별 적중률 3종(2008은 원점 0개 → '자료 없음'),
실측 순위 6칸 빈도(공개된 per-origin 점수를 공개된 절단점으로 다시 센 결정론적 집계 —
새 확률 파생 아님), 21+63일 손실차 CI90, 전진(라이브) 성숙 원점·확정 건수.

**공개하지 않는 것.** 방향 적중률(매매 신호로 소비될 위험), MASE·RMSE·pinball·width,
first_touch 점수(임계 초과확률로 읽힘), distribution_selection(하이퍼파라미터 인구조사),
52점 롤링 CRPS(실제 span이 약 1년이라 '봉인 구간 추이'로 오인), scores[] 원본 반출.

**이것이 아닌 것.** 재평가·재조정 아님(모델 코드·계약 yaml 무변경, `src/ai_fc/timeseries_v8/`
1바이트 무변경). 챔피언 승격 아님. 게이트 판정 소스 교체 아님 — 표시 게이트는 종전대로
전체창 `gate_pass`이며(위기 국면 요건은 2008을 포함한 전체창에서만 충족 가능), 봉인창의
자체 판정 '보류'는 숨기지 않고 화면에 사유와 함께 인쇄한다.

**기록.** method_changes r22 (`method:timeseries-v8-sealed-metric-disclosure:2026-09-03:r22`),
계보 `website_data_lineage_v1.yaml`(artifact_gate 문구 시정 + shadow_resolutions.jsonl 등록).

## 2026-09-02 — B안 승인: 게이트 닫힘 시 마지막 유효 후보 표시 (사용자 결정)

**결정.** 같은 날 "Pages 배포시점 V5.2 재봉인" 항목에서 분리 제안으로 남긴 B안을
사용자가 명시 승인했다 (사용자 메시지 2026-09-02 "승인이야"). fail-closed 표시 규약은
"후보 실패가 요청된 차트를 **조용히** 대체하지 않는다"로 개정된다 — 명시 공시를 동반한
마지막 유효 후보 표시는 허용, 조용한 대체와 다른 모델 차트로의 자동 전환은 계속 금지.

**구현 계약.**
- `dashboard_projection`: 게이트 사유가 있어도 봉인 산출물이 **내부적으로 온전**하면
  (`validate_candidate(payload, root=None)` 통과 — 모델 해시·스키마·표시 계약 검증,
  환경 의존 검사 제외) 전체 내용을 유지한 채 `status="stale_last_valid"`,
  `display_eligible=false`, `fallback_mode="last_valid_candidate_with_explicit_disclosure"`,
  게이트 사유 목록을 공시한다. 내부 무결성이 깨진 산출물(모델 해시 불일치 등)은 종전대로
  내용 0의 `stale_or_invalid` — B안의 한계선.
- 프런트(renderFlow → renderScenarioV52): `stale_last_valid` + 경로 데이터 존재 시
  마지막 유효 차트를 렌더하되, 상단에 게이트 공시 배너(`scenario-v52-gate-notice`)로
  **기준일 라벨 + 게이트 사유**를 표시한다. 완전 실패 화면(`renderFuturePathsLoadState`)도
  이제 사유 문자열을 렌더한다(종전에는 불리언으로만 사용).
- `split_future_paths`: 분리 조건을 게이트 상태에서 **경로 데이터 존재**로 변경 —
  stale_last_valid는 정상 분리(semantic reference 존재), 내용 없는 요약만 인라인.
- read-model 계약(`read_model_contract.py`)의 scenario_v5_2 status enum에
  `stale_last_valid` 추가.

**적용 범위.** 배포시점 재봉인(결정 1) 이후 이 상태가 나타나는 잔여 경로는
① pages 재빌드 실패(continue-on-error 경로), ② cron 2+거래일 연속 누락(age 게이트) —
두 경우 모두 이제 빈 화면 대신 "기준일 명시된 마지막 유효 차트 + 사유"가 보인다.

## 2026-09-07 — 사이트 정밀 검수 2차: 표시 정직성 73건 수정 + 사용자 결정 대기 3건

**배경.** 1차 검수(2026-09-04, PR #160) 뒤 16개 렌즈 감사와 3표 적대적 검증으로 78건을 수집해
73건을 확정했다. 대부분은 화면이 근거보다 강하게 말하거나(만기가 지난 지평을 열린 전망으로,
유일한 표본외 실적을 "아직 없음"으로), 같은 양을 화면마다 다른 이름으로 부르는 문제였다.

**결정(구현).**
- **게이트 표본 단위 = 해소 문항.** `v_gate_status`/`v_gate_status_all`의 P2(30+)·P3(50+) 조건을
  `COUNT(*)`(재예측 회차 포함)에서 `COUNT(DISTINCT question_id)`로 바꾼다. `n_resolved`는 행 수
  그대로 두고 `n_questions`를 추가한다. 반복 업데이트는 독립 표본이 아니다(CLAUDE.md "해소 50문항+").
- **V8 만기 지평 사후 대조(표시 전용).** 투영이 원점 이후 실측을 별도 `realized` 배열로 싣고,
  빌드 시점에 만기가 지난 지평(1·5거래일)은 카드·표·밴드차트에 실측을 병기한다. 원점 경과
  거래일 수를 칩으로 상시 노출하고, 신선도 칩은 리터럴 pass가 아니라 5그룹 상태에서 파생한다.
  실측은 전진 원장(shadow_resolutions)에 **기입하지 않는다** — 원장은 별도 성숙 판정 경로.
- **라이브 실적 문장.** 확정 행이 있으면 그 결과(기준선 대비·방향·원점 수)가 굵은 문장이다.
  라이브 기준선은 예측 시점에 저장한 historical_simulation 하나로 고정임을 명기한다.
- **통계 물가 선행 패널 분리.** CPI(1~5%)와 WTI(±130%)를 한 축에 두던 차트를
  `inflation_lead_cpi`/`inflation_lead_commodities` 2장으로 나눈다(단위 무변경). 투영 데시메이션은
  균일 stride 대신 구간별 최소·최대 보존(점 수 상한 동일)으로 바꾼다.
- **CSP.** pages 모드에만 `Content-Security-Policy` meta를 넣어 스크립트(self·gc.zgo.at),
  스타일·글꼴(jsDelivr), 네트워크(self·GoatCounter API)를 제한한다 — 관리자 게이트 문구를
  기술적으로 강제한다. 자기완결 감사 HTML(embed)에는 넣지 않는다.
- **원장 등록.** V8 원장 5종(sealed_evaluations·shadow_forecasts·shadow_resolutions·
  holdout_scorings·development_experiments)을 `ledger_registry.yaml`에 등록한다.
- **배포 트리거.** pages.yml 경로 필터를 모듈 목록에서 `src/ai_fc/**`로 바꾼다.

**사용자 결정 대기(코드 무변경, 화면에는 사실만 공시).**
1. `multivariate_timeseries_v8.yaml`(동결 계약) `operational_gate`에 원점 경과 상한
   (`max_origin_age_sessions`, 예: 경고 1 / 보류 10)을 넣을지 — 계약 개정이라 표시 계층에서
   원점 나이만 노출했다.
2. V5.2 `clustering.py`의 S2 전용 드리프트 제거(`values -= mean`) — 대칭화 또는 유지. 화면에는
   "S2만 모양 이식, 평탄함은 생성 규칙"과 등록 클러스터 실측 중앙값을 병기했다.
3. V5.2 `engine.py` 분리 게이트가 상관의 부호 있는 감소만 보는 문제(0.963→−0.977 통과) —
   `abs()` 비교로 바꾸면 현재 후보의 게이트 판정이 뒤집힐 수 있어 화면에서 분리 증거로 쓰지
   않는다고 공시만 했다.

**적용하지 않은 것.** 시계열·시나리오 SVG의 모바일 글자 크기는 viewBox 글꼴 확대로는 해결되지
않는다(설계 글꼴에서 겹침 0, 확대 시 겹침 69·잘림 31 실측). 통계 차트(viewBox 780)만 570px
가로 스크롤로 11px를 회복했고, 나머지는 모바일용 재도화가 필요하다(KNOWN_LIMITS 후보).

## 2026-09-07 — 정밀 검수 2차 결정 대기 3건에 대한 사용자 선택

**결정 1 — V8 원점 경과: 2단 임계 (사용자 선택).** `multivariate_timeseries_v8.yaml`에
`origin_age_policy`(warn 1 / hold 10 거래일)를 추가한다. `operational_gate`는 `frozen_coordinates`에
포함돼 봉인평가·섀도 원장 전부가 그 `contract_hash`(7c56ee4e…)를 고정하고 있으므로, 정책은
동결 좌표 **밖**의 새 섹션으로 둔다 — 발행 신선도 정책이지 모델·게이트 좌표가 아니다(테스트로
해시 불변을 고정). 표시 계층(`timeseries_v8_display.load_projection`)이 빌드 시점 원점 경과가
10거래일 이상이면 None을 돌려 validation_pending 표면으로 페일클로즈하고, 그 아래에서는
칩에 `원점 경과 N/10거래일`로 임계를 함께 보인다. method_changes r23.

**결정 2 — V5.2 S2 드리프트: 유지 + 공시 (사용자 선택).** `clustering.py`의 S2 전용 평균 제거는
'드리프트 중립 균형 시나리오'라는 설계 의도(후행 결과의 강세 드리프트 유입 방지)로 유지한다.
모델 무변경. 화면 공시(S2 카드의 생성 규칙 + 등록 클러스터 실측 중앙값)는 PR #162로 이미
배포됨.

**결정 3 — V5.2 분리 게이트 지표: 재질의.** 사용자는 "일간 차분 상관으로 교체"를 골랐으나,
구현 전 기준선 커밋(7ef55604)의 후보로 같은 지표를 재계산한 결과 전제가 성립하지 않았다:
- S1-S2 일간 차분 상관: 기준선 +0.073 → 현재 +0.080 (변별력 없음 — 부드러운 p50 곡선의
  증분은 재설계 전에도 사실상 무상관이었다). "기준선 대비 물질적 감소" 규칙을 이 지표에
  걸면 통과 불가.
- S1-S2 표준화 로그경로 DTW: 기준선 0.118 → 현재 1.719 (재설계가 실제로 만든 분리를
  잡는 지표). 로그레벨 상관은 +0.967 → −0.977(부호 반전, |ρ| 증가 — 감사 지적 그대로).
- 새 사실: 현재 **S2-S3 DTW 0.123**(기준선 1.741) — S2와 S3의 표준화 형태가 거의 같아졌다.
  결정 2(S2 평균 제거 유지)와 상호작용하는 사항이라 함께 공시 대상.
계약이 고정 절대 목표를 금지(`fixed_numeric_target_prohibited`)하므로 대안을 다시 사용자에게
제시한다(아래 결정 항목으로 후속 기록).

**결정 3 — V5.2 분리 지표: 표준화 로그경로 DTW, 기준선 대비 규칙 (사용자 선택, 재질의 후).**
수용 검사를 `S1_S2_standardized_dtw_materially_above_baseline`으로 교체한다: 기준선 커밋
7ef55604의 S1-S2 DTW 0.1175 대비 +0.8704 이상(= 기준선에서 형태가 달랐던 쌍의 최소 DTW 1.7408의
절반 — 절대 목표 금지 조항 준수). 현재 후보 1.7185로 통과. 로그레벨 상관은 퇴역하되
`baseline_comparison.superseded_log_level`에 투명성용으로 남기고, S2-S3 DTW(0.123)를 함께 공시한다.
경로·가중치·확률 무변경(진단·수용 규칙만) — 후보는 `scenario-v5-2-build --force` + replay 검증으로
재봉인. 계약 2종(`scenario_v5_3_separation.yaml` baseline 블록, `scenario_v5_2_weights.yaml`
distinctness 블록), 엔진·검증기·감사 보고서·대시보드 문구·테스트 갱신. method_changes r24.

## 2026-09-08 — V13-D2′: V13-VOL 계약 사전등록 개정 — 지속성 기준선(PB)·G2 champion 규칙·cross-fit isotonic(h63)·홀드아웃 게이트 정의 (사용자 결정)

**배경.** 외부 검토(`CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md`, 42파일 세션 리뷰팩 재계산)는 V9~V12
판정을 전부 유지하고 V13-VOL을 캠페인 유일의 진짜 긍정으로 인정하되, EWMA-logit이 곧 지속성
피처라 "기후 대비 통과"만으로는 '자명한 스킬'과 구분할 수 없다고 지적했다(§C-1). 홀드아웃을 보기
전인 지금이 임계·기준선을 사후 완화 없이 고칠 마지막 시점이다(§D-3, V12-D2와 같은 논리).

**결정.** 사용자 지시 "t2 숨긴패널까지 진행하고, 라이브 카드 노출 진행 후 위 첨부파일에 대한 것을
전수조사 및 분석해서 설계 계획을 작성한 후, 정밀하게 구현하는 것을 시행해." + 계획 승인 +
구현 순서 선택 "거버넌스 순"(사전등록 → C-1 → 동결 → T2 → T3). `multivariate_timeseries_v13_vol.yaml`에
개정 A1~A7을 적용한다 — 원문 `gate:` 블록은 1바이트도 바꾸지 않는다.
- **A1 자명 기준선(D-2).** `baselines.persistence_pb` = logit(P | 당일 수준 1피처) 등록. `gates.G2`
  champion 규칙: (a) EWMA가 PB 대비 양방향 CI90 하한>0 ∧ 증분 y-block 귀무 ≤0.10 → EWMA,
  (b) 아니면 PB가 기후 대비 양방향 통과 ∧ 귀무 ≤0.10 → **PB**(단순 우선), (c) 아니면 HOLD.
  근거: 중첩 모형(PB⊂EWMA)은 동률=단순 모형; 마진 δ>0은 magnitude 임계(계약 금지), δ=MDE는
  부호검정으로 퇴화. 홀드아웃의 '비열화'는 별도 정의(PB 대비 CI90 상단 ≥0).
- **A2** h63 오보정 셀(rel≈0.08) 파생층 cross-fit isotonic(k=5 연속 블록, embargo h, PAV) +
  사전등록 fallback(iso 유의 열위면 raw). 게이트 판정은 raw.
- **A3** 홀드아웃 게이트 G1(기후 CI90 하한>0) ∧ G2(PB 대비 CI90 상단≥0) ∧ G4(홀드아웃 y-block
  ≤0.10), G3 신뢰도 보고. label-complete origins, `observation_time ≤ 2018-12-31` 절단, frozen
  artifact만(재적합 금지), 결과 무관 원장 append, hold_condition(전 셀 HOLD면 미소모).
- **A4** `holdout_maximum_finalists: 3`, 사전등록 finalist `[V13VOL_champion]` 1개, 승인·원장 경로.
- **A5** prohibitions 3건 신설. **A6** `evaluations_spent` 0→2 정정(원장 2행 대사, 완화 아님).
- **A7** 표시 계층 사전등록: 신선도=NYSE 거래일 달력(`missing_sessions ≤ 1`), 80% 대역=델타법
  (사다리 se는 손실차 se — P의 se가 아님), 전용 read-model 키 `timeseries_v13_vol`, 24KB 예산,
  동결 artifact 이름을 champion 중립 `champion_coefficients.json`으로 정정(표시 설계서 §3 원문
  무수정), `publication.display_tier` 한 줄 전환(T0→T2→T3, T4 값 없음).
- 원장 등록 4종(`ledger_registry.yaml`) + 승인 원장 `data/timeseries_v13/ledgers/approvals.jsonl` 신설.

**이것이 아닌 것.** 홀드아웃 소모 아님(V13-D3 — C-1 결과 보고 직후 별도 질문·정지, 승인 원문
없이는 verb 자체가 없다). 임계 완화 아님(unchanged 영수증). 표시 승격 아님(V13-D4/D5). 배선
아님(V13-D6). 봉인 V8/V2 무접촉.

**fail-closed 규약.** 결과 전 커밋 hash를 `amendments_applied.V13-D2prime.prereg_commit`에 후속
1줄 커밋으로 기입. `gates.champion`은 C-1 전 null — 테스트가 원장과 대사. HOLD 셀은 finalist 제외.
`holdout_execution_path: absent_by_construction`인 동안 cli에 홀드아웃 verb가 없음을 테스트가 고정.

**기록.** method_changes r25 · approvals r1(V13-D2prime) · 계약 `amendments_applied.V13-D2prime`.

## 2026-09-08 — GOV-1: main 잠금 우회 금지 규칙 + 2026-09-08 리프스펙 FF 푸시 사후 기록 (사용자 결정)

**사후 기록(사실).** `main`은 Codex 워크트리 `C:/Users/91ssj/.codex/worktrees/7e4e/ai-investing`에
0c14900f(2026-08-07)로 체크아웃되어 잠겨 있었다. 로컬 `main` 갱신이 "already used by worktree"로
거부되자 `git push origin claude/v13-next:main`(리프스펙 fast-forward)으로 우회했다 —
`origin/main` reflog: 4033ec6e(2026-09-08 11:45:35 +0900 update by push), d6b72554(12:43:52 +0900
update by push). 봉인 무변경·CI(verify·pages) 통과·손실 0이었으나, 잠금의 목적(직렬화)을 무력화한
것은 사실이다(외부 검토 §A-6 경고, §D-4).

**결정.** 사용자 선택 "브랜치 push + PR (권장)". 규칙: ① push 전 `git worktree list`로 `main`
보유 워크트리를 확인한다. ② 다른 워크트리가 `main`을 보유하면 **브랜치 push + PR만** 허용 —
`git push origin <ref>:main` 및 어떤 우회도 금지. ③ 해제는 잠금 소유자의 해제 또는 사용자의 명시
인계 뒤에만. ④ 위반은 되돌리지 않고 이 문서에 사후 기록한다.

**이것이 아닌 것.** 4033ec6e·d6b72554의 되돌리기 아님(FF·CI green·내용 정당). git hook 강제 아님
(설정 변경은 별도 결정).

**기록.** approvals r1(GOV-1). 이 규칙은 이번 작업(V13-D2′ 이후 모든 커밋)부터 적용 — 이후 push는
`claude/v13-next` 브랜치 + PR.

## 2026-09-08 — V12b-park: 경로 생성기 트랙(T-B) 폐기 → 보류(파킹) 재라벨 (사용자 결정)

**배경.** 2026-09-07 사용자 결정은 '폐기'(`docs/review/V12B_TERMINATION_20260907.md`). 외부 검토
§A-4 수정②: T-A 게이트 문구("실패 시 어떤 재개도 금지")가 과도하게 넓었다 — T-B는 건전 y-블록
귀무로 검정 가능해 T-A 실패에 종속되지 않는다. 다만 크기 온건(VR(5)=0.874)·비용 근거의 종결은 정당
→ "폐기가 아니라 보류".

**결정.** 계획 승인으로 재라벨. 종결 문서는 무수정(append-only 정신), `docs/review/V12B_PARKED_20260908.md`
신설. 재개 조건 4항: ① 일중 데이터 확보(FirstRate 계획 문서) ② 새 사전등록(블록 재표집 ℓ_z /
AR(1) φ, ℓ_z=1·φ=0 = E0 항등) ③ 건전 y-블록 귀무(T-A 무관) ④ CRPS 게이트 무손상 제약. 예산 0.

**이것이 아닌 것.** 재개 아님. 예산 배정 아님. FirstRate 구매 결정 아님(FR-1 후순위, 사용자).

**기록.** approvals r1(V12b-park).

## 2026-09-09 — P0·P1: 국면(에피소드) 가드 신설과 라이브 전진 채점 개통 (설계도 v1 수립)

**배경.** 사용자가 외부 검토관 산출물(`ROADMAP_BLUEPRINT_v0.md`·`REVIEW_VERDICTS.md`)을 "그대로 반영하지 말고
최적 경로를 스스로 판단하라"고 지시했다. 3갈래 실측 조사에서 외부안의 **다섯 주장이 뒤집혔다**(설계도 부록 B).

**결정 1 — 퇴화 가드는 사건 수가 아니라 국면 수로 건다.** 외부안의 `min(사건,비사건) ≥ 20`은 9/9 셀이 통과해
(최소 27) 아무것도 막지 못한다. 라벨이 h영업일 전방창이라 이웃 원점이 겹치므로 유효 자유도는 **연속 국면 수**다.
실측(`tools/v13_guard_mde.py` → `data/timeseries_v13/vol/guard_mde_design.json`): **9셀 중 6셀이 국면 ≥5 미달**,
vix30_h21 후반창 사건 109일이 **1국면**(2011-07-06~12-07), vix30_h63 151일도 1국면, rv_h63 전반창 비사건 27일이
1구간. 깨끗한 셀은 vix25_h5·rv_h5·rv_h21 셋뿐이다. CI90 폭이 국면 희소성을 그대로 따라간다(1~2국면 반창의 폭
0.154~0.169 vs 10국면 이상 0.025~0.066).
**이것이 아닌 것.** 소급 판정 변경이 아니다. 임계를 설계창을 본 뒤 정했으므로(공시) 사용처를 엄격히 제한한다 —
이미 실행된 rung 판정과 `gate.primary`·홀드아웃 G1~G4 산술은 **그대로**이고, 가드는 게이트를 느슨하게 하는
방향으로는 절대 쓰이지 않는다. 쓰이는 곳은 셋: ① 카드 `▲ 국면 표본 얇음` 마커 ② 홀드아웃 PASS 여도 배선 불가
③ 홀드아웃 verb가 **실행 시점에** 홀드아웃 창에 적용(사전 점검은 미열람 위반이라 불가능하다).

**결정 2 — 라이브 전진 채점 개통.** `live_forward_gate`(2026-09-08 사전등록, 어떤 원점도 성숙 전)의 채점 verb를
구현했다(`timeseries-v13-vol-resolve`). 성숙은 달력이 아니라 아카이브 거래일 인덱스로 판정하고(V8 승계), 기후는
계약 고정값을 쓰며, **강등 판정은 하지 않는다**(표본 부족 표시까지). 규칙은 결과 전에 고정됐고 verb는 실행만 한다.

**결정 3 — 상태를 손으로 관리하지 않는다.** 통치 설계도 `docs/design/mts_program_blueprint_v1_260909.md`(1,125줄,
P0~P7 단계·게이트·승인·정지 규칙)와 `tools/roadmap_status.py`(원장·계약에서 파생, 읽기 전용, 스케줄 금지).
"현재 단계: P1" 같은 줄을 문서에 두지 않는다 — 낡은 상태 파일이 잘못된 다음 행동을 부르기 때문이다.

**기각한 외부안.** ① 홀드아웃을 무료 탐색 뒤로 미루기 — 계약이 finalist를 이미 '현 champion'으로 지정했고,
탐색 먼저는 오히려 새 finalist 등록(개정)이 필요하다. ② 옵션 형상 즉시 착수 — VVIX·SKEW는 봉인 V2 아카이브에
없고(V4 연구 스토어 전용) 표시 라이선스 라벨이 3중 모순이다. ③ V8 섀도 케이던스 격주→일간 — `evaluation`이
`frozen_coordinates` 안이라 contract_hash가 `7c56ee4e…`→`4d301ae2…`로 **봉인이 깨진다**. 게다가 게이트 단위는
origin이 아니라 세션 126이라 애초에 단축 대상이 아니다.

**부수 진단(P1b).** V8 섀도 정체의 원인은 케이던스가 아니라 **DTWEXBGS가 2026-08-28에서 12일 정지**한 것이다
(다른 4계열은 09-04). 원점은 필수 계열의 공통 마지막 날짜라 이 계열이 전진 속도를 지배하며, 최근 유입 간격은
약 2주다. 수집 실패가 아니라 소스 발행 속도다 — `docs/review/V8_SHADOW_ORIGIN_STALL_20260909.md`, 조치 없음.

**기록.** method_changes r30 · KNOWN_LIMITS 34·35·36 · 계약 `degeneracy_guard`·`live_display.episode_thin_cells`·
`live_forward_gate.execution_path: named_verb_guarded` · 판정서 `docs/review/V13_GUARD_MDE_20260909.md`.

## 2026-09-09 — V13-D3: 홀드아웃 1슬롯 소모 — 부분 통과(9셀 중 3셀) (사용자 승인)

**결정.** 사용자 승인 원문: `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b`
(영수증 `v13-approval:V13-D3:2026-09-09:r1`, 11:35:57 KST — 시각은 도구 호출 기록에서 가져왔다).
계약이 정한 순서대로 영수증 → `holdout_execution_path: named_verb_guarded` 개정 → verb 1회 → 결과 무관 원장 append.

**결과 — partial.** 통과 3셀(`vix25_h21`·`rv_h5`·`rv_h21`), 실패 6셀. family P(k≥3|n=9,p=0.05)=0.0084로
통과 3셀은 다중비교를 견딘다. 실패 6셀 중 **4셀은 기후 대비로는 통과했으나 건전 y-block 귀무에서 무너졌다**
(vix30_h5 귀무 통과율 1.000 · vix30_h21 0.965 · rv_h63 0.805 · vix25_h5 0.125). 사건이 드물면 어떤 매끄러운
확률이든 고정 기후상수를 이기므로 BSS가 커 보이지만 라벨을 섞어도 같은 성적이 난다 — T-A에서 배운 '자명한
이득'의 변동성 판이다. **P0의 국면 가드가 지목한 셀(vix30 3종·rv_h63)이 정확히 그 셀들이다.**
상세: `docs/review/V13_HOLDOUT_VERDICT_20260909.md`.

**표시.** 실패 6셀의 숫자를 카드에서 내렸다(표에 "—"). caveat는 "홀드아웃 부분 통과(9셀 중 3셀만 통과 —
나머지는 표시하지 않습니다)", 칩은 "홀드아웃 부분 통과 3/9". 이 페일클로즈는 2026-09-08에 미리 구현·검증해 둔 것이
그대로 작동한 것이다.

**배선(V13-D6)은 열리지 않는다.** 레지스트리에서 9셀로 채점 가능한 질문은 `vix-25-90d` 하나인데 그 질문에
대응하는 `vix25_h63`이 **실패**했다(G1 CI90이 0을 포함). 배선 자격이 있는 두 셀(`rv_h5`·`rv_h21`)에 대응하는
등록 질문은 없고, 새 표적 추가는 계약이 금지한다. **검증된 것과 쓰임이 있는 것이 겹치지 않았다** — 실패가
아니라 측정 결과다.
**이것이 아닌 것.** 트랙 종료 아님(3셀은 표본외 검증됨). 배선 영구 불가 아님(질문 레지스트리 신설로 열 수 있다).

**자원.** 홀드아웃 슬롯 1/3 소모(2 잔여) · 봉인 1/1 미사용 · 개발 예산 3/8.
**기록.** method_changes r31 · 계약 `amendments_applied.V13-D3`·`publication.holdout_*` · 원장 1행 · 테스트 7건.

## 2026-09-09 — V13-D6: EXIT base rate 배선 **보류** (사용자 결정)

**결정.** 사용자 선택 "보류 — 전진 표본 쌓고 재판단". 홀드아웃 통과 셀에 맞춰 새 등록 질문을 지금 만들지 않는다.

**왜.** 통과 셀은 `vix25_h21`·`rv_h5`·`rv_h21`이고 배선 자격(홀드아웃 PASS ∧ 설계창 국면 가드 통과)은 RV 두 셀뿐이다.
이에 대응하는 등록 질문이 없고, 유일하게 대응하던 `vix-25-90d`의 셀(`vix25_h63`)은 홀드아웃에서 실패했다.
여기서 질문을 신설하면 **통과한 셀에 맞춰 질문을 짜는** 모양이 된다 — 사전등록 정신에 어긋난다.
대신 라이브 전진 채점이 셀당 60원점에 닿으면 그때 **독립 표본**으로 배선을 판단한다.

**이것이 아닌 것.** 배선 영구 불가 아님. 트랙 종료 아님 — 3셀은 표본외 검증됐고 카드에 계속 표시된다.
질문 신설 금지도 아님 — 전진 증거가 쌓인 뒤 같은 결정을 다시 연다.

**다음 조건.** `vol_live_resolutions.jsonl`의 셀별 성숙 원점이 60에 도달(계약 `live_forward_gate`).
현재 0/60이며 원점은 하루(2026-09-04)뿐이다. `tools/roadmap_status.py`가 이 조건을 추적한다.

## 2026-09-09 — P4: 무료 정보집합 소진 — 매크로 피처블록 27검정 전부 '측정된 영'

**배경.** 봉인 아카이브에 있으면서 아직 쓰이지 않은 계열은 DGS2·DGS10·DTWEXBGS·FED_EBP 넷뿐이었다.
적재 0·비용 0·라이선스 위험 0으로 시험 가능한 **마지막** 정보집합이다. 사전등록 `rung4_macro_blocks`
(결과 전 커밋 7a868424) 후 실행.

**결과.** 3블록 × 9셀 = 27검정에서 **채택 0**. 전부 양방향 CI90 하한 > 0 단계에서 탈락(measured_zero).
family P(k≥0|n=27)=1.0000. 가장 나았던 조합(vix30_h63 × 기간스프레드)조차 early→late +0.030, late→early
**−0.102**로 방향이 뒤집힌다 — 한 방향만 봤다면 채택했을 전형적 실패 모양이다. EBP는 월간·2개월 지연이라
계단 함수가 되어 가장 크게 악화시켰다(최대 −0.214).

**의미.** ① V9가 같은 계열을 *가격 분포(CRPS)* 표적에서 무효로 판정했는데, 표적과 손실함수를 모두 바꾼
*사건 확률(Brier)* 에서도 같은 결론이 나왔다. 두 표적 독립 영이다. ② **무료 경로 소진** — 남은 정보집합은
전부 외부·유료(옵션 표면·일중)이며, 이후 진전은 데이터 구매·라이선스 회신에 종속된다. ③ PB의 지위가
굳었다: HAR 0/9 · EWMA 0/9 · 매크로 0/27. 세 확장이 전부 당일 수준 하나를 못 이겼다.

**PIT 규율.** 국채 금리는 과거 행의 `available_at`이 당일 22:00 UTC(H.15 발행 후)로 **실측 검증**되어
지연 0. 달러·EBP는 `available_at`이 2026 수집 시각이라 PIT 증거가 없어 각각 10·42세션 보수 지연을 걸었고,
지연 로직의 미래 정보 누수를 테스트 3건으로 고정했다.

**자원.** 개발 예산 4/8 · 홀드아웃 1/3 · 봉인 0/1 · 새 창 0. 채택 0이라 champion 재판정·재동결·추가 홀드아웃 없음.
**기록.** method_changes r33 · 판정서 `docs/review/V13_VOL_RUNG4_MACRO_VERDICT_20260909.md` · 원장 4행.

## 2026-09-09 — 라이브 워크플로 커밋 단계 결함 수정 (C1 축적 복구)

PR #169 병합 이후 `timeseries-v13-vol-live`가 3회 연속 실패했다. 해상 원장을 `git add` 목록에 넣었는데
성숙 원점이 0이라 파일이 없었고, 없는 경로를 `git add` 하면 `fatal`로 죽는다. 그 결과 포인터는 발행되지만
커밋되지 않아 **라이브 전진 표본(C1)이 축적되지 않았다** — C1은 완성 조건 중 유일하게 시간이 필요한 항목이라
정지가 곧 손실이다. 허용 목록을 변수로 두고 존재하는 경로만 add 하도록 고쳤고(허용 범위·가드 정규식 무변경),
테스트는 리터럴 `git add` 줄 대신 허용 목록과 존재 검사 루프를 고정한다. PR #173 병합 후 재실행 성공.
**교훈**: 산출물이 아직 없는 단계의 파이프라인은 '없음'을 정상 상태로 다뤄야 한다.

## 2026-09-08 — 사용자 결정 대기 (V13 트랙 · 데이터)

1. **V13-D3 홀드아웃 1슬롯 소모.** C-1(rung-3 PB 기준선) 결과·finalist 표·hold 판정을 보고한 뒤
   질문·정지. 승인 원문 형식: `V13-D3 홀드아웃 1회 소모 승인 finalist=<finalist_id>` (literal
   `V13-D3`·승인·정확한 finalist_id 포함). 승인 시에만 approvals receipt → 계약
   `holdout_execution_path: named_verb_guarded` 개정 커밋 → verb 1회 → 결과 무관 원장 append.
   자동 실행 없음. hold_condition(전 셀 HOLD)이면 소모하지 않는다.
2. **V13-D6 EXIT 트리거 base rate 배선.** 홀드아웃 PASS 셀 한정. `volatility_v13_auto.md`(스킬/사람
   경로) + `due` 괴리 표시 전용. LLM digest 주입·산술 결합·자동 재예측 금지.
3. **V12-D4 CBOE DataShop QQQ 질의 발송.** 사용자 직접 발송(`docs/design/v13_cboe_datashop_qqq_request_260907.md`).
   외부 검토 권고 "지금 발송". 발송 시 12-8 형식(날짜·수신처·원문·§2b 약관 캡처 sha256) 기록.
4. **FR-1 FirstRate 구매.** 저비용·후순위(반대 아님). 구매 시 라이선스 캡처 12-6/12-8 형식
   (`data/intraday/receipts.jsonl`). 약관 재확인(§A-3: FirstRate 표시 허용·Cboe §2b·QQQ 오버레이)은
   소유자 원문 캡처 후 진행.

## 2026-09-08 — V13 C-1 결과 기록: champion = persistence_pb 전 9셀 (규칙 기계 적용 — 결정 아님)

rung-3(`docs/review/V13_VOL_RUNG3_PB_VERDICT_20260908.md`, 예산 3/8, 사전등록 커밋 afec214e·도구 29eaa2bc):
EWMA-logit 이 당일 수준 단독 로짓(PB) 을 양방향으로 이긴 셀 **0/9** (h63 두 셀은 한 방향 유의 열위), PB 는 기후 대비
9/9 양방향 CI90>0·건전 귀무 ≤0.033 → V13-D2′ G2 규칙 (b) 그대로 **champion = persistence_pb**, finalist
`V13VOL_champion_aec80c65038b`, HOLD 0(hold_condition 미발동). h63 cross-fit isotonic 은 사전등록 fallback
발동(iso 유의 열위) → raw 유지. 스킬 라벨은 "당일 변동성 수준의 지속". method_changes r26(`champion_changed: true`).
**V13-D3(홀드아웃 1슬롯)** 은 이제 조건 ①~④ 충족 상태 — 계획 순서대로 T2/T3 표시 뒤 사용자에게 질문한다.
승인 원문 형식: `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b`.

## 2026-09-08 — V13-D4 · V13-D5: 변동성 이벤트 기준율 카드 T2 숨김 패널 → T3 라이브 카드 (사용자 결정)

**결정.** 사용자 지시 "t2 숨긴패널까지 진행하고, 라이브 카드 노출 진행 후 …" + 선택 "지금 T3 (요청대로)"
(홀드아웃 선행 안 함). 계약 `gates.armed: true`(게이트 산술·규칙 0바이트 변경), `publication.display_tier`
t0→t2→**t3_live_card**. 전제: 동결 계수 핀(sha256 51815bde…, 반창 대사 max|Δ| 2e-15) · champion
persistence_pb 전 9셀 · 표시 모듈(`timeseries_v13_vol_display.py`, 항상 dict, 마지막 값 캐시 없음) ·
읽기모델 전용 키 `timeseries_v13_vol` 가드 · 24KB 예산(실측 4KB) · 라이브 파이프라인(`timeseries-v13-vol-latest/verify`,
포인터 `vol_latest.json` live 2026-09-04, 원장 `vol_live.jsonl` 1행) · 워크플로 `timeseries-v13-vol-live.yml`
(화~토 03:40 UTC, pages·verify 트리거 등록) · 계보 `volatility_base_rate_v13`.
**X1 이름충돌 6항 검수(탭 활성 상태, 1400/620/375 스크린샷):** ① 명칭 '변동성 이벤트 기준율'·셀 '기준율'(예측
아님) ② 회색 배지 '수치모델 · 당일 수준 지속(PB)' 상시 ③ 열 머리 '5/21/63영업일(≈1주/1개월/90달력일)'
④ caveat lead 상시 — '설계창(2007~2014) 스킬 · 홀드아웃 미검증 · 참고 의견 — 매매 신호가 아닙니다' ⑤ 역할 문장
(vix-25-90d 의 base rate 공급원, 정의·지평·산출 차이 명시) + 괴리 칩 'AI 예측 36% 대비 −8%p' 표시만 ⑥ 결합·평균
산식 0. h63 셀 '▲ 보정 약함' 텍스트 마커 + [80%] 계수 불확실성 대역. 모바일(≤620) 지평 탭 — 전역
`table{min-width:900px}` 상속으로 63열이 화면 밖으로 밀리던 결함을 `.v13-vol-card .v13-vol-table{min-width:0;table-layout:fixed}`
로 수정 후 재검수 통과.

**이것이 아닌 것.** 홀드아웃 소모 아님(V13-D3 — 별도 질문). 배선 아님(V13-D6). 가격 카드(V8 `timeseries` 슬롯)
무접촉. 매매 신호 아님. T4(자본 결정)는 tier 값 자체가 없어 구조적으로 차단.

**공시(D-g).** T2 '숨김 패널'은 UI 수준 숨김이며 payload 비공개가 아니다 — 숫자는 공개 `data.json`
`timeseries_v13_vol` 키에 실린다. T3 에서는 5번째 탭·레일 항목이 활성화되고 caveat lead 의 '홀드아웃 미검증'이
굵게 상시 표시된다(읽기모델 가드 `holdout_caveat_bold` 강제).

**fail-closed 규약.** 숫자는 네 게이트(설계 증거·무장·계수 핀 3자 일치·거래일 신선도 missing_sessions ≤ 1, 빌드
시점 재평가) 전부 성립 시에만. 하나라도 어긋나면 HOLD + 사유, 마지막 값 재사용 없음. 계수 파일은 `ledger_registry`
immutable/frozen — 바이트 변경은 CI violation.

**기록.** method_changes r27 · approvals r1(V13-D4)·r1(V13-D5) · 계약 `amendments_applied.V13-D4/V13-D5`.

**정정(2026-09-08 16:25, 푸시 전 적대적 검토 governance 렌즈 3/3).** 위 approvals r1 두 행의 `approved_at`
15:05:00 은 14:59:22 에 적힌 **합성 시각**이며 사용자 이벤트가 아니다 — 무장(14:54:04)·라이브 포인터(14:54:13)·
T3 전환(14:58:03) 보다 뒤라 "승인이 집행에 선행" 의 증거로 쓸 수 없었다(method_changes r27 의 `occurred_at` 도 동일).
원장은 append-only 라 r1 을 고치지 않고 **r2 를 덧붙였다**: 실제 동의 = AskUserQuestion 선택(13:53:55) + 계획
승인(ExitPlanMode 14:14:41, 계획 파일 Phase E 에 V13-D4/D5 명시) → 집행은 그 뒤. 계약 `approval_receipt` 는 r2 로,
테스트는 영수증 `approved_at` 비미래 + 계약이 superseded 행을 가리키지 않음을 고정. method_changes r28.
교훈: 영수증 시각은 항상 이벤트 시각(도구 호출 기록)에서 가져오고, 절대 손으로 적지 않는다.

**정정 2 — band80 부트스트랩 좌표 불일치 (같은 검토, numerics 렌즈).** `block_bootstrap_cov` 가 재표집마다
재표준화한 β_b 의 공분산을 취해 동결 μ/σ 좌표의 델타법과 어긋났다(대역 과대). 전체 표본 (μ,σ) 로 고정 표준화하도록
수정하고 **재동결**(sha256 `51815bde…` → `1a857850…`, 반창 대사 2e-15 동일, 확률 p 무변경 — 대역만 좁아짐, 예:
vix25_h63 [18%,38%]→[21%,36%]). 재동결은 라이브 원장에 새 행(run_id 에 계수 sha 8자 포함)으로 남고 이전 행·이전
artifact 바이트는 git 이력에 보존. 함께 고친 것: 홀드아웃 FAIL/partial 과 계약 disarm 의 빌드 시점 페일클로즈,
비-dict 포인터 페일클로즈, verify 의 원장↔포인터 셀 교차검사, 라이브 워크플로의 V2 refresh 완료 종속(workflow_run),
라이브 전진 게이트 사전등록(`live_forward_gate`, 첫 원점 성숙 전), 파이프라인·신선도 테스트 신설, 부호검정 강화.
method_changes r29.

## 2026-09-09 — B안(게이트 닫힘 명시 공시 배너) 철회 + 대시보드 홈 문구 정리 (사용자 결정)

**결정.** 2026-09-02 "B안 승인: 게이트 닫힘 시 마지막 유효 후보 표시" 에서 도입한 배너
(`scenario-v52-gate-notice` — "게이트 차단 · 마지막 유효 후보" + 기준일 라벨 + 원문 게이트 사유
문자열, 예: `candidate age 3 trading days exceeds 1`)를 사용자 지시(2026-09-09)로 완전히 제거한다.
근거: 사용자가 원문 게이트 사유 등 내부 진단 문구를 화면에서 볼 필요가 없다고 명시적으로 판단.
이는 B안의 핵심 조건("조용한 대체는 금지, 명시 공시는 필수")을 뒤집는 것임을 사용자에게 고지했고
AskUserQuestion 으로 재확인 후 "완전 삭제"를 선택받았다.

**변경 내용.** `renderScenarioV52`(dashboard.js)에서 `runtime_gate.display_eligible===false` 분기의
배너 삽입 블록을 삭제 — `stale_last_valid` 후보는 이제 아무 공시 없이 마지막 유효 차트를 그대로
렌더링한다(내부 `runtime_gate`/`status` 데이터 자체는 그대로 유지 — 삭제된 것은 UI 표시뿐). CSS
`.scenario-v52-gate-notice` 규칙 제거. 대시보드 홈(TODAY 히어로)의 기술적 disclaimer 문단
("시나리오 조건부 분포와 공식 질문 확률은 서로 다른 공간이며…")도 같은 요청으로 함께 제거.

**한계.** 이제 사용자는 미래 탐색 탭이 최신 후보인지 마지막 유효 후보인지 화면만으로 구분할 수
없다. `runtime_gate.display_eligible`/`reasons` 는 페이로드에는 남아 있으므로 필요 시 원본
데이터로 확인 가능. 캘리브레이션 무결성(예측·원장 파일)에는 영향 없음 — 이 배너는 표시 계층
전용이었다.

**기록.** `src/ai_fc/dashboard_parts/dashboard.js`, `dashboard.css`,
`src/tests/test_scenario_v5_2.py` 갱신.

## 2026-09-09 — scenario_tracker 페이로드 예산 8KB→9KB (사용자 결정)

**문제 (실측 2026-09-05, 2026-09-08 scenario-refresh 실행 실패).** 보조 지표
`scenario_tracker`(`market_extensions.py`)의 payload가 `TRACKER_BUDGET_BYTES=8_000`
을 각 37바이트·초과분 초과해 `MarketExtensionError` 로 워크플로 최종 단계가 실패
표시됐다. 커밋된 스냅샷은 7,828바이트로 여유가 172바이트뿐 — signals(9개
방향성 신호)·realty_income_hypothesis(4개 조건) 본문 길이가 날짜마다 자연
변동하는 정상 콘텐츠이며 버그가 아니다. 예산 자체가 실측 변동폭에 비해 너무
빡빡했다. 핵심 asof 갱신·커밋·푸시는 이 실패와 무관하게 이미 정상 진행 중이었음
(파이프라인 안전에는 영향 없었음).

**결정.** `TRACKER_BUDGET_BYTES` 를 8,000 → 9,000 바이트로 상향. 이 예산은 외부
하드 제약(고정 크기 API 등)에 묶여 있지 않은 내부 폭주 감지용 sanity guard —
현재 실측치(~7.8~8.0KB) 대비 여유를 두면서도 실제 폭주는 계속 잡아낸다.
`validate_scenario_tracker` 오류 문구·`test_market_extensions.py`
(`test_tracker_budget_is_enforced`)의 "8KB budget" → "9KB budget" 동시 갱신.

## 2026-09-09 — '세 가지 시장 경로' 실제 기록 라인의 한 달 공백 브리지 (사용자 결정)

**문제 (실측, 사용자 보고).** 미래 탐색 GRAPH 01("세 가지 시장 경로")의 검은 실선(실제
기록)이 8/7 이후로 끊겨 보였다. 원인: V5.2 챔피언 엔진(`engine.py`)의 연구용 통계
프라이어는 `ANCHOR_DATE=2026-08-07` 로 사전등록·해시 고정된 point-in-time 역사
데이터베이스(`history_manifest`)에서만 나온다 — 이는 의도된 동결(라이브 포워드
원칙, 사전지식 오염 방지)로 절대 건드리지 않는다. 문제는 표시 전용 `historical_actual`
트렌드 라인 조립부(`generate_prior` 내 `actual_dates`/`actual_values`)가 이 동결된
8/7 종가 뒤에 **오늘자 라이브 anchor 한 점만 이어 붙이고 그 사이 20여 거래일을
비워둔 것** — 계산·캘리브레이션과 무관한 순수 조립 버그.

**결정.** `_live_actual_gap()` 헬퍼를 추가해 동결 종가(8/7) 이후 ~ 라이브 anchor 사이의
거래일을 `data/scenarios/archive/*.json`(scenario-refresh 가 매일 커밋하는 실측 종가)
에서 읽어 채운다. 프라이어의 통계 계산(에피소드 선택·클러스터·경로 생성)은 여전히
동결 데이터만 사용 — 이 브리지는 순수 표시용이며 `historical_actual` 배열에만
영향을 준다. 아카이브에 특정일이 없으면(주말·공휴일·과거 커밋 누락) 그 날은 그냥
건너뛴다 — 값을 보간·추정하지 않는다. 아카이브 자체가 없거나 오늘자 파일이 아직
없으면(빌드 시점 레이스) 예전 동작(anchor 단일 점 추가)으로 안전하게 폴백한다.

**한계.** 과거 scenario-refresh 실행이 실패해 특정 거래일의 archive 파일이 아예
없었다면(예: 9/3) 그 날짜는 여전히 비어 있다 — 이 커밋이 소급 채우지 않는다. 차트의
`gapBefore` 로직(10일 초과 공백만 끊어 그림)은 유지되므로 이런 단일 결측일은 시각적
문제를 일으키지 않는다.

**기록.** `src/ai_fc/scenario_v5_2/engine.py`(`_live_actual_gap`),
`src/tests/test_scenario_v5_2.py`(3개 테스트 추가) 갱신.

## 2026-09-09 — V5 protected 격리 판정을 '동결 매니페스트'에서 '체크아웃 대비 워킹트리'로

**문제 (실측).** `timeseries-v5-refresh` 가 2026-08-25 부터 12일 연속 실패했다. compute
잡의 `timeseries-v5-verify` 가 exit 1, `protected_non_mutation.ok=false`, errors 18건이
전부 `protected drift:` — data/scenarios·data/timeseries·data/timeseries_v2 의 파일들.

**진단 (V5 코드 무결 — 판정 기준의 오탐).** 세 갈래 증거:
1. compute 잡 명령 5종(`mature-labels`·`train`·`gate`·`forecast`·`resolve`)을 로컬에서
   실행 전후로 protected 매니페스트를 떠 비교 → 델타 **0건**. V5 는 보호 경로에 쓰지 않는다.
2. `protected_baseline.json`(2026-08-24T01:34Z 동결, 4,945 파일)을 각 커밋 트리와 비교:
   플라이휠 커밋 `3ce82b95` 에서 드리프트 0, HEAD 에서 changed 18 · added 2,669 —
   CI 가 보고한 목록과 **1:1 일치**.
3. 그 18개 파일을 바꾼 커밋은 전부 형제 파이프라인(scenario-refresh·timeseries-refresh
   ·timeseries-v2-refresh)의 `github-actions[bot]` 커밋. V5 커밋은 0건(한 번도 성공 못 함).

즉 `verify_v5` 는 "V5 가 보호 경로를 건드렸는가"가 아니라 "저장소가 8/24 이후 멈춰
있는가"를 물었다. data/timeseries·data/timeseries_v2·data/scenarios 는 각자 스케줄
라이터를 가진 **살아 있는** 디렉터리이므로 이 판정은 구조적으로 매일 실패한다.
동일 커밋(`3ce82b95`)이 `runs/backtest_latest.json` 을 함께 넣어 워크플로의
`if [ -f ... ]` 가드가 첫날부터 열린 것이 12일 연속 실패의 시작점이다.

**결정.** protected 판정 기준을 **체크아웃 커밋 대비 워킹트리 드리프트**로 교체한다
(`contracts.protected_worktree_drift` — `git status --porcelain -uall -- <protected_roots>`).
이는 `backtest_v5`(런 내 before/after)와 `baseline_audit.write_audit_artifacts` 가 이미
쓰던 의미론이고, 워크플로의 `protected and allowlist guard` 스텝과도 같은 기준이다.
부가 효과로 추적되지 않는 신규 파일(untracked)과 오늘 존재하지 않는 보호 루트
(data/forecasts·data/ledgers)의 **생성**까지 잡는다 — 기존 `git diff` 가드는 놓치던 경로.
git 을 쓸 수 없으면 통과가 아니라 오류(`protected isolation unverifiable`)로 닫는다.

`protected_baseline.json` 은 삭제하지 않는다 — V5 격리 시작점의 provenance 기록이자
감사 문서(`V4_TO_V5_BASELINE_AUDIT.md`)·워크북이 인용하는 해시다. verify 출력에서
`protected_baseline_reference`(`divergence_expected: true`)로 강등해 계속 보고한다.
`initialize_v5` 의 동일 오탐 단언도 같은 기준으로 교체.

**기록.** `src/ai_fc/timeseries_v5/contracts.py`(`protected_worktree_drift`),
`pipeline.py`(`verify_v5`·`initialize_v5`), `src/tests/test_multivariate_timeseries_v5.py`
(회귀 3종 — 형제 커밋 무해·실제 위반 4종 탐지·verify 기준 확인).

**후속 (같은 PR).** 위 수정으로 compute 잡이 처음으로 `verify` 를 통과하자 그 다음
스텝인 `commit research read model` 에서 새 실패가 드러났다(PR 브랜치 런). 이 워크플로는
`fetch-depth` 기본값(얕은 체크아웃)에 `git pull --rebase origin main` 을 무조건 실행하는데,
main 이외의 ref 에서는 그 브랜치를 main 위로 재생하려 들고 얕은 히스토리에는 공통 조상이
없어 add/add 충돌로 죽는다. `push` 트리거 경로(`src/ai_fc/timeseries_v5/**`)가 있으므로
V5 코드 PR 마다 재발한다. 형제 `timeseries-v4-data-refresh.yml` 과 동일하게 커밋·푸시
스텝에 `github.event_name != 'pull_request' && github.ref == 'refs/heads/main'` 가드를
달았다 — 브랜치 런은 검증만, 기록은 main 만. 회귀 테스트
`test_workflow_writes_the_read_model_only_from_main` 추가.

## 2026-09-09 — C5-A1·A2·A3: 캘리브레이션 프로그램 개시 — 포트폴리오 사전등록·월 예산 $40·자동화 (사용자 승인)

**결정.** 사용자 승인 원문: `다 승인이야. 월예산도 40불로 늘려. 그리고 둘다 단계별로 진행해.`
(수신 2026-09-09 14:45:30 KST — 시각은 도구 호출 기록에서 가져왔다.) 세 승인 지점을 한 번에 받았다.

| # | 항목 | 결정 |
|---|---|---|
| **C5-A1** | 질문 포트폴리오 사전등록 | `questions/portfolio_prereg_v1.yaml` — 예리도 예산(신규 평균 `p(1−p)` ≤ 0.15 · 개별 상한 0.21 · 예외 슬롯 3) · 분산 규칙(단일 드라이버 ≤ 40% · 동일 마감일 ≤ 3 · 도메인 ≥ 4 · 90일 이내 ≥ 50%) · 조합 20문항(정책4·매크로6·변동성4·기업3·예외3) |
| **C5-A2** | 월 예산 상한 | **$20 → $40**. 자동 경로 sub-cap(OpenAI) $10 → $25 — 주 1건에서 주 2~3건으로 늘리려면 CI 핀이 실질 병목이기 때문 |
| **C5-A3** | 자동화 활성화 | 신규 질문 우선 예측 · 판정 초안 큐잉 · SLA 경보. **판정 확정 자동화는 포함하지 않는다** |

**왜 지금인가 — 실측 진단.** 설계도(`docs/design/c5_calibration_program_blueprint_v1_260909.md`) 5개 병목.

- **D1** primary 해소 **5문항 / 50**. 레지스트리 구조 상한은 `해소 5 + active 34 = 39 < 50` — 신설이 산술적으로 강제된다.
- **D2 (핵심)** 완전 캘리브레이션 하의 기대 Brier는 항등적으로 `p(1−p)`인데, 전 예측 51행의 평균이 **0.1841 > 0.18**이다. **질문 선택만으로 이미 임계 위**이며 실력으로 뒤집을 수 없다. 원장 최악 2건(`spx-up` p=50 · `soxx-up` p=46)이 그 증거.
- **D3** 드라이버 `ai-capex-cycle` 19문항 · `fed-path` 11문항, 마감일 12-31 에 7문항. 클러스터 내 완전 상관 가정 시 ESS 하한 2.7/40.
- **D4** CI 워크플로 23개 중 C5 루프를 도는 것 0개. 유일하게 스치는 `investing-refresh` 4단계는 주 1건 **재예측**인데, 게이트 문항 수는 `COUNT(DISTINCT question_id)`(`schema.sql:436`)라 **기여 0**이다.
- **D5** anchor 회수 44건에서 평균 `|최종확률 − anchor|` = **4.8%p** — 우리 확률은 사실상 base rate다.

**결과 전 고정.** 예리도 예산·분산 규칙·조합·금지 질문형·부수 증명서 목록·중간 정지 조건을 **신규 질문을 하나도 만들기 전에** 커밋했다. 이후 개정은 개정 커밋 + 재승인으로만 한다.

**게이트 산술 무변경.** `v_gate_status`(50문항 · Brier < 0.18)의 SQL은 한 글자도 바꾸지 않는다. 부수 증명서(BSS vs anchor · Murphy · ESS · 클러스터 부트스트랩 · 경로별 분해)는 전부 **표시 계층**이며 판정에 다리를 놓지 않는다.

**이것이 아닌 것.** P3 게이트 완화 아님(임계는 CLAUDE.md 소관). 실전 자금 승인 아님 — 통과해도 `BSS_anchor ≤ 0`이면 자동 활성화하지 않고 사용자 판단으로 넘긴다(C5-A4). 하드 룰(VIX 25+·드로다운) 대체 아님.

**부수 발견 (기록).** 재예측은 예리도를 실제로 개선한다 — 다회차 13문항에서 첫→최신 평균 `p(1−p)` **0.1845 → 0.1636 (−0.0209)**, 7/13 개선(adbe 59%→82%, aapl 54%→80%). 따라서 비용 절감안 중 "회차 절감"은 **기각**한다: 예리도를 함께 깎는다.

**기록.** 설계도 840줄 · 사전등록 `questions/portfolio_prereg_v1.yaml` · `src/ai_fc/config.py` 예산 · `docs/P1_OPERATIONS.md`.


## 2026-09-09 — C5 실행 기록 Q0·Q1·Q4 + ML 전략 설계도 (승인 C5-A1~A3의 이행)

**Q0 판정 기계.** `src/ai_fc/c5_certificate.py` + `tools/c5_status.py`. 게이트 산술을 원천 파일에서
재계산한 거울이 **정본 뷰(`v_gate_status`)와 일치**함을 확인했다. 부수 증명서 5종(BSS vs anchor ·
Murphy · ESS 하한 · 클러스터 부트스트랩 · 생산 경로 분해)은 전부 표시 계층이며 게이트 SQL 무변경.
첫 출력이 즉시 잡아낸 것: 분산 규칙 위반 3건 · 생산 51건 중 **43건이 unmetered 경로** ·
클러스터 부트스트랩 CI90 [0.0166, 0.2380]로 **현 Brier 가 임계 아래라고 말할 수 없음**.

**Q1 밀린 해소 2건.** SLA(마감+3영업일) 초과분을 1차 출처로 판정.
- `avgo-eps-beat-fq3-2026` → **YES** (p=82%, Brier 0.0324). non-GAAP EPS $3.32 > 스냅샷 컨센 $3.238.
  r1 이 사전 배제한 Zacks 계열 컨센을 써도 결론 동일 — 벤더 선택에 판정이 걸리지 않았다.
- `nfp-aug2026-below100k` → **NO** (p=74%, Brier 0.5476). 최초 공표 +162,000, 컨센 +55,000 대비
  +107K 상방 서프라이즈. **같은 릴리스에서 7월 초판 −23,000 이 +21,000 으로 상향 개정**되어
  r1 의 전제였던 '사이클 첫 마이너스'가 소멸했다. 본 질문은 최초 공표 기준이라 판정에는 영향이
  없으나, **초판 기반 추론의 취약점**으로 기록한다.

누계 문항 5 → **7/50**, primary Brier 0.1273 → **0.1599**, 해소 대기 큐 0.

**Q4 자동화.** 자동 경로가 **첫 예측 미실행 질문을 먼저** 집도록 우선순위를 뒤집었다
(`registry.prioritize_forecast_targets`). 이전에는 주 1건을 재예측에 썼는데, 게이트 문항 수가
`COUNT(DISTINCT question_id)`라 그 1건의 게이트 기여가 **정확히 0**이었다.
`c5-resolve-draft.yml` 신설 — 판정 초안까지만 자동, **확정은 영구히 사람**(원장 append-only).
`ops-backlog-alert` 본문에 C5 게이트 진도 추가.

## 새 측정 — extremization 은 우리 표본에서 음(−)이다

`docs/design/ml_dl_strategy_blueprint_v1_260909.md` §4.1. 기록된 확률에 결정론 변환
σ(α·logit(p)) 을 적용한 가상 Brier (해소 10행 primary):

| α | 1.000 | 1.200 | 1.500 | **1.732 (√3)** | 2.000 | 2.500 |
|---|---|---|---|---|---|---|
| Brier | 0.1599 | 0.1640 | 0.1735 | **0.1818** | 0.1914 | 0.2076 |

**단조 악화이며 되돌아오는 지점이 없다.** 확신 있게 틀린 예측(nfp-aug 74%→NO 등)이 극단화로
제곱 손실을 폭증시킨다. 보조 진단(Murphy REL 0.1598 ≤ RES 0.2100)은 반대를 가리키므로
**격자를 따르고 불일치를 상시 인쇄**한다. 표본 10/30 이라 판정은 보류 — 격자는 결과 전 고정.

**함의 (중요).** C5 설계도 D2(예리도 0.1841 > 0.18)의 해법은 extremization 이 **아니다**.
`p(1−p)`(캘리브레이션 하의 *기대* Brier)를 낮추는 것과 실현 Brier 를 낮추는 것은 다르며,
미보정 상태에서 예리하게 밀면 전자는 좋아지고 후자는 나빠진다. D2 의 해법은 질문 포트폴리오다.

**관측 채널 개통 (비용 0).** `anchor_pct`·`shadow_extremized` 기입을 TEMPLATE 과 `/forecast`
스킬에 의무화했다. 지금까지 CLI 경로만 기록해 커버리지가 **4/51**이었고 그래서 BSS 표본이
결손이고 M1 표본이 0 이었다. 전방 전용 — 기존 불변 파일 무수정.

**자원.** 신규 LLM 호출 0 · 비용 0(판정은 웹 검증). 테스트 38건 추가.


## 2026-09-09 — C5 Q3: 신규 20문항 등록 + 사전등록 예상확률의 대실패 (기록)

**Q3 실행.** 사전등록 `C5_PORTFOLIO_V1` 을 **기계 검증한 뒤에만** 레지스트리에 썼다. 1차 검증에서
예리도 예산 초과(0.1620 > 0.15)로 FAIL 이 나자 **확률 추정을 손대지 않고 임계를 실제로 더 예리하게**
바꿔 재통과시켰다(11월 CPI 3.0%→2.8% · ECB 2.75%→3.00% · X-Energy 창 10/31→9/30). 최종 0.1487.

**분산 위반 3건 중 드라이버 집중이 해소됐다.** 신규 드라이버 6종(inflation-path·labor-market·
ipo-window·ecb-normalization·boj-normalization·credit-cycle)을 도입하고 ai-capex-cycle 을 하나도
늘리지 않아 최대 점유 **42% → 28%**, **ESS 하한 2.7 → 5.1**. 마감일 밀집 2건(10-28·12-31)은
기존 질문에서 온 것이라 남아 있다.

## 자동 경로의 결함 하나가 등록 직후 드러났다

`due` 는 레지스트리 순서를 따르므로 신규 26문항이 사실상 등록 순으로 줄을 섰고, **마감이 2일 남은
질문이 마감 6개월 남은 질문 뒤로 밀렸다.** 주 1건 상한이면 그대로 마감을 넘겼을 것이고 그 질문은
영구 채점 불가(void)가 된다 — 2026-08-31 회고에서 질문 3건이 실제로 이렇게 소실된 실패 모드다.
`prioritize_forecast_targets` 에 2차 정렬키(마감 임박)를 넣고 처리량을 주 1 → 3건으로 올렸다.

## 사전등록 예상확률이 43%p 빗나갔다 — 이것이 이 세션의 가장 중요한 발견이다

`cpi-aug2026-core-below-24` 첫 예측 결과: **사전등록 예상 22% vs 실제 65%**.

**원인.** 등록 시점에 "core 가 2.6%→2.5% 로 왔으니 2.4% 까지 한 계단 더는 어렵다"고 **인쇄값의
계단만 셌다**. BLS 지수 수준을 보면 미반올림 7월 YoY 가 **2.4783%** 로 이미 반올림 경계에서
0.028%p 위였고, 컨센서스(2.4%)와 Cleveland Fed 나우캐스트(2.38%)가 둘 다 YES 를 가리키고 있었다.

**왜 중대한가.** C5 설계도 §6.1 의 예리도 예산 전체가 **"첫 예측 전에 p 를 추정할 수 있다"는 가정**
위에 서 있다. 이 표본 1건은 그 추정 능력이 최소한 매우 부정확할 수 있음을 보인다. 예산이 맞는지는
**등록 시점이 아니라 첫 예측이 끝난 뒤에야** 알 수 있다는 뜻이다.

**즉각적 결과.** p(1−p) 가 0.1716 → **0.2275** 로 개별 상한 0.21 을 초과했다. 예외 슬롯이 아니므로
**첫 예측에서 예산 위반이 확정**됐다. 확률을 예산에 맞추는 조정은 하지 않았다 — 그것이 곧
캘리브레이션 조작이다. 사전등록 `reconciliation.recompute_on_actual` 대로 실제값으로 재계산해 보고한다.

**남은 19문항이 같은 방향으로 빗나가면** 결합 행 평균이 임계 0.18 을 넘어 게이트가 닫힌다.
현재 여유는 신규 1회차 가정에서 0.0059 뿐이라 이 리스크는 실재한다. 다음 몇 건의 첫 예측에서
괴리 방향을 관측한 뒤 §12(부정 결과 처리) 또는 사전등록 개정을 판단한다 — **결과를 보고 예산을
완화하는 것은 금지**이므로, 개정한다면 그것은 '예상 능력 부족'의 기록이지 기준 완화가 아니다.

**자원.** 신규 LLM 호출 0(등록은 무료) · 첫 예측 1건은 스킬 경로(unmetered). 서브에이전트 2개.
**미완.** 로컬 `ots` CLI 가 내부 TypeError 로 실패해 `forecasts/.hashes.ots` 가 2026-09-08 판이다.
머지 후 ots-stamp 워크플로 또는 수동 재스탬프 필요.


## 2026-09-09 — C5 v1.1: 예측률 제고 전략 — 실측된 지렛대 하나에 건다

**배경.** Q3 실행이 설계 v1 의 두 가정을 실측으로 무너뜨렸다.
① "첫 예측 전에 p 를 추정할 수 있다" — `cpi-aug` 예상 22% vs 실제 65%(오차 43%p).
② "설계대로 쓰면 해소가능하다" — 20건 중 **6건(30%) 결함**, 그중 3건은 **결과가 이미 확정된
과거 사건**(X-Energy 2026-04-24 상장 · Cerebras 2026-05-14 상장). 전부 첫 예측 전에 잡혀
**원장 오염은 0**이다.

**전략.** 이 프로그램에서 **양(+)으로 측정된 지렛대는 재예측 sharpening 하나뿐**이다
(다회차 13문항 첫→최신 `p(1−p)` 0.1845 → 0.1636, −0.0209, 7/13 개선). extremization 은
실측에서 단조 악화했고(0.1599 → 0.1818 @α=√3), 질문 예리도 사전 설계는 ①로 보장이 안 된다.
따라서 **재예측 커버리지 극대화**에 건다.

| 단계 | 행 | 행 평균 p(1−p) | 임계 0.18 대비 |
|---|---|---|---|
| 현재 | 55 | 0.1842 | **−0.0042 (미달)** |
| + Q3 잔여 첫 예측 13 | 68 | 0.1773 | +0.0027 |
| + active 전건 D-3 회차 | 117 | **0.1714** | **+0.0086** |

총비용 $93(월 $9.3)으로 sub-cap $25 안. **돈이 아니라 큐 순서가 병목이었다.**

**변경 3건.**
- **V1 마감 임박 > 회차** (`URGENT_WINDOW_DAYS=7`). v1 의 "미예측 항상 우선"은 문항 수만 보고
  Brier 를 무시했고, 그 결과 미예측 19건을 주 3건으로 소진하는 7주 사이 마감되는 질문의
  **D-3 회차가 영구 소실**된다(실측 4건). 적용 즉시 다음날 마감인 `adbe` 의 D-3 회차가
  1순위로 올라왔다 — 옛 규칙이면 잃었을 회차다. 긴급 창 밖에서는 v1 규칙이 그대로 산다.
- **V2 질문 프리플라이트**. 정적 탐지 2종(기간형 시작일 누락 · 리터럴 문자열 의존) +
  2026-09-10 이후 등록 질문에 `preflight` 블록 강제(`not_yet_occurred`·`window_start`·
  `resolution_wording_checked`). 판정이 아니라 점검 후보 제시다. 이 검사가 즉시
  `hy-oas-500bp-by-2027-01-31` 의 시작일 누락을 잡아내 폐기·재등록했다(실측상 무해했으나
  ai-ipo-2b-plus 와 동일 결함 유형).
- **V3 예산 실측 대사**. 사전등록 `recompute_on_actual` 을 구현 — **첫 예측** 확률로 재계산하고
  미채점분은 예상으로 혼합. Q3 생존 17문항 실측 혼합 **0.1483** (목표 0.15 만족).

**사전등록은 개정하지 않는다.** ①이 보여준 것은 "기준이 틀렸다"가 아니라 "추정 능력이
부족하다"이며, 결과를 본 뒤 기준을 완화하는 것은 설계도 §4.3-9 위반이다. 대신 대사를 실측
기준으로 바꿔 미달을 숨기지 않는다. corporate_event 군은 **0/3 미달로 남긴다** — 30% 결함률
직후에 검증 없이 채우는 것이 더 나쁘다.

**남은 위험.** 폐기 7건으로 구조적 상한이 58(게이트 50 대비 +8)까지 얇아졌다. 전략 완주 시
여유 +0.0086 은 행 117개의 Brier 표준오차(`[추정]` 0.015)보다 작다 — 통과는 상당 부분 운이며
설계도 §6.3 이 이미 명시한 바다.

**기록.** 설계도 §13(v1.1) · `registry.prioritize_forecast_targets` · `c5_certificate`
(`question_preflight`·`budget_reconciliation`) · `tools/c5_status` · 테스트 17건 추가.

### 2026-09-10 — V13-D10: PAV(cross-fit isotonic) 예외를 ML 게이트에 대해 명문화

외부 검토 판정서(2026-09-10) RQ12-1 의 권고를 받아들여 기록한다. 적대적 검증에서
"PAV 적합이 아예 없었다"는 우리 진술이 **거짓**임이 밝혀졌기 때문에 더 필요해진 기록이다 —
h63 3셀에 isotonic 이 **실제로 적합·평가**됐고, 사전등록 fallback 으로 **배치만** 0이었다
(`data/timeseries_v13/vol/ladder_pb_baseline.json` 의 `cells.*.iso`, 동결 계수의 `iso_map` 9셀 전부 null).

**판정.** PAV 단조맵은 CLAUDE.md 하드 게이트의 "캘리브레이션 보정(isotonic/Platt)은 해소 100+ 후"
조항 **문면 밖**이다. 그 조항은 **LLM 예측 원장의 확률을 보정하는 것**을 규율하며, V13 은
결정론 수치 모델의 산출을 다루고 LLM 캘리브레이션 표본이 아니다(CLAUDE.md 5원칙 5 명문화된 예외).
그러나 PAV 는 **데이터에 적합되는 단조맵**이므로 조항의 취지에는 닿는다. 그래서 예외를 넓게
두지 않고 네 조건으로 좁힌다.

| # | 조건 |
|---|---|
| (a) | **판정(G1·G2·G4)은 raw PB 확률로만 한다.** 보정된 확률은 어떤 게이트 판정에도 들어가지 않는다 |
| (b) | **표시 파생층 한정.** 계약 `reliability.cross_fit_isotonic_h63.layer: derived_probability_only` · `gate_bridge: false` |
| (c) | **파라미터 수와 cross-fit 로그를 남긴다.** 적합이 있었는지 없었는지를 사후에 다투지 않기 위해서다 |
| (d) | **해소 100+ 전 LLM 원장 적용 금지**를 재확인한다. 이 예외는 V13 수치 모델 산출에만 적용되며 `calibration/ledger.csv` 경로로 번지지 않는다 |

**현 상태.** 사전등록 fallback(양방향 중 한 방향이라도 iso 가 유의 열위면 raw)이 발동해
**운영 배치는 0**이다. 즉 지금 표시되는 어떤 숫자도 PAV 를 거치지 않았다. 그럼에도 이 항목을
남기는 이유는, "적합이 없었다"와 "적합은 있었고 배치만 없었다"가 다른 진술이고 후자가 사실이기 때문이다.

**기록.** `data/contracts/multivariate_timeseries_v13_vol.yaml` `reliability.cross_fit_isotonic_h63` ·
`data/timeseries_v13/vol/ladder_pb_baseline.json` · 검토팩 정오표 A2.

### 2026-09-10 — T02: 질문 포트폴리오 사전등록 계약 + 승인 12건 등록 (사용자 승인)

P3 게이트에서 우리가 통제할 수 있는 것은 **예측을 잘하는 방법이 아니라 채점될 수 있는 질문을
고르는 방법**이다. 완전 캘리브레이션 하의 기대 Brier 가 `E[p(1−p)]` 이므로, 질문을 고르는
순간 기대 성적의 바닥이 정해진다. 사후에 나쁜 표본을 빼면 그것은 표본 선택이다 — 그래서
**등록 시점이 유일한 정직한 개입 지점**이다.

**계약.** `questions/portfolio_prereg_v1.yaml` — 커밋 **`9337f183`**, 후보 z 재검증·선택 결과를
보기 **전에** 커밋했다. 내용: z 규율(`z = |임계−중심추정|/σ`, `z≥1.0` 채택 / `[0.7,1.0)` 예외 슬롯 ≤3 /
`<0.7` 거부) · 사구간 `[0.235, 0.765]` 등록 차단(`0.235×0.765 = 0.17978`) · 문항별 기대 Brier 상한 0.21 ·
market-daily 영구 제외 · L3/L4 발동조건과 비선택 로그 의무(소급 금지) · 정지 규칙
(`never: [stop_at_49_and_cherry_pick, post_hoc_failed_tagging, gate_arithmetic_change]`) ·
게이트 상태 표현 고정("미결 (0.33 SE)", 금지어 "통과").

**집행.** `src/ai_fc/portfolio_prereg.py` 가 계약을 읽어 등록 후보를 판정한다. 계약 파일이 없으면
**모든 신규 등록을 거부**한다. 이 훅은 **원장을 읽지 않는다** — 등록 판정이 성적을 보면 그 자체가
선택 편향이므로 테스트(`test_module_never_reads_the_ledger`)로 고정했다.

**사용자 결정 2건 (2026-09-10).**

| 결정 | 선택 | 근거 |
|---|---|---|
| 최종 목록 | **A — 채택 9 + 예외 슬롯 3 = 12건 전부** | 문항 수가 꼬리 위험의 방어다. 2건 YES 시나리오에서 A(12건) 0.1607 vs B(9건) 0.2080 — 분모가 손실을 희석한다. 기대 바닥은 B 가 낫지만(0.0675 vs 0.0784) 꼬리에 약하다 |
| 기등록 충돌 | **거부 유지 + 부정합 기록** | 기등록 질문은 건드리지 않는다. `mu-gm-qoq-drop10pp-fq1-2027` 은 기등록 `mu-margin-qoq-fq1fy27` 의 진부분집합이라 거부 유지. `fedfunds-upper-450-2026-12-09` 은 기등록 `fedfunds-upper-425-2026-12-09`(예상 12%)와 `P(3회째|2회)=58%` 를 함의하는 부정합이 있으나, 예외 슬롯으로 등록하고 부정합을 **질문 파일과 계약에 기록**한다 |

**등록 결과.** `questions/registry.yaml` **67 → 79 문항**. 포트폴리오 기대 Brier 바닥 평균 **0.0784**.
문항별 상한 0.21 초과 0건 · 사구간 진입 0건 · 마감 전부 2027-01-15 이하 · 계약 훅 12/12 통과.
등록으로 **드라이버 집중 위반이 해소**됐다(단일 드라이버 점유 42% → 상한 40% 아래).

**훅보다 한 칸 보수적으로 기록했다.** 훅은 `z<1.0` 또는 `기대 Brier>0.21` 일 때만 슬롯을 청구하므로
기계적 소모는 2/3 다(`fedfunds-upper-450` z=0.810 · `nasdaq-comp-30000` z=0.954). 계약은
`adbe-eps-above-guide-top-fq4-2026`(z=1.040, floor 0.1275)에 `n=4` 표본이 얇다는 이유로 슬롯 1개를
**자발적으로** 청구해 3/3 으로 기록했다. 반대 방향(훅이 요구하는 슬롯을 계약이 면제)은 없다.

**등록은 예측이 아니다.** `forecasts/` 0건 생성 · `calibration/ledger.csv` 0행 추가 ·
게이트 SQL·문턱 무변경. r1 실행은 별도 지시 사항이며 12건 × (r1 + D-3) = 24회차로 대략 $50~78 이다.

**적용하지 않은 권고.** 검증(`SELECTION.md §5-1`)은 정직확률 3건의 교정을 권고했으나
(`vix-40-touch` 0.08→0.13 · `t10y2y-100bp` 0.06→0.09 · `fedfunds-upper-450` 0.07→0.04) 등록값은
바꾸지 않고 각 질문의 `prereg.reference_class_correction` 에 **병기**했다. 권고는 승인 대상 목록에
없었고, 어느 값을 써도 채택/거부 판정이 바뀌지 않는다(0.13 의 바닥 0.1131 · 0.09 의 바닥 0.0819 —
둘 다 문항 상한 아래).

**기록.** `questions/portfolio_prereg_v1.yaml`(`9337f183`) · `src/ai_fc/portfolio_prereg.py` ·
`src/tests/test_portfolio_prereg.py`(13건) · `docs/p3_gate_path/candidates/`
(후보 20건 초안 3종 · `verdicts.json` · `SELECTION.md` · `REGISTRATION.md`).

### 2026-09-11 — T03: σ 는 트랙이 공급하고 임계는 사람이 정한다 (사용자 확정)

수치 트랙이 P3 게이트에 기여할 수 있는 유일한 합법 경로는 **산포 공급**이다. 확률 결합은
8-8 이 금지하지만, 계약의 z 규율(`z = |임계 − 중심추정| / σ`)은 σ 를 요구하고 사람이
눈대중으로 적으면 그 규율은 집행되지 않는다. 그래서 σ 만 기계가 공급한다.

**팩의 전제를 하나 정정했다 — V13 은 σ 를 공급할 수 없다.** T03 팩은 "변동성 질문 →
V13 PB 셀"로 매핑을 적었으나 셀 산출은 `P(사건)`이지 산포가 아니다. 확률에서 σ 를 역산하면
z 규율이 `z = Φ⁻¹(1−p)` 항등식이 되어 어떤 p 를 써도 자동 통과한다 — `SELECTION.md` 가
`fedfunds-cut-to-350` 을 거부한 바로 그 사유다. σ 경로는 참조클래스와 V8 분위수 둘뿐이고
V13 의 몫은 표시 전용 배선이다.

**사용자 확정 2건 (2026-09-10, 결과 보기 전).**

| 결정 | 선택 |
|---|---|
| σ 소스 매핑 | **양 일치 우선 + 두 경로가 같은 양을 재면 큰 σ 채택** — 큰 σ 는 z 를 낮춰 등록을 어렵게 만드는 방향이라 게이밍의 반대편 |
| V13-D6 배선 | **코드는 만들고 대상 0으로 페일클로즈** — 자격 셀이나 대응 질문이 생기면 지도만 채우면 켜진다 |

**규칙 2 의 구멍을 같이 막았다.** `전체기간 σ` 와 `2010+ σ` 는 두 경로가 아니라 한 경로의 두
파라미터이므로, 큰 쪽을 고르게 두면 규칙이 조건화 쇼핑 장치가 된다. 실측으로 이 구멍은 크다 —
나스닥 87영업일 종점 로그수익률 σ 가 전체 0.0971 · 2010+ 0.0772 · 2015+ 0.0841 로 26% 벌어지고
`nasdaq-comp-30000` 의 z 가 1.37~1.73 을 오간다. `adopt()` 는 같은 경로의 견적이 둘 이상이면
거부한다. 조건화는 계산 **전에** 하나로 선언한다.

**등록 12건 대조.** 기계 경로 4건을 재계산해 `vix-40-touch` 6.553 · `t10y2y-100bp` 0.230 ·
`nasdaq-comp-30000` 0.081172 가 등록값과 일치했다. `vix-above20-40days` 만 19.644 vs 등록
20.015 로 1.9% 차이인데 카운트가 0 에 몰린 이산 분포라 분위수 보간에 민감한 탓이고, z 는
1.60 vs 1.63 으로 밴드 판정이 바뀌지 않는다. **σ 값은 바꾸지 않았다** — 계약의 소급 금지
조항에 따라 T03 규칙은 이후 등록분부터 적용되며, 12건에는 `sigma_quantity`·`sigma_path`·
`sigma_reproduce` 라벨만 추가했다(나머지 67문항 바이트 무변경).

**배선은 0건이다.** 자격 = 홀드아웃 통과 ∧ 설계창 국면 가드 통과 ∧ 대응 질문 존재.
`vix25_h21` 은 홀드아웃을 통과했지만 설계창 late 국면이 4개뿐이라 두 번째 조건에서 걸리고
(그래서 **교집합**을 쓴다), 남는 `rv_h5`·`rv_h21` 은 대응 질문이 없다. 등록된 `vix-25-90d` 는
63영업일이라 홀드아웃 **실패** 셀 `vix25_h63` 에 대응한다. 화면에 바뀌는 것은 없다.
배선이 켜져도 나가는 것은 기후 기저율·임계·지평뿐이고 모델의 `p`·`band80` 은 넘기지 않는다.

**기록.** `src/ai_fc/sigma_supply.py` · `src/ai_fc/vol_base_rate_wiring.py` ·
`src/tests/test_sigma_supply.py`(22건) · CLI `sigma-quote`·`vol-wiring-status` ·
`docs/p3_gate_path/T03_RESULT.md`.

### 2026-09-11 — T04: NFP 계열의 예약된 손실을 결과 전에 기록하고, 손실을 세 조각으로 쪼갰다

`nfp-oct2026-below100k`·`nfp-nov2026-below100k` 의 r1 은 같은 날(2026-08-31) 같은 전제
(컨센서스 NOT FOUND)로 생산돼 확률이 66% 로 동일하다. 두 행은 독립 표본이 아니다.
둘 다 NO 면 primary 행 평균이 **0.15986 → 0.20582** 로 문턱 위로 올라간다(둘 다 YES 면 0.15248).
이 숫자를 **결과를 보기 전에** 남긴다 — 나중에 보고 규칙을 바꾸면 그것이 사후 조작이다.

**등록 시점 z 사후 계측 — 재분류 없음.** `status`·`research_status` 무변경, void 0건,
원장 행·예측 파일 무수정. `postmortem` 블록은 점수에 개입하지 않는다.

| 질문 | z | 정직확률 | 기대 바닥 | 밴드 |
|---|---|---|---|---|
| `nfp-aug2026-below100k`(해소) | 0.474 | 0.682 | 0.2168 | reject |
| `nfp-oct2026-below100k` | 0.228 | 0.590 | 0.2418 | reject |
| `nfp-nov2026-below100k` | 0.228 | 0.590 | 0.2418 | reject |
| `nfp-dec2026-below-neg75k`(신규) | 1.526 | 0.064 | 0.0594 | accept |

σ 경로가 갈린다: aug 는 r1 시점 컨센이 있어 컨센 오차 σ 95K 로 `|100−55|/95`, oct·nov 는
컨센이 NOT FOUND 였으므로 계열 자체 산포(2026년 1~7월 최초 공표 평균 76.7K·표본SD 102.0K)로
`|100−76.7|/102.0`. **컨센이 없으면 z 가 더 나빠진다.**

**손실의 대부분은 예측이 아니라 질문에서 왔다.** aug r1 은 q=0.74 로 정직확률 0.682 와
+0.058 차이뿐인데 실현 Brier 가 0.5476 이었다. 기대 바닥만으로 이미 0.2168 이다.
신규 `nfp-dec2026` 은 **같은 σ 95K 를 그대로 두고** 임계만 100K → −75K 로 옮겨 바닥을
0.2168 → 0.0594 로 **72.6% 내렸다**. 무엇을 묻느냐가 아니라 임계가 어디 있느냐가 바닥을 정한다.

**팩 문구 하나를 정정했다.** 팩은 "T02 의 L3 규칙에 따라 r2 재예측"이라 적었으나 L3 의 scope 는
"2026-09-10 이후 신규 등록분만, 소급 금지"다. oct·nov 는 2026-07-20 등록이라 **L3 대상이 아니다**.
실무 결과는 같다 — 두 질문의 cadence 가 이미 `r1 + D-3`(2026-11-03·2026-12-01)이고 컨센서스는
발표 1~2주 전에 형성되므로 D-3 회차가 자연히 컨센 이후가 된다. 필요도 없는데 소급 적용하면
"유예 규칙을 결과 보고 꺼내 썼다"는 기록만 남는다.

**r2 는 r1 손실을 지우지 않는다.** 원장은 회차별 행이 남고 대표 Brier 는 행 평균이므로 늦은
정확한 회차는 r1 행을 덮지 않고 **희석만** 한다. 재예측은 손실 취소가 아니라 표본 추가다.

**손실 3분해** `Brier = p(1−p) + [(p−y)² − p(1−p)] + [(q−y)² − (p−y)²]` — 기대 바닥(등록에서만
고칠 수 있다) · 뽑기(고칠 수 없다, 기댓값 0) · 앵커 초과(유일한 실력 축, 부호 양방향).
`p` 는 등록 시점 고정값에서만 오고(`prereg.honest_probability_estimate` 또는 `notes` 의
`예상확률 N% (첫 예측 전 고정)`), 없으면 분해하지 않는다.

**커버리지는 지금 0 이다.** 해소 10행 전부가 분해 불가 — 등록 시점 정직 확률이 기록된 질문이
아직 하나도 해소되지 않았다. 앞으로는 활성 61문항 중 25건이 분해 가능하다(prereg 12 + notes 13,
32건 기록 없음, 4건 '리서치 이후 산정' 제외). "분해가 작동한다"와 "지금 쓸 수 있다"는
다른 진술이고 후자는 아직 거짓이다.

**기록.** `src/ai_fc/loss_decomp.py` · `src/tests/test_loss_decomp.py`(15건) ·
`src/ai_fc/report.py` 손실 3분해 패널 · `questions/registry.yaml` NFP 3건 `postmortem` ·
`docs/p3_gate_path/T04_RESULT.md`.

### 2026-09-11 — T05: 소실률 정본 유지 · lite 티어 은퇴 · 가드 두 개가 꺼져 있던 문제 (사용자 확정)

**먼저, 가드 두 개가 조용히 꺼져 있었다.** 레지스트리의 `created` 는 `2026-07-08`(YAML date)과
`'2026-09-10'`(따옴표 문자열)이 섞여 있는데, `question_preflight` 와 `factory_filter_violation` 이
둘 다 `isinstance(created, date)` 로만 봐서 **문자열인 36/79문항의 컷오프 비교를 건너뛰었다.**
그중 13건이 컷오프 이후 등록분이고 T02 의 신규 12건도 포함된다 — 내용은 맞았지만 검사는
**통과가 아니라 면제**였다. 가드가 꺼진 줄 모르고 통과하는 것이 가드가 없는 것보다 나쁘다.
`as_date()` 정규화 + 회귀 테스트 3건. 고친 뒤 결과는 동일하다(결함 후보 5건 전부 기등록,
등록필터 위반 0건).

**사용자 확정 3건.**

| 결정 | 선택 |
|---|---|
| 소실률 정본 | **계약값 14.9% 유지** |
| 품질 티어 | **cli/api 통일 · lite 은퇴** |
| `asml-eps-beat-2026q3` | **r2 생산 · 선택된 티어로** |

**소실률.** 실측은 등록 대비 전량 void **12.7%**(10/79) · 예측 후 void **0.0%**(0/8) ·
처리량 소실 **11.1%**(1/9, `cpi-jun2026-accel`). 팩이 인용한 14.9%/6.0% 는 재현되지 않는다 —
14.9% 는 계약의 *사전등록 기대값*이지 실측이 아니었다. void 10건은 **전부 예측 0건**으로,
프리플라이트가 돈 쓰기 전에 잡은 설계 결함이지 구조적 소실이 아니다.
정본을 계약값으로 두는 이유: 14.9% 는 결과 전에 커밋됐고, 실측으로 갈아끼우면 이번엔 무해해
보여도(12.7 < 14.9) **같은 움직임이 불리한 방향으로도 허용된다는 선례**가 남는다.
실측 세 값은 계측치로 별도 기록한다. 기대 생존은 계약대로 12건 → 10.2건.

**품질 티어.** 실측 `lite` $0.2129(n=4, **0/4 ok**) vs 과금 기록 있는 cli/api $1.7197(n=4, **4/4 ok**),
Fisher 정확검정 p=0.029. 팩의 lite $0.27 은 재현되지 않는다.
**그러나 이 증거는 티어와 제공자를 분리하지 못한다** — lite 4건은 전부 `openai:gpt-5.6-terra`
(DECISIONS 10-4 의 자동 생산자 전환 기간)이고 비교군 4건은 전부 `anthropic:claude-opus-4-8` 로
두 축이 표본에서 완전히 겹친다. 그래서 은퇴 사유를 "검색량 축소가 원인"이라 적지 않고
**그 조합이 게이트급 회차를 하나도 내지 못했다**는 사실만 적는다. openai 경로는 이미 config
기본값에서 내려와 있다.

은퇴 방식은 레지스트리 일괄 수정이 아니다. `tier: lite`(활성 40문항)를 **역사 기록으로 보존**하고
`registry.effective_tier()` 가 `LITE_TIER_RETIRED_AT = 2026-09-11` 이후 standard 로 승격시킨다.
40문항을 고쳐 쓰면 "그때 무엇으로 등록했는가"가 지워져 "왜 이 회차가 degraded 였나"를 되짚을 수 없다.
예측 파일에는 `pipeline_tier`(실제로 돈 티어)와 `registered_tier`(등록 시점)를 **둘 다** 남긴다.

**월 sub-cap 여유가 얇다.** 주 3건 = 13회차/월 기준 실측 $1.7197 → 월 **$22.36** (cap $25 의 89%,
한도 내 최대 14회차). 설계서가 표준 티어 목표로 잡은 $2.5~4 로 실현되면 월 $32.5~52 로
**한도를 넘는다**. 그 경우 주 2건으로 내리거나 sub-cap 을 올리는 결정이 필요하며,
지금 정하지 않고 첫 5회차 실측 뒤 재판정한다.

**`mu-margin-qoq-fq1fy27` 마감 기재.** `deadline: null` 이면 orchestrator 프리플라이트가
"판정기준 불변 원칙상 자동 기록하지 않음"으로 예측을 거부해 이 질문이 영구히 미예측으로 남는다.
등록 시점 question 본문이 이미 명시한 "2026년 12월 하순 예상"의 상한으로 `2026-12-31` 을 기재했다.
발표일 자체는 **[미검증]** 이고 D-30(2026-12-01)에 재확인한다. `resolution` 무변경, 예측 0건.

**`asml-eps-beat-2026q3` 는 준비만 했다.** 시크릿 이전 단계 프리플라이트는 전부 통과한다
(active · fixed 2026-10-14 · 등록필터 OK · 유효 티어 standard). 실행 팩의 하드 라인에
**"시크릿 미로드"** 가 있고 `run_forecast` 는 dry_run 이어도 `get_api_key()` 를 프리플라이트
안에서 호출하므로, 실행은 사용자 몫으로 남긴다. r1 파일과 failed 태그는 그대로 둔다 —
재분류가 아니라 회차 추가다.

**처리량 캘린더.** 미예측 활성 31건을 마감 가까운 순 주 3건으로 11주(2026-09-14~11-23)에 소진.
`fedfunds-upper-425` 와 `fedfunds-upper-450` 은 조건부 부정합을 함께 보기 위해 같은 주에 배치했다.
총 비용 31건 × $1.7197 ≈ **$53.3**(약 2.4개월치 sub-cap).

**기록.** `src/ai_fc/config.py` `LITE_TIER_RETIRED_AT` · `src/ai_fc/registry.py` `effective_tier` ·
`src/ai_fc/c5_certificate.py` `as_date` · `src/tests/test_inventory_hygiene.py`(13건) ·
`src/tests/test_c5_preflight.py`(+3건) · `docs/p3_gate_path/T05_RESULT.md`.

### 2026-09-11 — T06: 정지 규칙·부정 결과 선언을 코드로 고정 + 금지 행위 감지기

부정 선언은 늦게 정할수록 안 하게 된다. 20문항에서 나쁘면 "표본이 얇다", 30에서 나쁘면
"이번 분기가 특이했다", 49에서 나쁘면 "한 건만 더"다. 계약이 문턱을 결과 전에 고정한 이유이고,
`gate_review` 는 그 조건을 **사람이 다시 해석할 여지 없이** 계산한다.

**부정 선언은 두 조건의 논리곱**이다 — 문항 30 이상 **∧** 클러스터 CI90 하한 > 0.20.
하나만으로는 발동하지 않는다. 문턱·조건은 전부 계약에서 읽고, 계약을 못 읽으면 페일클로즈
기본값을 쓰되 통과 쪽으로 기울지 않는다. 현재 상태는 문항 7 · CI90 [0.06894, 0.31583] ·
중간검토 문턱 미도달.

**금지 행위 감지기 `gate_guard`.** 계약 `stopping_rules.never` 세 항목은 문장으로만 있으면
지켜지지 않는다 — 셋 다 조용히 일어날 수 있기 때문이다.

| 금지 행위 | 감지 |
|---|---|
| `gate_arithmetic_change` | `schema.sql` 두 SQL 리터럴 + `config.GATE_P3` 문자 일치 |
| 원장 행 삭제 | git 기준선 대비 `ledger.csv` 의 삭제된 줄 |
| `post_hoc_failed_tagging` | 기준선 대비 오버라이드 변경·삭제 + `forecasts/` 수정 |

**기준선은 git 이다.** 저장소 안 스냅샷 파일은 같이 조작될 수 있고 낡으면 거짓 안심을 준다.
**추가는 허용**한다(새 예측이 생기면 행도 태그도 는다) — 금지되는 것은 기존 행의 변경·삭제다.
**보류는 통과가 아니다** — git 기준선을 못 읽으면 위반으로 세고 exit 1.
CI 배선은 `verify.yml` 마지막 단계(PR 은 base_ref merge-base, push 는 HEAD~1).

**배지 문구 — 산술 충족도 '통과'가 아니다.** 리포트 배지가
`{"통과" if gate["gate_p3"] else "미달"}` 이었다. 지금은 "미달"이 찍히지만 산술이 충족되는 순간
**"통과"가 렌더링된다** — 계약 `status_wording.forbidden_words` 에 등재된 단어다. 미충족이면
`미달`, 충족이면 `산술 충족 · 통계적 미결 (N SE)` 로 바꿨다. 행 평균이 문턱 아래여도 SE 여유가
얇으면 통계적으로 미결이고, 그 구별이 사라지면 배지 하나가 프로그램 전체의 지위를 잘못 말한다.
남은 "통과"는 "P3 게이트 통과 전 …"(통과되지 **않았다**는 진술) 한 곳뿐이다.

**상태 파일을 만들지 않는다.** 리포트는 stdout 으로만 낸다 — 손으로 갱신하는 상태 파일은
낡으면 잘못된 다음 행동을 부른다(테스트로 고정).

**기록.** `src/ai_fc/gate_review.py` · `src/ai_fc/gate_guard.py` · `tools/gate_review.py` ·
`src/tests/test_gate_review.py`(15건) · `.github/workflows/verify.yml` ·
`docs/p3_gate_path/T06_RESULT.md`.

### 2026-09-11 — T07: 발굴 엔진·사구간 감시·추론 코어 v1.1 + 게이트 이후 로드맵(문서만)

**ML 게이트 저촉 0.** 어떤 항목도 해소 100+ 전 isotonic/Platt, 200+ 전 가중 결합,
extremization 을 도입하지 않는다. 공식 확률은 언제나 LLM rN(8-8)이다.

**① 질문 발굴 엔진.** 원장에서 earnings 0.02817 vs macro 0.19450 vs market-daily 0.27080 인
이유는 실적을 잘 맞혀서가 아니라 **질문의 구조**(발행자 예보 존재 · 임계 원거리 · 비개정 판정)다.
`question_discovery` 는 캘린더에서 발행자 예보가 있는 종류만 후보화하고(earnings·fomc·cpi·nfp·gdp),
`other` 는 σ 를 세울 수 없어 제외한다. **엔진은 임계를 정하지 않는다** — `Candidate.threshold` 는
항상 None 이고 성질 카운트는 최대 2/3 다(임계 원거리는 사람이 임계를 넣은 뒤에만 판정된다).
원장도 읽지 않는다. σ 힌트에는 `SELECTION.md` 가 잡아낸 실패 유형을 미리 박았다
(fomc 의 위원 이견 SD 의미론, gdp 의 중심·σ 출처 불일치, cpi 의 지평 불일치).

**② 사구간 감시.** 등록 시점은 **차단**, 예측 시점은 **경고만**이다 — 예측을 사구간 밖으로 미는
것이 곧 극단화이고 8-8 이 금지한다. 예측 시점 경고에는 "확률을 밀지 마라, 올바른 반응은 다음
질문의 임계를 다시 두는 것"이 반드시 붙는다. 이 구별이 흐려지면 감시기가 극단화 유도 장치가 된다.
실측: 정직 확률이 기록된 활성 25문항 중 **사구간 진입 0건**. 다만 나머지 36문항은 정직 확률이 없어
**판정 자체가 불가능**하므로, 출력은 커버리지(25/61)를 항상 함께 낸다 — 경고 0건은
"사구간 문항이 없다"가 아니라 "볼 수 있는 것 중에 없다"다.

**③ 추론 코어 v1.1.** 프리모템에 필수 3항을 추가하고 `PROMPT_VERSION` 을 `reasoning_core_v1_1` 로
전환했다. (a) 전제 개정 취약성 — `nfp-jul2026` 초판 −23K→+21K 개정으로 r1 의 전제가 소멸했다
(**초판 고정은 판정을 지켜주지만 추론의 전제는 지켜주지 않는다**). (b) 컨센서스 존재 여부 —
컨센 NOT FOUND 로 생산된 두 회차가 같은 66% 로 수렴했다. (c) 임계 z — **그리고 z 가 작다고
확률을 밀지 말라는 금지 문구를 함께** 넣었다. 없으면 체크리스트가 극단화 유도문이 된다.
가중 학습이 아니라 프롬프트 절차 변경이고, `reasoning_core_v1.md` 를 남겨 frontmatter 의
`prompt_version` 이 두 코호트를 구별하게 했다.

**④ 게이트 이후 로드맵 — 문서만, 코드 금지.** 해소 100+ isotonic 은 cross-fit·문항 클러스터
부트스트랩 평가·표시층 한정·raw 로만 게이트 판정. 200+ 가중 결합은 out-of-sample 가중만.
지금 코드를 두지 않는 이유: V13-D10 에서 PAV 를 적합했는데 배치는 0 이었던 사례가 있고,
**코드가 있으면 언젠가 돈다**.

**⑤ 트랙 정합 — 무변경.** ML 괴리 칩은 `due` 표시 전용(자동 재예측 없음, `ML_DIVERGENCE_PP`),
V13 기후 기저율은 T03 의 대상 0건 페일클로즈. edge 활성화는 P3 후.

**⑥ 연간 계획.** 50문항 도달은 소화 속도가 아니라 **마감 분포**가 정한다. 두 단위 목표를 병기한다 —
행 평균(정본) < 0.18 유지 **∧** 문항 등가중 0.22079 → < 0.18 하강. 행 평균만 보면 쉬운 질문을
여러 회차 재예측해 내릴 수 있고(현재 복수 회차가 primary 행의 50%), 두 단위가 같이 내려가야
그 하강이 실력이다. 틀릴 수 있는 지점 4개를 함께 적었다(마감 병목 · sub-cap 여유 $22.36/$25 ·
예약 손실 2건 · 문항 30 부정 선언 가능성).

**기록.** `src/ai_fc/question_discovery.py` · `src/ai_fc/dead_zone_watch.py` ·
`prompts/reasoning_core_v1_1.md` · `src/ai_fc/config.py` `PROMPT_VERSION` ·
`src/tests/test_question_discovery.py`(18건) · `docs/p3_gate_path/T07_RESULT.md`.

### 2026-09-11 — 추론 호출이 계약 위반 시 비용도 원문도 남기지 않고 죽던 결함 (실측·수정)

`asml-eps-beat-2026q3` r2 실행이 리서치 성공 직후 죽었다. `cost_log.csv` 에 `failed:pipeline:1/2`
**2행만**(리서치 general·devil, **$1.564**) 남고 추론 행도 예측 파일도 없었다. **돈은 나가고
기록은 0**이며, 무엇이 왜 틀렸는지 알 단서도 남지 않았다.

**원인.** `llm.reasoning_call` 이 쓰던 `client.messages.parse` 는 HTTP 응답을 받은 뒤
**post-parser 안에서** `TypeAdapter(ForecastResult).validate_json` 을 돌린다. `ForecastResult` 는
`@model_validator` 로 `anchor_pct + Σ(부호 있는 delta_pp) == probability` 항등식을 강제하는데,
**이 교차 필드 항등식은 JSON Schema 로 표현할 수 없어 서버가 막아주지 못한다** — SDK 의
`transform_schema` 는 `minimum`/`maximum`/`exclusiveMinimum` 조차 description 문자열로 강등한다
(전송 스키마에 해당 키워드 0개임을 로컬에서 확인). 즉 계약 전량이 클라이언트 전용이다.
위반 응답이 오면 `ValidationError` 가 `messages.parse` **안에서** 터져 `_usage_of`·`budget.add`
어느 쪽에도 도달하지 못한다. `_with_retries` 는 RateLimit/InternalServer/APIConnection 만 잡으므로
즉시 전파된다.

**왜 두 달간 안 드러났나.** ① 이 계약은 커밋 `af01a809`(2026-08-06)에서 신설됐다.
② p1-pipeline 의 마지막 **anthropic** 회차는 2026-07-15 이고, 2026-08-03 이후 산출은 전부
`openai/gpt-5.6-terra` 였다(DECISIONS 10-4). 즉 이번이 **계약 도입 이후 anthropic 추론 경로의
첫 실행**이다. ③ OpenAI 경로는 `budget.add` 가 `model_validate` **보다 먼저**라 같은 위반이
3행을 남기고 `ProviderOutputError` 로 보인다 — 이 비대칭이 결함을 가렸다.
④ `src/tests/` 에 `reasoning_call`·`messages.parse` 를 건드리는 테스트가 **0건**이었다.

**내 몫.** 결함 자체는 선행하지만 **발동 확률을 내가 올렸다.** 어제 `PROMPT_VERSION` 을
`reasoning_core_v1_1` 로 바꿨는데(커밋 `95454428`), v1.1 의 `[4-A]` 필수 3항은 임계 z 까지
재성찰하게 만들어 확률 재조정 유인을 키운다. 그런데 `[4]` 의 "각 원인을 반영해 최종 확률을
재조정한다"는 v1 부터 있던 문장이고, **재조정분을 `adjustments` 에 적으라는 말이 없다** —
적지 않고 확률만 옮기면 항등식이 깨진다. 직전 성공 회차는 65 +4 −3 −4 −5 = 57 로 맞췄다.
만족 가능하지만 빡빡한 계약을, 모델에게 알려주지도 않은 채 성찰만 늘린 셈이다.

**수정 세 가지.**

| # | 무엇 | 왜 |
|---|---|---|
| 1 | `messages.parse` → `messages.create` + **직접 검증** | 응답을 받으면 **무엇이 실패하든 `budget.add` 를 먼저** 한다. 응답은 이미 과금됐다 |
| 2 | 시도별 원문을 `db/scratch/*_reasoning_attemptN.json` 으로 덤프 | 원문이 없으면 사후 진단이 불가능하다 — 이번이 정확히 그 상태였다 |
| 3 | 항등식 위반 시 **교정 재시도 1회** | 위반은 대개 판단이 아니라 **기록 누락**이다 |

**교정 재시도는 기록을 고치지 판단을 고치지 않는다.** 재시도 지시는 "최종 확률은 절대 바꾸지
마라, 재조정을 `adjustments` 에 항목으로 추가하라"이고, **재시도가 확률을 바꾸면 그 자체를
실패로 본다**(`계약 교정 재시도가 확률을 바꿨다` → 기록 없이 중단). 교정이 판단을 움직이면
그건 교정이 아니다.

**프롬프트가 계약을 말하게 했다.** `STRUCTURED_SUFFIX` 에 항등식·CI 포함관계·중복 조정 금지를
명시하고, `reasoning_core_v1_1.md` 의 `[4]` 에 "재조정분은 반드시 `adjustments` 에 항목으로
남긴다 — 기록하지 않고 확률만 옮기면 출력 전체가 거부된다"를 넣었다. 모델이 모르는 규칙은
지킬 수 없다. **한계**: `STRUCTURED_SUFFIX` 는 `prompt_version` 에 기록되지 않는 비버전 문자열이라
이 변경은 예측 파일에서 추적되지 않는다.

**남은 한계.** OpenAI 경로(`llm_provider.py`)에는 교정 재시도가 없다 — 비용은 계상되지만
위반 시 `ProviderOutputError` 로 회차가 버려진다. 현 공식 제공자가 anthropic 이라 이번에는
손대지 않았다.

**기록.** `src/ai_fc/llm.py`(`_reasoning_once`·`_peek_probability`·`CONTRACT_RETRY_HINT`) ·
`src/ai_fc/reasoning_core.py` · `prompts/reasoning_core_v1_1.md` ·
`src/tests/test_reasoning_contract.py`(11건 — 계약 위반 시 비용 계상·원문 덤프·교정 재시도·
확률 변경 거부·전송 스키마에 항등식 부재까지 고정).
### 2026-09-11 — C5-A4: 월 상한 $50 + 비용 규칙 전면 개정 (사용자 결정)

사용자 지시: **"월 비용 50불 한정으로 가정하고 규칙 다 전면 수정"**. 금액 하나를 바꾸는 일이
아니라, 그 금액을 중심으로 서로 어긋나 있던 규칙들을 다시 맞추는 일이다.

**먼저, 세 가지가 어긋나 있었다.**

**① 오래 인용해 온 "sub-cap $25"는 아무것도 묶지 않았다.** `OPENAI_MONTHLY_BUDGET` 은
**provider** 캡인데, 게이트급 회차를 내는 것은 anthropic cli/api 경로다. 2026-09 지출은
**전액 anthropic $15.75 · openai $0**, openai 경로의 마지막 생산은 2026-08-29 다. 그런데
T05·T07·D1 은 전부 "주 3건이 sub-cap $25 를 넘는가"를 물었다 — 실제로 묶고 있던 것은
전역 $40 이었다. **내가 잘못된 상한을 놓고 처리량 결정을 물었다.** D1 은 그래서 질문이
틀렸고, 이 기록이 정정이다.

**② lite 티어 은퇴가 라벨에만 걸렸다.** T05 는 `openai:gpt-5.6-terra` + 축소 핀(검색 3~4회·
리서치 6000토큰) 조합을 "게이트급 회차를 하나도 내지 못했다"(0/4 ok, Fisher p=0.029)로
은퇴시켰다. 그런데 은퇴는 레지스트리의 `tier: lite` **라벨**에만 적용됐고, 그 라벨을 실제로
만들어 내던 예약 실행(`investing-refresh.yml`, 매주 토 11:15 KST, `forecast --due --max 3`)은
그대로 남아 있었다. lite 가 standard 로 승격된 2026-09-11 이후에는 같은 조합이
`pipeline_tier: standard` 로 **게이트 표본에 들어간다**. 은퇴한 생산자를 라벨만 바꿔 계속
돌리는 것이 그냥 돌리는 것보다 나쁘다. 다음 발화는 **2026-09-12** 였다.

**③ 문서가 두 개정 뒤처져 있었다.** `questions/FACTORY_GUIDE.md` 와 C5 설계서는 여전히
"월 상한 $20"이라고 적고 있었다($20 → $40 → $50).

**실측 (`calibration/cost_log.csv`, 2026-09-11).**

| 항목 | 값 |
|---|---|
| 표준 회차 단가 (anthropic cli/api) | **$2.303** (n=5 · $1.92~$2.75) |
| 자동 경로 회차 단가 (openai 축소 핀) | $0.204 (n=3) · 품질 **0/4 ok** |
| 2026-09 누적 | **$15.75** = 리서치 10.92 + **실패 4.24** + 추론 0.59 |
| 2026-08 | $2.60 (전액 openai) |

T05 가 근거로 쓴 $1.7197(n=4) 은 **+34%** 로 갱신됐다. 실패분이 그달 지출의 **27%** 였다
(원인은 같은 날 고친 `llm.py` 계약 사고 한 건). 그래도 **실패분은 상한에 센다** — 실패를
예산 밖으로 빼는 순간 상한이 거짓말이 된다.

**결정.**

| 규칙 | 이전 | 이후 |
|---|---|---|
| 전역 월 상한 | $40 | **$50** |
| 생산 경로(anthropic) sub-cap | = 전역 | **= 전역 (일부러 유지)** |
| 자동 경로(openai) sub-cap | $25 | **$2** |
| 예비 구간 | 없음 | **마지막 20%($40~$50)는 마감 D-30 이내 질문 전용** |
| 회차당 상한 | $4 | $4 (유지) |
| 케이던스 | 주 3건 (재판정 보류) | **주 3건 확정** — 13회차/월 × $2.303 = $29.9 = 상한의 60% |
| 무인 예약 실행의 공식 회차 생산 | 주 최대 3건 | **0건** (키 생존 smoke 만) |

**생산 경로 캡을 전역과 같게 두는 이유.** 게이트급 생산자가 하나뿐인데 그 하나에 전역보다
낮은 캡을 걸면, 남는 금액을 쓸 수 있는 주체가 없다 — 사용자가 정한 $50 이 사실상 그 캡으로
내려앉는다. "예비비"라는 이름의 사문화된 돈을 만들지 않았다.

**대신 예비 구간을 우선순위 가드로 만들었다.** 상한의 마지막 20% 에 들어가면 마감 D-30 이내
질문만 새 회차를 받는다(`reserve_zone_block_reason`). 돈은 쓸 수 있고 **대상**만 좁아진다.
막으려는 실패는 실측된 것이다 — `cpi-jun2026-accel` 은 예산이 앞선 질문들에 먼저 쓰여
**첫 예측 없이 만료**했고(처리량 소실 11.1%), 무예측 만료는 게이트 분자에 0 을 더한다.
마감을 알 수 없는 질문(rolling·tbd)은 임박 판정 불가라 **페일클로즈**로 막는다.

**케이던스가 마감을 앞서는지 확인했다(정하기 전에 쟀다).** 미예측 활성 **27건**, 가장 이른
마감은 **2026-11-30**(D-80), 60일 이내 마감 **0건**. 주 3건이면 27건 소진에 9주
(2026-09-14~11-15)로 최초 마감보다 **15일 이르다**. 월별 전망 2026-09 $36.5 · 10월 약 $30 ·
11월 약 $20 — 전부 $50 아래다. 게이트 분모 전망은 10월말 26문항 · 11월말 33 · **12월말 54** 로,
P3 의 50문항 조건은 **2026-12 월에 처음 충족 가능**하다. **상한 $50 은 게이트 도달 시점의
제약이 아니다 — 제약은 마감 도래 속도다.** 그래서 주 4건으로 올릴 이유도 없다.

**케이던스는 기계로 강제하지 않는다.** 밀린 뒤 따라잡는 주가 정당하게 생기고, 상한 두 개가
이미 바닥을 지킨다. 강제 목록에 넣으면 과잉 차단이 된다 — 무엇이 기계 강제이고 무엇이 운영
규칙인지 문서에 나눠 적었다.

**게이트 문턱·SQL·표본 정의는 한 글자도 건드리지 않았다.** 바뀐 것은 지출 규칙뿐이고,
게이트 상태는 그대로 **미결(0.33 SE)** 이다.

**기록.** `src/ai_fc/config.py`(`MONTHLY_BUDGET`·`MONTHLY_BUDGET_RESERVE_RATIO`·
`RESERVE_DEADLINE_DAYS`·`WEEKLY_FORECAST_CADENCE`) · `src/ai_fc/orchestrator.py`
(`reserve_zone_block_reason`) · `src/ai_fc/report.py`(`_budget_txt`) · `src/ai_fc/cli.py`
(확인 프롬프트에 이달 소진 표시) · `.github/workflows/investing-refresh.yml` ·
`CLAUDE.md` · `docs/P1_OPERATIONS.md`('비용·처리량 규율' 신설) · `questions/FACTORY_GUIDE.md` ·
설계서 2건 정정 주석 · `src/tests/test_budget_rules.py`(13건) ·
`test_investing_refresh_workflow.py`(무인 경로 공식 회차 생산 0 고정) · `test_c5_automation.py`.
### 2026-09-11 — V5.2 시나리오 부채꼴 폭의 절대 문턱 제거 (CI 적색 해소)

2026-09-11 예약 데이터 갱신 이후 `verify` 가 **main 에서 세 번 연속 실패**했다. 사유는
`test_projection_preserves_direction_changes` 의 `returns["S1"] - returns["S3"] > .25`
하나다. 코드는 바뀌지 않았고 데이터만 새로 들어왔다.

**정하기 전에 되짚었다.** 같은 후보 산출물의 과거 8개 판본에 테스트와 동일한 계산을
돌려 보면 폭은 고장난 것이 아니라 **꾸준히 내려오고 있었다**.

| 판본 | S1 | S3 | 폭 |
|---|---|---|---|
| 09-05 (4판본 동일) | +13.423% | −12.528% | 0.2595 |
| 09-09 | +12.986% | −12.771% | 0.2576 |
| 09-10 | +13.061% | −12.274% | 0.2533 |
| **09-11** | +12.798% | −12.142% | **0.2494** |

문턱 0.25 는 작성 시점 실측값의 **1.4% 아래**였고 지표는 하루 0.4% 씩 움직인다 —
코드가 그대로여도 며칠 안에 반드시 빨간불이 되는 자리였다.

**척도-무관 형태로 바꾸려 시도했고, 실패했다.** S2·S1 자체 밴드 폭(p90/p10)으로 나눈
비율은 같은 8판본에서 상대 변동이 **7.3%** 로 절대 폭(3.9%)보다 **더 불안정**했다.
부채꼴이 좁아지는 원인이 시나리오 내부 분산이 아니라는 뜻이라 이 정규화는 쓸 수 없다.

**관측값을 바짝 따라가는 절대 문턱을 매일 데이터가 새로 들어오는 자리에 두면, 그
테스트는 성질이 아니라 시장 국면을 지킨다.** 숫자를 0.24 로 내리는 것은 같은 덫을 며칠
뒤로 옮기는 일이라 하지 않았다.

**최종 형태는 다른 세션(`bbbdd43d`, PR #196)의 것을 채택했다.** 나는 단언을 지웠는데,
그쪽은 **코드가 이미 정의해 둔 판정으로 갈아끼웠다** —
`assert projected["distinctness_2027"]["gate_pass"] is True`. 가드를 잃지 않으면서
미고정 상수를 없애므로 내 삭제보다 낫다. 그쪽이 출처도 찾아냈다: `.25` 는 **2026-08-19
에 무관한 PR 에 딸려 들어온 값**으로 코드에 대응하는 규칙이 없었다. 같은 시점
`distinctness_2027` 은 통과였다 — 즉 "경로가 구별되지 않는다"는 신호가 아니었다.

이 항목이 남기는 몫은 **그 상수가 우연히 깨진 것이 아니라 깨질 수밖에 없었다**는 근거
(위 드리프트 표)와, **척도-무관 정규화가 대안이 될 수 없다**는 측정이다. 둘 다 테스트
docstring 에 병기했다 — 다시 넣고 싶은 사람이 숫자가 아니라 무엇이 깨지는 것을 막는지
부터 적도록.

**기록.** `src/tests/test_scenario_v5_2.py`.

### 2026-09-11 — 주 3건 케이던스를 로컬 예약으로 자동화 (사용자 지시)

C5-A4 가 무인 예약 실행의 공식 회차 생산을 3건 → **0건**으로 내렸다. 사유는 케이던스가
아니라 **생산자 조합**이었다 — `openai:gpt-5.6-terra` + 축소 핀이 게이트급 회차를 하나도
내지 못했고(0/4 ok), 그 조합을 매주 돌리던 것이 `investing-refresh` 스텝이었다.

그래서 케이던스 자체(주 3건)는 살아 있는데 **그것을 실행할 주체가 없어졌다.** 사용자가
"다음주에 자동으로 3건씩 계속 돌려"로 그 공백을 메우도록 지시했다.

**CI 로 되살리지 않았다.** 두 가지 이유다.

1. 저장소 시크릿에 `ANTHROPIC_API_KEY` 가 없다(`FRED_API_KEY`·`MAIL_APP_PASSWORD`·
   `OPENAI_API_KEY` 뿐). CI 에서 공식 회차를 내려면 은퇴한 openai 경로를 쓰거나 새 키를
   넣어야 하는데, 전자는 C5-A4 가 막은 바로 그 행위고 후자는 사용자만 할 수 있다.
2. C5-A4 가 "게이트 회차는 **로컬 anthropic cli/api 경로 전용**"(실측 $2.303/회차, 5/5 ok)
   이라고 못박았다. 로컬 예약은 그 규칙을 뒤집지 않고 그대로 따른다.

**형태**: Claude 데스크톱 예약 작업 `weekly-forecast-3`, 매주 **토 11:30 KST**
(`investing-refresh` 의 데이터 수집 11:15 KST 직후 — 갓 갱신된 base rate 로 돈다).
`forecast --due --max 3 --yes` 를 로컬에서 실행하고 PR·머지까지 간다.

- `--max 3` 은 임의로 올리지 못하게 프롬프트에 근거와 함께 못박았다(마감 도래 속도가
  병목이라는 C5-A4 의 측정). 올릴 이유가 생기면 실행하지 말고 사용자에게 묻는다.
- 당월 소진이 예비 구간($40) 이상이면 마감 D-30 질문만 받고, 막혀서 3건을 못 채우면
  억지로 채우지 않고 그대로 보고한다. 월 상한 근접 시 실행하지 않는다.
- 앱이 꺼져 있으면 다음 실행 때 돈다 — 무인 CI 와 달리 **머신이 켜져 있어야** 한다.
  이것이 이 방식의 유일한 약점이고, 대가로 은퇴한 생산자를 되살리지 않는다.

`investing-refresh` 의 공식 회차 생산 0건은 **그대로 둔다**. `test_investing_refresh_workflow.py`
가 고정한 계약을 건드리지 않았다.
