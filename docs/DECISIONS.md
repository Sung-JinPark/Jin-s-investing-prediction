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
