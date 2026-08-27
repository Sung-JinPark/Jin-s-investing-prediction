# [상세 설계] 무료 오픈 데이터 레이어 확장 — PIT 정합 수집 설계 (2026-08-27)

> 원칙: 모든 신규 소스는 기존 계보(content-addressed receipt·불변 아카이브·available_at
> 규율·증분 커서)를 그대로 승계. **소스당 1개의 "PIT 계약서"** 없이는 피처화 금지.
> 라이선스·ToS 확인은 온보딩 태스크의 1단계 — 확인 전 수집 금지.

## 1. 소스 카탈로그 (Tier = PIT 신뢰도 × 가치)

### Tier A — 즉시 온보딩 (공식·무개정·PIT 명확)
| 소스 | 시리즈 | 주기 | available_at 규칙 | 예상 가치 |
|---|---|---|---|---|
| FRED(기존 확장) | **VIXCLS**, VXNCLS(나스닥 변동성) | 일간 | 기존 규칙(익일 세션 보수) | **최상 — VRP 즉시 가능, 신규 인프라 0** |
| CBOE 공식 CSV | VIX9D, VVIX, SKEW, VIX 선물 이력(2004~) | 일간 | EOD 산출 → 익일 개장 전 사용 금지 | 기간구조·꼬리·vol-of-vol |
| CFTC COT | E-mini NQ/ES·VIX 선물 포지션 | 주간 | **화요일 데이터, 금요일 15:30 ET 공표** — available_at=금요일 공표시각(3일 지연 하드코딩) | 포지셔닝 극단=변동성 상태 |
| Treasury FiscalData API | 경매·발행·금리 | 일간 | 공식 공표시각 | 유동성 공급 측 |
| SEC EDGAR company-facts | XBRL 펀더멘털 | 수시 | **acceptance_datetime = 완벽한 PIT** | (후순위) 지수 구성종목 집계용 |

### Tier B — 지연·개정 명시 후 온보딩
| 소스 | 내용 | PIT 함정 |
|---|---|---|
| FINRA 마진부채(기존) | 월간 | ~T+3주 지연 — 이미 규율화됨 |
| ICI 자금흐름 | 주간 MMF/펀드 | 수요일 공표, 추정치→확정 개정 — 이중 빈티지 필요 |
| policyuncertainty.com EPU | 일간 뉴스 기반 불확실성 | 학술 무료. 소급 재계산 가능성 → 다운로드 시점 스냅샷 동결 |
| NAAIM 노출지수 | 주간 | 목요일 공표 |
| AAII 설문 | 주간 | 목요일 공표. 접근 조건 확인 필수(등록/유료 전환 이력) — 확인 실패 시 제외 |
| Ken French 팩터 | 일/월 | 월 갱신 + 소급 개정 — **라이브 피처 금지, base rate 전용** |

### Tier C — 대안·주의 (온보딩은 사용자 결정 후)
- Wikipedia pageviews API / Google Trends(pytrends): 주의 채널(attention). PIT 안전하나
  예측력 재현성 논쟁(Preis 2013 재현 혼재) — 후보 등록만, 기대 낮게.
- GDELT: 방대·노이즈. V8 범위 외 보류.
- Stooq/야후: 기존 폴백 유지.
- **금지**: 스크래핑 ToS 위반 소스, 재배포 금지 데이터의 저장소 커밋(값은 DB, 원문은 receipt 해시만).

## 2. PIT 계약서 스키마 (소스당 1파일, contracts/data_sources/*.yaml)

```yaml
source_id: cboe_vix9d
license_check: {url: ..., verdict: personal_research_ok, checked_at: ...}
frequency: daily
publication_rule: "EOD 산출, 익영업일 09:30 ET 이전 origin 사용 금지"
revision_policy: none | estimate_then_final | retro_recalc
available_at_formula: "next_trading_session_open(obs_date)"
incremental_cursor: last_obs_date
receipt: content_addressed_sha256
prohibited: [원문 재배포, 지연규칙 우회]
```

## 3. 수집 아키텍처 (기존 패턴 복제)

```
소스 공식 엔드포인트 → fetch(증분 커서) → receipt(SHA256, 원문 미저장)
  → ObservationFact(obs_date, vintage/available_at, value, lineage)
  → 피처 빌더는 available_at ≤ origin 행만 조회(런타임 강제, R4 하네스 재사용)
```
- 개정 있는 소스(ICI 등)는 ALFRED식 이중행(vintage) 보존.
- 소급 재계산 소스(EPU)는 **다운로드 스냅샷 자체를 빈티지**로 취급(같은 날짜의 값이
  달라지면 새 vintage 행 — 덮어쓰기 금지).

## 4. 피처 사전 (전부 §02 예산 규율 하에서만)

| 피처 | 정의 | 채널 |
|---|---|---|
| VRP_t | VIX²_t/12 − RV̂_{t,21}(HAR) | 스케일·틸트(최우선) |
| TS_t | VIX9D/VIX − 1, VIX선물 근월/차월 베이시스 | 스트레스 상태 |
| VVIX_z, SKEW_z | 롤링 z(창=252, train 역할 적합) | 꼬리 형상 |
| COT_x | 비상업 순포지션의 26주 백분위(공표 지연 반영) | 포지셔닝 극단 |
| FLOW_z | ICI MMF 주간 증감 z | 대기자금 |
| EPU_z | EPU 21일 평균 z | 불확실성 |

피처 수 상한: **V8 1차 라운드 총 8개 이하**(§02 예산). 각 피처는 단독 사전등록 +
ablation 의무. 표준화 파라미터는 research_train에서만 적합.
