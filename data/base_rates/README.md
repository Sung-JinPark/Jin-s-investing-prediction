# Base Rate 라이브러리 (L3 Outside View의 원천)

목적: 예측할 때마다 base rate를 처음부터 다시 검색하지 않도록, 검증된 참조율을 축적한다.

## 파일 규칙

- 도메인별 1파일: `earnings.md`, `macro.md`, `volatility.md`, `market-regime.md`, `crypto.md`, `corporate-event.md`
- 각 항목 형식:

```markdown
### <참조 클래스 이름>
- **base rate**: X% (표본: N건, 기간: YYYY~YYYY)
- **출처**: <URL 또는 산출 방법> (수집일: YYYY-MM-DD)
- **신뢰도**: 검증 | [미검증]
- **사용 질문**: <question-id 목록>
```

## 규칙

1. `[미검증]` 항목은 anchor로 쓸 수 있으나, 예측 기록에 반드시 `[미검증]`을 함께 표기한다.
2. 예측 리서치 중 새 base rate를 발견하면 여기에 추가한다 (예측 파일과 달리 이 라이브러리는 **갱신 가능** — 단, 갱신 시 수집일 업데이트).
3. LLM 기억에서 꺼낸 수치는 반드시 웹 출처로 재확인 후 등록. 재확인 실패 시 `[미검증]`.
