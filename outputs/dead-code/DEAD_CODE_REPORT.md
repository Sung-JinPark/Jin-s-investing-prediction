# DEAD CODE REPORT — ai-investing (2026-08-31)

브랜치 `chore/dead-code-cleanup-20260831` · 커밋 5개 · 반복 4회
설계도 원칙 P1: **성공 지표는 삭제량이 아니라 잘못된 삭제 0건이다.**

## Summary

| 지표 | Baseline | Final | Δ |
|---|---|---|---|
| 추적 .py | 746 | 746 | 0 (파일 삭제 없음) |
| 안전 표면 LOC | 41,605 | 41,588 | −17 |
| 삭제 항목 | — | **26** | F401 23 · F841 3 |
| pytest `src/tests` | 932 passed / 7 skipped / 0 failed | **935 passed / 7 skipped / 0 failed** | 신규 실패 0 |
| dualdb/tests | 53 passed / 1 failed(기존) | 53 passed / 1 failed(동일) | 변화 없음 |
| ruff Tier1·2 잔여 | 31 | **0** | −31 |
| 의존성 | — | +1 (`dev` extra: ruff, CI 미설치) | |

## Removed (Tier 1, 26건)

| 커밋 | 범위 | 건수 | 증거 |
|---|---|---|---|
| `4cbb1d71` | src/ai_fc | 8 | ruff F401/F841 + 재export 전역검색 0건 |
| `d7d41cd5` | src/tests | 7 | 동일 |
| `58b24973` | tools, scripts | 7 | 동일 + 감사 박제 대조 |
| `e3d35902` | dualdb | 4 | 동일 (연쇄 import 1건 포함) |

증거 3종 요약: ① ruff 0.16.5 `--select F401,F811,F841,ARG` ② 각 F401 심볼에 대해
`from <module> import <symbol>` 형태 외부 참조 저장소 전역 검색 → **재export 위험 0건**
③ 삭제 커밋의 `+` 줄 7개는 전부 다중 import에서 이름 하나만 뺀 줄 재작성 — 신규 로직 0.

**동작 보존 처리 1건**: `src/ai_fc/quant/feed.py:256` `header = next(reader)` 는 바인딩만 제거하고
`next(reader)` 호출을 남겼다 — CSV 헤더 행 건너뛰기라는 부작용이 소멸하면 안 되기 때문.

## False Positives (도구가 unused라 했으나 삭제 불가, 6건)

| 심볼/파일 | 도구가 unused로 본 이유 | 실제 제약 | RED-LINE 추가 제안 |
|---|---|---|---|
| `tools/verify_v7_protected.py` (F401 ×2) | import가 코드에서 미참조 | **현재 sha256이 `outputs/timeseries_v7/task_results/V7-P0-002/ARTIFACTS.sha256`에 박제** — 수정 시 V7 감사 증명 파손 | `tools/*v7*` 를 보호 glob에 추가 |
| `tools/freeze_v7_contract.py` (F401 ×1) | 동일 | `.../V7-P0-003/ARTIFACTS.sha256`에 박제 | 동일 |
| `src/ai_fc/statistics_lab.py:2700` `observation_through` | 값이 미사용 | `max()`가 빈 시퀀스에서 예외를 던지는 **암묵적 검증** — 제거 시 동작 변경 | 판정표에 "암묵적 검증 대입" 항목 신설 |
| `src/ai_fc/statistics_lab.py:2764` `generated_time` | 동일 | `datetime.fromisoformat`이 형식 검증 역할 | 동일 |
| `src/ai_fc/dashboard.py:215` `qmap` | 값이 미사용 | dashboard.py는 `scenario_v5/audit.py` DELIVERY_PATHS 바이트 목록 + 다수 테스트가 소스 문자열 grep | `src/ai_fc/dashboard*` 를 Tier 3로 고정 |

## Deferred (Tier 3 — 사람 판단 필요)

| 항목 | 건수 | 삭제 시 리스크 | 확인 대상 |
|---|---|---|---|
| 미사용 인자 ARG001/002/005 | 43 | 인터페이스 구현·오버라이드·스텁·람다 시그니처 — 제거 시 계약 위반 | 각 프로토콜 정의 |
| `config.py` 경로 상수 | 11 | `.claude/skills/*/SKILL.md`·문서가 참조하는 공개 표면 가능 | 스킬 작성자 |
| `official_sources.py` `*_request` | 5 | 수집기 공개 API 후보 | 데이터 수집 담당 |
| `data_contracts.py` 3종 | 3 | 계약 검증 헬퍼 | 계약 담당 |
| DB 객체(K) | — | 이 작업 범위 밖 (설계도 §3) | DBA |

## Tool Runs

- `ruff 0.16.5` — `python -m ruff check . --select F401,F811,F841,ARG`
  - 탐지 74 → 실행 27(1건은 Tier3 강등되어 26 삭제) / 보고 47
  - 최종 잔여 **49 = ARG 43 + 박제파일 F401 3 + Tier3 F841 3** (Tier 1·2 잔여 0)
- `pytest src/tests -q` — 935 passed, 7 skipped
- `pytest dualdb/tests -q` — 53 passed, 1 failed(`test_sentinels::test_ixic_coverage`, **베이스라인에서도 동일 실패** — 미변경 트리에서 재현 확인, CI 미실행 영역)
- `pytest src/tests/timeseries_v7/test_protected_v6_baseline.py` — 8 passed (삭제 커밋마다 재실행, V7 보호 계보 무손상)
- `ai_fc sync --check` / `inventory --check` / `audit-ledgers --check` / `provider-guard` / `security-check` — 전부 rc=0
- `tools/verify_track_record.py` — rc=0

## Reproduce

```bash
git checkout chore/dead-code-cleanup-20260831
python -m pip install "ruff>=0.6,<1"
python -m ruff check . --select F401,F811,F841,ARG      # 잔여 49 = 전부 Tier 3
python -m pytest src/tests -q                            # 935 passed, 7 skipped
python -m pytest src/tests/timeseries_v7/test_protected_v6_baseline.py -q   # 8 passed
cd src && python -m ai_fc sync --check && python -m ai_fc inventory --check
```

## 이번 회차가 남긴 교훈 (다음 실행 프롬프트 개선)

1. **감사 증명서 대조를 증거 3종에 추가하라.** 이 저장소에서는 도구·스크립트의 sha256이
   `ARTIFACTS.sha256`/`MANIFEST.sha256`에 박제된다. 전역 문자열 검색만으로는 잡히지 않고,
   현재 파일 해시가 매니페스트 본문에 있는지 확인해야 한다 — 실제로 2파일을 이 검사로 살렸다.
2. **"암묵적 검증 대입"을 회색지대 판정표에 넣어라.** `max()`·`fromisoformat` 같은 호출은
   값이 미사용이어도 예외 발생 자체가 계약이다. ruff는 unsafe-fix로 분류하지만 이유는 설명하지 않는다.
3. **동시 세션 오염 주의.** 다른 세션이 같은 작업트리를 편집하면 전체 스위트가 남의 미완성 변경으로
   붉어진다. 최종 검증은 **자기 커밋만 담긴 격리 worktree**에서 수행해야 판정이 정직하다
   (이번에 4건 실패 → 격리 후 0건으로 확인).
