# Claude 검토 응답 형식

아래 형식을 그대로 사용하라. 구현 제안보다 먼저 수용 판정을 작성한다.

## 1. 최종 판정

- 전체: `ACCEPT / ACCEPT WITH CONDITIONS / REJECT`
- NASDAQ 구조 경로: `PASS / PARTIAL / FAIL / BLOCKED`
- 닷컴 교차자산: `PASS / PARTIAL / FAIL / BLOCKED`
- UI·확률공간: `PASS / PARTIAL / FAIL / BLOCKED`
- 불변 archive·배포: `PASS / PARTIAL / FAIL / BLOCKED`

## 2. 게이트 전수표

| 게이트 | 판정 | 직접 확인한 파일/필드/테스트 | 설명 |
|---|---|---|---|
| G0-1 | | | |
| ... | | | |
| G4 | | | |

미검증을 PASS로 표시하지 말 것.

## 3. 발견 사항

| 심각도 | 제목 | 파일·라인/JSON path | 실제 영향 | 재현 또는 근거 | 최소 수정안 |
|---|---|---|---|---|---|

결함이 없으면 “actionable finding 없음”이라고 명시한다. 일반적인 모델 개선 아이디어는
이 표에 넣지 말고 §5에 분리한다.

## 4. 수치 독립 재계산

- NASDAQ 5년:
- O 가격 5년:
- O 총수익 proxy 5년:
- BTC 네 case 종점:
- 2026/2027 구조 경로 MDD:
- 보고값과의 불일치:

## 5. 모델 설계 의견

다음 항목을 결함 판정과 분리해 평가한다.

- 일간 beta → 월간 수익 frequency transfer
- 모든 음의 월에 downside beta 적용
- selected-era hindsight/selection leakage
- S1 캘리브레이션 strength의 S2/S3·2027 전이
- 구조선과 GBM fan의 이중 생성 규칙

## 6. 후속 구현 우선순위

- 반드시 수정(P0/P1):
- 출시 후 수정(P2):
- 연구 backlog(P3/모델 고도화):
- 변경 불필요:

각 권고는 현재 계약을 바꾸는지 여부와 새 correction/version 필요 여부를 함께 적는다.

