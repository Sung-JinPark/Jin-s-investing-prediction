---
name: new-question
description: Formalize a vague forecasting idea into a resolvable question (deadline, threshold, resolution criteria) and register it in questions/registry.yaml. Use when the user says /new-question, proposes a new thing to track/predict, or asks "이것도 질문으로 만들어줘".
---

# /new-question — 질문 정밀화 (L1 질문 엔진)

## 절차

1. **초안 작성**: 사용자의 막연한 아이디어("NVDA 괜찮을까?")를 해소가능 질문으로 변환. `questions/TEMPLATE.md`의 스키마와 해소가능성 체크리스트 5항목을 적용.
2. **Rules-lawyer 체크**: 스스로 악의적 판정자가 되어 질문의 빈틈을 찾는다 — "발표가 연기되면?", "지표가 단종되면?", "동률이면?", "컨센서스는 어느 시점 값?". 빈틈마다 resolution에 처리 규칙을 추가.
3. **스냅샷 필요성 판정**: 판정 기준값이 사후에 움직일 수 있으면(컨센서스, 기준가, ATH 등) "예측 시점 스냅샷" 조항을 resolution에 명시.
4. **도메인·주기 지정**: domain(earnings/macro/volatility/corporate-event/market-regime/crypto), cadence(재예측 주기), action_link(연결되는 포트폴리오 액션)를 채운다.
5. **사용자 승인**: 완성된 질문 객체를 보여주고 승인받는다 (설계 원칙: "애매하면 재작성 후 확인"). 승인 전에는 registry에 쓰지 않는다.
6. **등록**: 승인 후 `questions/registry.yaml`에 append. `updated:` 필드 갱신.

## 좋은 질문의 기준 (설계서 §03·§11)

- 해소 주기가 짧을수록 좋다 — 캘리브레이션 표본이 빨리 쌓인다. 장기 질문(1년+)은 전략적으로 중요할 때만.
- 포트폴리오 액션에 연결되지 않는 질문은 등록하지 않는다 (호기심 질문은 비용만 소모).
- 이미 등록된 질문과 중복되면 기존 질문을 알려주고 중단.
