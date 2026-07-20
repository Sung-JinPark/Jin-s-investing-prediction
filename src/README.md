# src/ — P1 Python 스캐폴드 (구현 완료)

`python -m ai_fc <cmd>` — 사용법은 [docs/P1_OPERATIONS.md](../docs/P1_OPERATIONS.md).

## 모듈 지도 (설계서 §07 구현)

```
ai_fc/
├── cli.py             typer 진입점: forecast/resolve/due/sync/report/notify/migrate-schedule
├── config.py          경로·모델(claude-opus-4-8)·가격·예산·게이트 상수
├── models.py          Question/ForecastRecord/LedgerRow/EvidenceBrief/DueItem
├── schemas.py         추론 코어 structured output (Pydantic)
├── registry.py        registry.yaml 로드 + schedule 정규화 + due 계산 (순수 함수)
├── files.py           관대한 파서 + 배타적-생성 라이터 — 불변성 집행 지점
├── orchestrator.py    파이프라인 스파인 (L1 프리플라이트→L2 리서치→L3 추론→L7 기록)
├── agents/            리서치 서브에이전트 (web_search_20260209, 데블스 생략 불가)
├── reasoning_core.py  prompts/reasoning_core_vN.md + 증거 합성 → messages.parse
├── aggregator.py      ProbabilityAggregator — P2 앙상블(L4) 교체 지점 (현재 SingleRun)
├── llm.py             Anthropic 래퍼: 재시도·미터링·예산 중단·pause_turn 처리
├── resolver.py        해소 판정 보조 (확인 후 원장 append)
├── db/                SQLite 파생 인덱스 (schema.sql·ingest·queries) + 드리프트 경보
├── report.py          자기완결 HTML 캘리브레이션 대시보드
└── notify.py          텔레그램 (fail-soft)
tests/                 합성 미래 질문 픽스처만 사용 (백테스트 금지 원칙)
```

## P2에서 추가될 것 (인터페이스 준비됨)

- `aggregator.py`에 MedianEnsemble (Claude+GPT × K=6, 중앙값, σ>8%p 재조사) — orchestrator 무수정
- `edge_detector.py` (옵션 IV·Kalshi 내재확률) — 캘리브레이션 게이트(해소 30+) 전까지 봉인
- 캘리브레이션 보정(isotonic/Platt)은 해소 100+ 후 (CLAUDE.md ML 게이트)

## 테스트

```powershell
cd src && python -m pytest tests/ -q
```
