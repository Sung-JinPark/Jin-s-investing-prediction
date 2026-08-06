# 아키텍처 — 상용 예측 시스템 대비 계층 지도 (2026-07-15)

> 근거: 상용·학술 시스템 3렌즈 조사 (Halawi 2024 arXiv:2402.18563 · Bridgewater AIA arXiv:2511.07678 ·
> FutureSearch · Metaculus forecasting-tools · Samotsvety/GJP · QuantConnect LEAN · MS Qlib · Kedro/MLflow/CCDS).
> 결론 요약: **우리 구조는 LLM 예측 시스템의 표준 7단 파이프라인 + 퀀트 플랫폼의 계층 서열과 이미 동형** —
> 남은 갭은 구조가 아니라 배관 3개(섀도 캘리브레이션·K회 실행·드라이버 태그)와 운영 규약 명문화였고, 본 커밋에서 반영.

## 1. 계층 지도 (업계 어휘 ↔ 우리 구현)

| 업계 표준 계층 (Kedro/Qlib/LEAN 어휘) | 우리 구현 | 상태 |
|---|---|---|
| raw (불변 수집 원본) | `dualdb/data/raw/` (원본 파일 보존, 해시 명명) | ✅ |
| intermediate/primary | `dualdb/db/dualdb.sqlite` price/macro (재구축 가능) | ✅ |
| feature | `derived_daily` (vol·dd·RSI·norm), `data/base_rates/` | ✅ |
| model (모델 계층 + 레지스트리) | `src/ai_fc/{quant,ml,market}` + `dualdb/models` · 계보=`model_run`·`ml_history` · 상태=`docs/MODEL_REGISTRY.md` | ✅ |
| model_output (불변 버전) | `forecasts/YYYY/` (배타적 생성, r회차 = MLflow 버전 개념) | ✅ |
| reporting + 원장 | `calibration/ledger.csv`(append-only) → SQLite 뷰 → `reports/calibration.html` | ✅ |
| 실행 오케스트레이션 | `python -m ai_fc` (엔진) · `python -m dualdb` (데이터 백본) · 주간 예약 태스크 | ✅ |

**관통 원칙 (업계와 동일)**: 앞 계층 불변·뒤 계층 재생성 가능, 데이터는 패키지 밖 루트, 파생 인덱스는 gitignore+재구축 커맨드.

## 2. LLM 예측 표준 7단 vs 우리

| 표준 단계 (전 시스템 공통 수렴) | 우리 | 비고 |
|---|---|---|
| ① 질문 수집·생성 | registry.yaml + /new-question (rules-lawyer) | FutureSearch식 자동 질문 생성은 백로그 |
| ② 에이전틱 리트리벌 | 리서치 에이전트 (웹서치, 순차, 프로필별) | AIA 실증: 에이전틱 서치가 Brier 3.6배 차이의 원천 |
| ③ scratchpad 추론 | reasoning_core (§06: base rate→분해→premortem) | Halawi 프롬프트 구조와 동형 |
| ④ 앙상블 집계 | **K회 실행 중앙값 배관 신설** (`AI_FC_REASONING_RUNS`, 기본 1 — P2 게이트 후 활성) | "단일 실행은 불안정"이 전 시스템 공통 결론 |
| ⑤ 사후 캘리브레이션 | **섀도 필드 신설**: `shadow_extremized` (log-odds α=√3, 표시 전용) — 실 보정은 해소 100+ 게이트 뒤 | AIA: 프롬프트로는 hedging 교정 불가, Platt/extremize만 유효 |
| ⑥ 크로스-질문 일관성 | **drivers 태그 신설** (registry) — 공유 드라이버별 일관성 점검의 기반 | FutureSearch world-model의 최소 구현 |
| ⑦ 기록·채점·반복 | 불변 기록 + Brier 원장 + 자가감사 프로토콜 | frozen-web pastcasting 대신 라이브 포워드 (더 엄격, 반복은 느림 — 인지된 트레이드오프) |

## 3. 명문 규약 (DECISIONS 8-8)

- **공식 확률 = LLM 파이프라인 rN** (K>1이면 K회 중앙값). quant·ML·시장내재는 base rate 참조·divergence 견제 — 최종 확률에 산술 결합하지 않는다 (계층 귀속: v3.1.1 §1).
- **클램프**: 확률은 1~99% 정수 (스키마 강제) — 상위 봇들의 극단 캡핑 관례와 동일, 단일 환각의 재앙적 Brier 차단.
- **집계 함수**: 고정 중앙값 (가중 학습은 해소 200+ 게이트 뒤). Samotsvety식 geomean-of-odds 전환은 표본 축적 후 비교 검토.

## 4. 백로그 (구조 준비 완료, 활성화 대기)

| 항목 | 트리거 | 근거 |
|---|---|---|
| K=3~6 실행 중앙값 활성 | P2 게이트 (해소 30+, Brier<0.20) — 사용자 결정 | AIA·FutureSearch "run twice" |
| Platt/extremize 실 보정 | 해소 100+ (ML 게이트) — 섀도 열로 사전 검증 가능 | AIA 최대 단일 개선 |
| 모델 출력 상관 행렬 (수렴=중복? 검사) | ml_history 8~12주 축적 후 | WorldQuant 중복 기각 관례 |
| divergence 명확화 질문 자동 생성 (supervisor-lite) | 표시→명확화 목록 첨부, 실행은 사람 | AIA supervisor (0.1125 vs 0.1140) |
| 드라이버별 일관성 리포트 | 질문 15개+ 시 calibration-report에 섹션 | FutureSearch world-model |
| uv workspace (packages/{ai_fc,dualdb}) | 배포·의존 충돌이 실제로 발생할 때 (현재 불필요) | OSS 모노레포 관례 |
| 모델별 rolling skill 추이 (도메인→모델 단위 차단 정밀화) | 해소 20+ | 상용 decay/drift 감시 관례 |
