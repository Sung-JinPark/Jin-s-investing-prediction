# ADR-003 — LLM provider abstraction and approval-gated switching

- Status: accepted
- Date: 2026-08-01

## Context

공식 확률의 생산자는 모델 정체성에 종속된다. 기존 Anthropic 예측과 새 OpenAI 후보를 같은 성능 시계열로 합치면 트랙레코드가 끊기고, 과거 질문을 다른 provider로 다시 예측하면 hindsight 누수가 생긴다. OpenAI의 이동 alias는 underlying snapshot이 바뀔 수 있어 재현 가능한 모델 식별자로 사용할 수 없다.

## Decision

1. 공식 생산자는 계속 Anthropic이다. provider 전환은 설정만으로 강행할 수 없다.
2. `LLMProvider` 공통 계약 아래 Anthropic과 OpenAI Responses API adapter를 둔다.
3. OpenAI는 새 질문 allowlist에 한해 별도 append-only shadow ledger에 기록한다. 공식 확률과 산술 결합하지 않는다.
4. OpenAI model은 날짜가 포함된 snapshot 이름만 허용한다. alias는 fail-closed로 거부한다.
5. 공식 OpenAI 전환은 `calibration/approvals.csv`의 정확한 provider/model snapshot 승인 행이 있어야 하며 CI `provider-guard`가 이를 검사한다.
6. 전환 검토는 고유 해소 이벤트 10건 이상의 paired 비교, 비용 실측, 계약 준수율, 버전별 분리 집계와 사용자 승인을 전제로 한다.
7. `cost_log`는 provider, model snapshot, request id, cached input과 web search 사용량을 포함해 append-only로 기록한다.

## Consequences

- Anthropic 기존 경로는 동작 변화가 없다.
- OpenAI API 키나 날짜 snapshot이 없으면 shadow 실행도 시작되지 않는다.
- OpenAI 결과는 공식 트랙레코드를 오염시키지 않는다.
- 사용자 승인 전 공식 provider는 바뀌지 않는다.

## Rollback

공식 provider 설정을 `anthropic`으로 되돌리면 된다. adapter, registry와 shadow ledger는 감사 계보를 위해 유지한다.
