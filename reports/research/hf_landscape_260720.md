# Hugging Face 생태계 심층 리서치 종합 — 시계열·금융·물류·평가·구조 (2026-07-20)

> 4트랙 병렬 딥 리서치 종합본 (트랙당 30~40 웹소스, 전 항목 [source] 병기 원문은 각 트랙 노트).
> **지위: 참고 의견 — 도입 실행은 전부 별도 지시 대기** (토큰·비용 규율). 성능 수치 다수는
> 제작자 자기보고 — 도입 전 자체 검증 필수.

## 0. 경영 요약 (5줄)

1. **시계열**: 현 스택 3종(Bolt·C2·T5)은 전부 Amazon Chronos 혈통 — 중앙값 결합의 독립성 가정이 약함.
   **TiRex-2(38M, Apache, fev-bench 2위)·TimesFM-2.5(Google)·Sundial(경로 샘플 네이티브)**로 이질 앙상블 전환이 최대 개선.
2. **금융 NLP**: FinBERT 교체보다 **토픽 라우팅 추가**(nickmuchi 20토픽 or ModernBERT zero-shot)가 확실한 개선.
   FOMC 전용으로는 **gtfintechlab/FOMC-RoBERTa**(hawkish/dovish)가 fomc 질문군에 직접 유용.
3. **물류/수요예측**: HF에 생산급 물류 모델은 사실상 부재 — 방법론(간헐 수요·계층 조정·분위수 손실)만 이식 가치.
4. **평가**: 업계 표준은 Brier 단축이 아니라 **Brier+ECE+log score 다축** — `scoringrules` 라이브러리와
   fev식 부트스트랩 skill score가 우리 원장 보강의 정공법. **ForecastBench 데이터셋**(야간 갱신)은 외부 base rate 소스.
5. **구조**: 우리 결핍은 배치가 아니라 **선언 파일 부재** — pyproject·uv.lock·.gitattributes 추가로 해소 (이동 0건, 완료).

## 1. 시계열 파운데이션 모델 — 도입 우선순위

| 순위 | 모델 | 크기/라이선스 | 근거 | 유보 |
|---|---|---|---|---|
| 1 | **TiRex-2** (NX-AI) | 38M · Apache-2.0 | fev-bench 2위를 Chronos-2의 1/3 크기로. xLSTM — 혈통·벤더·데이터 전부 상이 → 앙상블 분산 감소 최대. CPU 공식 지원, 공변량(과거+미래) | 분위수 API 카드 미명시 — 도입 전 1회 실검증 |
| 2 | **TimesFM-2.5** (Google) | 200M+30M 분위수 헤드 · Apache-2.0 | GIFT-Eval·fev 상위 고정, 연속 분위수, ctx 16k, 벤더 다양성 | 스택 내 최대 크기 (주간 배치엔 무리 없음). LoRA 파인튜닝 기능은 **절대 사용 금지** |
| 3 | **Sundial-base-128m** (Tsinghua) | 128M · Apache-2.0 | **네이티브 샘플 경로**(flow-matching) — 경로 질문 정공법, T5 상위 호환 후보 | 순위는 중하위 — '경로 생성 멤버'로만 |

- 목표 구성: 5멤버(C2·Bolt·TiRex-2·TimesFM·Sundial) 또는 Bolt·T5 은퇴 후 4멤버 — "중앙값 이상치 방어 3개+"를 혈통 독립으로 충족.
- **제외 확정**: Moirai-2(CC-BY-NC 비상업)·TTM-r3(NC-SA)·TiRex-1(NXAI 커뮤니티 라이선스)·Time-MoE/TTM-r2(포인트 전용)·TabPFN-TS(조건부 라이선스)·TimeGPT(폐쇄 API).
- 리더보드 현황: fev-bench 1위 Chronos-2(win 81.0%) — **현 C2 채택의 외부 검증**. GIFT-Eval 절대 상위는 Agentic 파이프라인이 점령 — 단일 모델 비교는 부문 필터 기준.
- 위험: 벤치마크는 일반 도메인 평균 — 금융 저 신호대잡음에서 TSFM 우위는 미미할 수 있고 캘리브레이션 문제 지적 연구 존재(arXiv 2510.16060). base rate 참조 지위 유지.

## 2. 금융 특화 NLP — 권고

| 우선 | 항목 | 내용 |
|---|---|---|
| 1 | **토픽 라우팅 추가** | nickmuchi/finbert-tone-…-topic-classification (20토픽, ~110M, 기성품 = 학습 게이트 준수) 또는 MoritzLaurer/ModernBERT-base-zeroshot-v2.0 (커스텀 라벨 런타임 지정). 검증: zeroshot/twitter-financial-news-topic (MIT, 4,118건) |
| 2 | **FOMC 스탠스** | gtfintechlab/**FOMC-RoBERTa** (ACL 2023, hawkish/dovish/neutral) — fomc 질문군의 성명서 사후 판정·스탠스 지수화 직접 사용 가능. 보조: CentralBankRoBERTa |
| 3 | 감성 조건부 교체 | tabularisai/ModernFinBERT (0.1B, Apache, ctx 8192) — **즉시 교체 금지**: phrasebank 100%-합의 + twitter-sentiment로 A/B 병행, ml_history에 신구 병기 후 전환 (감성이 base rate에 물려 있어 연속성 훼손 방지, DECISIONS 기록) |
| 4 | 엔티티 추출 (선택) | GLiNER (제로샷 NER, Apache, CPU) — 뉴스 주체 추출 |

**쓰지 말 것 (7유형)**: "stock prediction" 개인 업로드 전부 · LLM 주가 방향 예측(FinGPT-Forecaster — 사전지식 오염, 원칙 5 위반) · **금융 가격 특화 DL(Kronos — DL 가격 예측 금지 게이트 저촉, 성과 전부 백테스트)** · 0.99+ 정확도 주장(누수 신호) · NC 라이선스 운영 사용(FinE5·FinLang) · 정체된 2023 금융 LLM(FinMA·FinGPT LoRA) · FinDPO(가중치 NOT FOUND).

## 3. 물류·수요예측·이벤트 예측

- **물류/수요 모델**: HF "demand forecasting" 검색 9건 전부 개인 학습용 — 생산급 부재. M5·GIFT-Eval Sales 도메인·Nixtla 생태계(HierarchicalForecast)가 실체. **방법론 교차점 3개만 이식 가치**: ① 분위수 예측(이미 보유) ② 간헐 수요 ↔ 저빈도 이벤트 base rate ③ 계층 조정(reconciliation) ↔ drivers 태그 일관성 점검의 개념적 상위 호환.
- **LLM 포캐스터 2026 현황**: ForecastBench에서 2026-07-16 최초로 AI(Cassi AI)가 슈퍼포캐스터 통계 동급/상회 (caveat: 인간 예측은 2024 수집 외삽). Prophet Arena — 프론티어 LLM Brier 0.18~0.22 밴드, **ECE ≤ 0.05로 캘리브레이션은 시장 상회**. 우리 P3 게이트(Brier<0.18)가 프론티어 밴드 상단과 정합함을 외부 확인.
- **이식 후보 데이터셋**: `forecastingresearch/forecastbench-datasets` (야간 갱신, CC BY-SA) — 타 시스템 Brier를 도메인별 **외부 base rate**로 참조 (라이브 포워드 원칙과 무충돌 — 우리가 그 질문을 예측하는 게 아님). Halawi `YuehHanChen/forecasting` (5,516 질문, Apache).
- **사용 금지**: valory/autocast (2022 컷오프 — LLM 오염, 원칙 5 위반) · Polymarket 온체인 데이터셋(중복·품질 편차).

## 4. 평가 인프라 — 원장 보강 로드맵 (원장 무수정, 리포트 계층만)

| 도구 | 이식 내용 |
|---|---|
| **scoringrules** (frazane) | Brier 외 **log score·ECE** 병기 — 업계 3축(Prophet Arena: Brier+ECE+시장수익률) 대비 부족분 해소. properscoring 상위 호환, numpy 백엔드 |
| **fev 프로토콜** (AutoGluon) | 부트스트랩 CI 기반 skill score — P3 게이트 판정(Brier<0.18)에 **신뢰구간 병기** (v_brier_primary vs 시장 baseline 비교에 그대로 이식) |
| GIFT-Eval/GluonTS | 재현 시에만 — GluonTS 분위수 추정 편향 이슈로 직접 도입 대신 scoringrules 경유 |

## 5. 저장소 구조 벤치마킹 — 적용 완료/보류

**적용 완료 (2026-07-20, 이동 0건)**: 루트 pyproject.toml(uv_build, `ai-fc` 스크립트, 워크스페이스) · dualdb/pyproject.toml · .gitattributes(**불변 경로 `-text` 예외 — 해시 앵커 보호**, renormalize 미실행) · data/README.md(계층 지도) · docs/models/ HF 스타일 모델 카드 4종(frontmatter 메타 — 라이선스·게이트 감사 자동화 기반) · README 갱신.

**보류 (조건부/위험)**: uv.lock 커밋(uv 설치 확인 후) · src/tests→루트 이동(후순위, 별도 커밋) · **휠 배포 금지**(config.py `__file__` 앵커) · forecasts/·calibration/ 어떤 이동·개명·EOL 정규화도 **영구 금지**.

## 6. 다음 단계 제안 (전부 지시 대기 — 비용·게이트 순종)

1. **[소]** scoringrules 도입 + 리포트에 log score·ECE 병기 (~반나절, 원장 무접촉)
2. **[중]** TiRex-2 분위수 API 실검증 → 앙상블 4번째 멤버 편입 (ml_history 병행 기록 기간 2주)
3. **[소]** FOMC-RoBERTa를 sentiment 레이어에 fomc 전용 피드로 추가 (7/29 FOMC 전이면 이번 회의부터 스탠스 지수 축적)
4. **[중]** 토픽 라우터 도입 (FEEDS 5종 자동 분류 검증 포함)
5. **[소]** forecastbench-datasets 주간 pull → 도메인별 외부 base rate 자동 갱신 (`*_auto.md` 패턴)
6. **[대·후순위]** Sundial 경로 샘플러 검증 → T5 대체 판단

> 트랙별 원문(출처 전체 포함)은 내부 아카이브에 보존 — 이 파일이 공개 정본 요약.
> 확인일 2026-07-20 — HF 생태계 변동 빠름, 도입 시점 재확인 필수.
