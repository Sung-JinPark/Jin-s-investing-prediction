# AI Superforecaster — 주식시장 예측 시스템

프론티어 LLM + 예측 스캐폴드로 시장 이벤트를 확률화하는 시스템.
설계 원본: [docs/design/system_design_v1.0.html](docs/design/system_design_v1.0.html) (13개 섹션 — 모든 설계 판단의 근거 문서)

## 목표 서열 (절대 순서 — 뒤집지 말 것)

1. **1차 (검증된 영역)**: 사용자의 포트폴리오 EXIT 트리거 이벤트를 확률화한다. "주가 맞히기"가 아니라 "이벤트 확률화"가 목표.
2. **2차 (조건부)**: AI 확률 vs 시장내재확률의 edge 검출 — **캘리브레이션 증명(Brier < 0.18, 해소 50문항+) 후에만** 활성화.
3. **3차 (선택)**: 마켓뉴트럴 페어 아이디어 — 가장 후순위.

## 5대 원칙 (모든 작업에 적용)

1. **이벤트 → 가격**: 예측 대상은 항상 기한·임계값·판정기준이 있는 해소가능(resolvable) 질문. 애매한 질문은 재작성 후 사용자 확인.
2. **Edge 없으면 무행동**: |AI확률 − 시장내재확률| > 10%p AND 앙상블 수렴 시에만 시그널.
3. **캘리브레이션이 왕**: 모든 예측은 예외 없이 불변 기록. 기록 없는 예측은 존재하지 않는 예측.
4. **자동화된 폭**: 정기 재예측 + 이벤트 트리거 재예측.
5. **라이브 포워드 only — 백테스트 절대 금지**: LLM은 과거 결과를 학습에 내포하므로 과거 질문 테스트는 원천 무효. "2024년 질문으로 검증하자"는 제안이 나오면 거부하고 이 원칙을 인용할 것.
   - **명문화된 예외 (dualdb 스펙 v1.0 §8, DECISIONS.md 8-6)**: 결정론 **수치 모델**(LPPL·GBM·DTW·k-NN 등)의 과거 데이터 적합·워크포워드는 허용 — 사전지식 오염이 없기 때문. 단 ① 산출물은 base rate 참조이지 캘리브레이션 표본이 아니며, ② 하이퍼파라미터(탐색 경계·기간 선택)가 정점 지식을 간접 내포할 수 있음을 caveat로 명기하고, ③ LLM이 개입하는 어떤 평가에도 이 예외를 적용하지 않는다.

## 하드 게이트 (위반 금지)

- **현재 Phase: P1 (자동화 스캐폴드 — src/ai_fc CLI 운영)**. Phase 전환은 사용자만 결정.
- **ML 게이트**: 표본 임계 도달 전 ML 도입 금지 (과적합 방지) — 캘리브레이션 보정(isotonic/Platt)은 해소 **100+** 후, 앙상블 가중 학습은 해소 **200+** 후에만. DL 가격 예측 학습은 하지 않는다 (설계서 §02 — 검증된 능력은 이벤트 확률화).
- **오픈웨이트 추론 레이어는 게이트 예외 아님을 명시**: `src/ai_fc/ml`(Chronos-Bolt·Chronos-2·T5·FinBERT)은 사전학습 모델의 **추론 전용** — 어떤 학습·가중치 갱신도 금지. 모델 결합은 **고정 규칙(중앙값·불일치 지수)만 허용** — 이는 학습이 아니다; 가중치 '학습' 결합은 해소 200+ 게이트 뒤. 출력은 base rate(`data/base_rates/ml_auto.md`) 공급용 참조 확률이며 매매 신호가 아니다. LLM 추론(rN)과의 괴리 15%p+는 `due`에 divergence로 **표시만** 된다 — 자동 재예측 실행 금지, 판단은 사람.
- **market_implied/edge '기록'은 edge 검출 활성화가 아니다**: `src/ai_fc/market`(Kalshi·Polymarket·CBOE 옵션)이 채우는 값은 P3 게이트 전까지 데이터 축적·표시 전용. 옵션 내재확률은 risk-neutral 측도 + 프록시 가정임을 항상 병기.
- P3 게이트(해소 50문항+ & Brier < 0.18) 통과 전, 시스템의 어떤 예측도 **실전 자금 결정의 단독 근거로 제시하지 않는다**. 모든 출력에 "참고 의견" 지위임을 유지.
- **채점 표본 규칙 (AUDIT-260715 8-2c, docs/DECISIONS.md)**: 원장은 전량 채점(투명). 단 대표 Brier·게이트 판정은 `research_status='failed'`(리서치 전멸 생산분 — frontmatter 자동 태그 또는 `calibration/research_status_overrides.csv` 메타) 제외 표본(`v_brier_primary`) 기준. 예측 파일·원장은 이 과정에서도 절대 무수정.
- 사용자의 하드 룰(VIX 25+, 드로다운 룰 등)은 확률과 무관하게 기계적으로 유지된다. 시스템은 **대체가 아니라 조기경보**.
- Brier 무능 도메인(> 0.22)은 시그널 발행 차단, 정보 제공만.

## 디렉터리 구조

```
CLAUDE.md                  ← 이 파일 (프로젝트 헌법)
docs/                      ← 부속 정본: ARCHITECTURE(계층 지도)·MODEL_REGISTRY(모델 상태)
                             ·DECISIONS(결정 기록)·KNOWN_LIMITS(한계 대장)·SELF_AUDIT_PROMPT
                             ·P1_OPERATIONS(운영)·design/(설계서 v1.0 HTML)
prompts/reasoning_core_v1.md ← §06 추론 코어 시스템 프롬프트 (예측 시 필수 로드)
questions/registry.yaml    ← 질문 레지스트리 (schedule=재예측 주기, drivers=공유 드라이버 태그)
forecasts/YYYY/            ← 예측 불변 기록 (1예측=1파일, 수정 절대 금지) + .hashes 앵커
calibration/               ← ledger.csv(append-only 원장) + research_status_overrides.csv(원장급 메타)
data/base_rates/           ← Outside view 라이브러리 (수동 + *_auto.md 재생성본)
data/ml_history/           ← 모델 산출 이력 (append-only JSONL — DB 재구축 원천)
src/ai_fc/                 ← 예측 엔진 (CLI: cd src && python -m ai_fc)
dualdb/                    ← 닷컴↔AI 이중시대 일간 비교 DB (자체 CLI·스펙·CHANGELOG)
reports/                   ← calibration.html · md/(시나리오 스펙) · audit/(검증 패키지)
db/                        ← SQLite 파생 인덱스 (gitignore — sync --rebuild로 재구축 가능)
```

## P1 CLI (자동화 경로 — Claude Code 스킬과 병행)

`cd src && python -m ai_fc <cmd>`: `due`(기한 도래) / `forecast <qid>`(파이프라인 실행) /
`resolve <qid>`(채점) / `report`(대시보드) / `sync --check`(불변성 검사). 상세: docs/P1_OPERATIONS.md.
Claude Code 스킬(/forecast 등)은 수동 심층 분석·질문 정밀화용으로 유지 — 두 경로 모두 같은 불변 파일 체계에 기록.

## 불변성 규칙 (가장 중요한 규약)

- `forecasts/` 아래 파일은 **생성 후 절대 수정·삭제 금지**. 오타가 있어도 그대로 둔다 (사후 수정은 캘리브레이션 조작).
- 재예측은 항상 **새 파일** (`YYYY-MM-DD_<question-id>_r<N>.md`, N = 회차).
- `calibration/ledger.csv`는 append-only. 행 수정 금지.
- 질문의 판정기준은 첫 예측 이후 변경 금지. 변경이 필요하면 질문을 폐기(status: void)하고 새 질문 생성.

## 스킬 (워크플로 진입점)

| 스킬 | 용도 |
|---|---|
| `/new-question` | 막연한 아이디어 → 해소가능 질문으로 정밀화 → 레지스트리 등록 |
| `/forecast <question-id>` | §06 절차(base rate→분해→premortem)로 예측 실행 + 불변 기록. 인자 없으면 재예측 기한 도래 질문 스캔 |
| `/resolve <question-id>` | 기한 도래 질문의 결과 판정 + Brier 채점 + 원장 기록 |
| `/calibration-report` | Brier·캘리브레이션 커브·도메인 skill·게이트 상태 리포트 생성 |

## 출력 규약

- 확률은 **1% 단위** ("약 20~25%" 금지), 80% 신뢰구간 병기.
- 모든 사실 주장에 출처(URL·날짜). 검증 못한 주장은 `[미검증]` 표기.
- 날짜는 절대날짜(YYYY-MM-DD), 시각은 KST 명시.
- 리서치에는 반드시 **반대증거(데블스 애드버킷) 섹션** 포함 — 없으면 예측 무효.
- 언어: 한국어 (기술 용어는 영어 병용).

## 비용 가드레일

- P0: 질문당 리서치는 서브에이전트 1~4개 이내. 월 API 예산 상한 개념 유지 (설계서 §09: 질문당 $1.5~4 목표).
