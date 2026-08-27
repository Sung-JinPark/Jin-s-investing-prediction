# NASDAQ V8 RESEARCH & DATA EXPANSION PACK (20260827)

다변량 시계열 예측 문헌·실전 벤치마킹 → 무료 오픈 데이터 확장 → 과적합 방지 규율 →
V8 모델 로드맵 → Codex ralph 실행 스펙. **V8 open-data는 PROPOSED_NOT_APPROVED 상태였음 —
본 팩이 그 승인 심사용 상세 설계이며, 사용자 승인(결정 DV-1) 전 수집 태스크 착수 금지.**

## 읽기 순서
1. `00_RESEARCH_SYNTHESIS_BENCHMARK_20260827.md` — 문헌·대회·솔루션 증거 정본
2. `01_DATA_LAYER_BLUEPRINT_OPEN_SOURCES_20260827.md` — 소스 카탈로그·PIT 계약·피처 사전
3. `02_ANTI_OVERFIT_PROTOCOL_20260827.md` — 5층 방어(등록부·예산·FDR·Thresholdout·안정성)
4. `03_MODEL_ROADMAP_V8_20260827.md` — Stage 1~4 (틸트→다변량→TSFM→conformal)
5. `ralph_spec/` — 마스터/런처/백로그/config

## 핵심 원칙 (한 줄)
게이트·E0·outer 1회 불변. 데이터를 늘리는 만큼 §02의 방어층이 같이 늘어야 하며,
평균(방향)이 아니라 **분포·스케일 채널**에만 투자한다 (M6 IR -3.4의 교훈).

## 사용자 결정
- DV-1: 오픈데이터 확장 승인(Tier A부터 / Tier B 포함 / 보류)
- DV-2: 1차 피처 8개 선택(§01 피처 사전에서)
- DV-3: TSFM Stage 3 착수 시점(R5·Stage1 결과 확인 후 권고)
