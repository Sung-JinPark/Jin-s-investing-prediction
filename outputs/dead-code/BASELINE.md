# Dead-code cleanup BASELINE

- recorded_at: 2026-08-31T07:18:37Z
- branch: 
- HEAD: c1b2b8b3c89b0663dd1da1ceed76e4ca5b7ee1ef
- python: Python 3.12.10
- ruff: ruff 0.16.5

## Scale
```
tracked .py: 746
src/ai_fc LOC:   58121 total
```

## Verification baseline
```
pytest src/tests -q  ->  932 passed, 7 skipped, 0 failed (427.88s)
ai_fc sync --check -> rc=0 [경고] Q1 quarantined probability benchmark/2026-07-20_fomc-2026-07-29-hike_r4@2026-07-31|market: probability 5.0 (fraction) is outside the canonical [0, 1] range 질문 38 / 예측 25 / 해소 6 
ai_fc inventory --check -> rc=0 inventory current: docs/generated/inventory.generated.md 
ai_fc audit-ledgers --check -> rc=0 ledger audit: accumulating=26 stalled=9 inactive=4 violation=2 planned=3 
ai_fc provider-guard -> rc=0 official provider approved: anthropic:claude-opus-4-8 
ai_fc sync --check          ->  rc=0  (Q1 quarantine 경고는 기존 상태)
ai_fc inventory --check     ->  rc=0  inventory current
ai_fc audit-ledgers --check ->  rc=0  accumulating=26 stalled=9 inactive=4 violation=2 planned=3
ai_fc provider-guard        ->  rc=0  anthropic:claude-opus-4-8
ai_fc security-check        ->  (별도 실행, 아래 참조)
tools/verify_track_record.py -> rc=0  A급 강한 증명
pytest src/tests/timeseries_v7/test_protected_v6_baseline.py -> 8 passed (1.24s)  ★ V7 보호 계보 가드
```

## 이 저장소의 핵심 가드

`src/tests/timeseries_v7/test_protected_v6_baseline.py` (8 tests, 1.24s) 가
`data/timeseries_v7/manifests/protected_v6_baseline.json` 대비 보호 계보를 검증한다.
**삭제 커밋마다 이 테스트를 반드시 재실행**한다 — RED-LINE 침범의 즉각 탐지기.
