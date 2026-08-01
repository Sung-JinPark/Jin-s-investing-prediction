# Codex 통합 마스터 프롬프트 구현 완료 보고서

- 기준: Grand Blueprint + UI 가독성 감사 + WP-15 LLM provider 전환 검토
- 구현일: 2026-08-01 KST
- 브랜치: `codex/ui-sidebar-overhaul`
- 공식 예측 생산자: **Anthropic 유지**

## 1. 실행 결론

마스터 프롬프트에서 코드로 안전하게 구현할 수 있는 범위는 모두 반영했다. 승인 또는 외부 계약 확인이 필요한 항목은 임의 활성화하지 않고, 실행 가능한 배관·계약·검증 가드와 정직한 상태 표기까지 구현했다.

핵심 결과는 다음과 같다.

1. Phase 0~4의 정합성·계보·read-model·Trust Center 기반을 완성했다.
2. 미래 시나리오와 과거 혁신 사이클을 서로 다른 확률 공간으로 분리했다.
3. UI 전수 가독성 감사를 변경 전·후 2회 수행하고 12px/44px/대비/overflow 기준을 통과했다.
4. Anthropic 동작을 보존한 provider interface, OpenAI Responses API adapter, shadow 이중 실행과 비용 원장을 구현했다.
5. 승인 없는 OpenAI 공식 전환과 이동 alias 사용은 CI에서 fail-closed로 차단한다.

## 2. Part A 구현

| 영역 | 구현 결과 |
|---|---|
| 정합성 | clean rebuild 기준 forecasts 21건, resolutions 6건, invalid market probability 2건 격리 유지 |
| 데이터 계약 | canonical `[0,1]`, probability space enum, correction/quarantine, source license manifest |
| DB 계보 | `schema_migrations`, deterministic `lineage_edge`, inventory/read-model schema 자동 생성 |
| 읽기 모델 | legacy 키 보존 + v2 schema 검증 + receipt lineage |
| 역사 아날로그 | `log10(index/100)`, anchor month, result-known, reference-only 계약, 한계와 미산출 민감도 명시 |
| UI 확률 공간 | 미래 분포와 사이클 비교를 ARIA 탭으로 분리, 과거 비교를 공식 확률과 결합하지 않음 |
| 보안 | 저장소 비밀 패턴 스캔과 verify workflow gate |
| 라이선스 | source registry에서 생성되는 `licenses.generated.md`와 drift check |

`±3개월` 재앵커링 유사도는 원시 거리 산출물이 append-only로 보존되지 않아 숫자를 만들지 않았다. UI와 read-model 모두 `not_computed` 및 구체적 이유를 노출한다.

## 3. Part B UI 감사 결과

변경 전 보고서는 `ui_readability_audit_260801.md`, 변경 후 보고서는 `ui_readability_audit_post_260801.md`다.

| 측정 | 변경 전 | 변경 후 |
|---|---:|---:|
| 모바일 예측 연구 `<12px` | 402 | 0 |
| 모바일 예측 연구 `<44px` | 45 | 0 |
| 390px 핵심 화면 overflow | 0 | 0 |
| 1080px overview overflow/소형 글자/소형 타깃 | 미측정 | 0 / 0 / 0 |
| 1440px flow HTML 대비 실패 | 작은 주황 텍스트 다수 | 112개 검사 중 0 |

명령 팔레트, 3단계 브리핑, Esc 닫기, 시장 지도 탭 전환을 실제 브라우저에서 조작했다. 최종 자기완결 Pages HTML은 `419,800 bytes`로 420,000 bytes 예산을 통과했다.

## 4. Part C OpenAI provider 검토와 구현

OpenAI의 현재 권장 통합 경로는 Responses API이며 built-in `web_search`를 지원한다. 구현은 이 경로를 사용한다.

| 후보 | 성격 | 공식 공개 단가: input / cached / output (USD, 1M tokens) | 판단 |
|---|---|---:|---|
| GPT-5.6 Sol | 최고 성능·장기 복합 작업 | 5 / 0.50 / 30 | 품질 후보 |
| GPT-5.6 Terra | 균형형 | 2 / 0.20 / 12 | 1차 shadow 후보 |
| GPT-5.6 Luna | 비용 최적화 | 0.20 / 0.02 / 1.20 | 저비용 비교군 |

근거: [Responses API 전환 가이드](https://developers.openai.com/api/docs/guides/migrate-to-responses), [web search 도구](https://developers.openai.com/api/docs/guides/tools-web-search), [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

현재 공식 문서에서 재현 가능한 날짜 snapshot을 확인하지 못했으므로 실제 OpenAI shadow를 자동 활성화하지 않았다. 코드는 날짜 snapshot 형식만 허용하며 alias를 거부한다. 향후 실제 snapshot을 확인한 뒤 신규 질문 allowlist에서만 shadow를 시작할 수 있다.

### 구현된 안전장치

- `LLMProvider` 공통 structured-output 계약
- 기존 Anthropic provider의 동작 회귀 0
- OpenAI Responses API + `web_search` adapter
- 날짜 snapshot 및 출력 계약 검증
- 신규 질문 allowlist shadow, 별도 append-only ledger
- provider/model snapshot별 model registry와 비용 기록
- provider별 월 비용 상한
- `approvals.csv`가 없거나 정확히 일치하지 않으면 공식 OpenAI 전환 차단
- CI `provider-guard`, `security-check`

## 5. 의도적으로 활성화하지 않은 승인 경계

- invalid benchmark `22.0`, `5.0`을 임의로 0.22/0.05로 고치지 않음
- unique-event gate v2를 기존 공식 gate로 교체하지 않음
- GARCH/RND/foundation model을 champion 또는 공식 확률에 결합하지 않음
- 외부 API 라이브 backfill과 재배포는 키·라이선스·공표 캘린더 확인 전 보류
- OpenAI shadow 데이터가 없는 상태에서 공식 provider를 전환하지 않음
- calibration 및 학습 가중 ensemble을 활성화하지 않음

이는 미완료가 아니라 마스터 프롬프트가 요구한 인간 승인·증거 경계다.

## 6. 최종 검증

- 전체 테스트: **250 passed**
- 파일↔DB 정합: `sync --check` 통과
- inventory drift: 통과
- official provider guard: `anthropic:claude-opus-4-8` 통과
- secret pattern scan: 통과
- track record 독립 검증: 해시·append-only·Brier 전건 통과
- Pages: 419,800 bytes, 외부 CDN 0, 모바일/데스크톱 overflow 0

Pytest cache 디렉터리 ACL 경고 1건은 테스트 결과와 산출물에 영향을 주지 않았다.
