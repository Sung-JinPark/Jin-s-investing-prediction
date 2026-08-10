# 질문 표준 스키마 (L1 질문 엔진)

새 질문은 `/new-question` 스킬로 생성하며, 아래 필드를 모두 채워 `registry.yaml`에 등록한다.

```yaml
- id: <kebab-case-고유-id>          # 예: nvda-dc-beat-2026aug
  title: "<한 줄 제목>"
  question: >
    <해소가능 형태의 정밀 질문 — 기한·임계값·판정기준 내포>
  deadline: YYYY-MM-DD | rolling-<N>d | null(첫 예측 시 확정)
  resolution: >
    <YES 판정 조건을 rules-lawyer가 시비 걸 수 없게 명시.
     기준 데이터·스냅샷 시점·동률 처리까지.>
  resolution_source: "<판정에 쓸 공식 출처>"
  domain: earnings | macro | volatility | corporate-event | market-regime | crypto
  cadence: "<재예측 주기>"
  action_link: "<이 질문이 연결되는 포트폴리오 액션>"
  status: active | resolved | void
  created: YYYY-MM-DD
  notes: "<미확정 사항, [미검증] 표기 등>"
```

## 해소가능성 체크리스트 (모두 YES여야 등록)

1. **기한**: 언제 판정하는지 날짜가 박혀 있는가? (rolling이면 윈도우 규칙이 있는가)
2. **임계값**: 숫자 경계가 있는가? ("크게 상승" 금지 → "+5% 이상")
3. **판정 출처**: 제3자가 같은 출처를 보고 같은 판정을 내리는가?
4. **스냅샷**: 판정에 쓰이는 비교 기준(컨센서스, 기준가)이 사후에 움직일 수 있다면, 예측 시점에 스냅샷하도록 명시했는가?
5. **엣지 케이스**: 발표 연기, 지표 단종, 회사 인수 등 경계 상황의 처리를 정했는가? (최소한 "발생 시 void" 명시)

## rolling 질문 특칙

"90일 내 X" 형태는 매 예측이 **독립 인스턴스**다:
- 예측 파일에 `window_end: YYYY-MM-DD`를 기록한다.
- 해소도 인스턴스 단위로 한다 (윈도우 종료 시 채점).
- 겹치는 윈도우의 예측들은 캘리브레이션 집계 시 독립 표본이 아님을 리포트에 주석으로 남긴다.
