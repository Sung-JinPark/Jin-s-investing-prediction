# ADR-003 — LLM provider abstraction and approval-gated switching

- Status: accepted
- Date: 2026-08-01 (amended 2026-08-03)

## Context

공식 확률의 생산자는 모델 정체성에 종속된다. 기존 Anthropic 예측과 새 OpenAI 후보를 같은 성능 시계열로 합치면 트랙레코드가 끊기고, 과거 질문을 다른 provider로 다시 예측하면 hindsight 누수가 생긴다. OpenAI의 이동 alias는 underlying snapshot이 바뀔 수 있어 재현 가능한 모델 식별자로 사용할 수 없다.

## Decision

1. 기존 기록의 생산자는 Anthropic으로 보존한다. 2026-08-03 이후 자동 갱신의 공식 생산자는
   소유자가 승인한 `openai:gpt-5.6-terra`이며 과거 기록은 재작성·재분류하지 않는다.
2. `LLMProvider` 공통 계약 아래 Anthropic과 OpenAI Responses API adapter를 둔다.
3. 승인되지 않은 OpenAI 후보는 새 질문 allowlist에 한해 별도 append-only shadow ledger에
   기록한다. 공식 확률과 산술 결합하지 않는다.
4. OpenAI model은 명시적 성능 tier(`sol|terra|luna`) 또는 검증된 날짜 snapshot만 허용한다.
   tier 없는 family alias는 fail-closed로 거부한다.
5. 공식 OpenAI 전환은 `calibration/approvals.csv`의 정확한 provider/model snapshot 승인 행이 있어야 하며 CI `provider-guard`가 이를 검사한다.
6. 전환 검토는 고유 해소 이벤트 10건 이상의 paired 비교, 비용 실측, 계약 준수율, 버전별 분리 집계와 사용자 승인을 전제로 한다.
7. `cost_log`는 provider, model snapshot, request id, cached input과 web search 사용량을 포함해 append-only로 기록한다.

## Consequences

- Anthropic 기존 기록과 실행 경로는 유지된다.
- OpenAI API 키나 승인된 명시 모델이 없으면 공식 자동 예측은 시작되지 않는다.
- 신규 OpenAI 예측은 provider/model/request 계보가 분리되어 기존 점수를 재분류하지 않는다.
- 설정만 바꾸어 다른 OpenAI tier나 provider로 전환할 수 없다.

## Rollback

공식 provider 설정을 `anthropic`으로 되돌리면 된다. adapter, registry와 shadow ledger는 감사 계보를 위해 유지한다.
