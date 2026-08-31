# 죽은 코드 정리 — ai-investing 실행 프롬프트 (설계도 §6 인스턴스)

2026-08-31 1회차 실행으로 검증된 슬롯 채움본. 재실행 시 이 파일을 Claude Code에 투입한다.
1회차 결과·교훈은 `outputs/dead-code/DEAD_CODE_REPORT.md`.

## 1. ROLE & MISSION
이 저장소의 유지보수 엔지니어로서 참조되지 않는 코드를 제거하되 **동작을 100% 보존**한다.
성공 지표는 삭제 줄 수가 아니라 **잘못된 삭제 0건·동작 변경 0건**이다. 확신이 없으면 삭제하지 말고
Deferred로 보고하라 — 그것이 올바른 결과다. §4 RED-LINE은 어떤 이유로도 예외가 없다.

## 2. PROJECT CONTEXT
- 루트 `C:/workspace/ai-investing` · Python 3.12 · uv_build · **APP(비배포)**, PyPI 미공개
- 인터프리터 `.venv/Scripts/python.exe` (editable 설치, 비-editable wheel 금지 — config.py가 `__file__` 앵커)
- 명령 (추측 금지)
  - test: `python -m pytest src/tests -q` (935 passed / 7 skipped 기준)
  - test(비CI): `python -m pytest dualdb/tests -q` — `test_sentinels::test_ixic_coverage` **기존 실패 1건**
  - lint: `python -m ruff check . --select F401,F811,F841,ARG`
  - 검증: `cd src && python -m ai_fc {sync --check, inventory --check, audit-ledgers --check, provider-guard, security-check}`
  - 추적기록: `python tools/verify_track_record.py`
  - **보호 가드(필수·1.2초): `python -m pytest src/tests/timeseries_v7/test_protected_v6_baseline.py -q`**
  - typecheck/build: **없음**
- 진입점: `python -m ai_fc` (Typer 84개 명령) · `ai-fc` 콘솔 · `python -m dualdb <verb>` · 워크플로 18개(12 cron) · tools/·scripts/
- 동적 로딩: Typer 데코레이터 84개 · `dualdb/__main__.py`의 `import_module(f".models.{name}")` 4종 ·
  `data/contracts/website_data_lineage_v1.yaml`의 `builder:` 심볼 · `read_model_contract.py`의 32개 문자열 키 ·
  `dashboard.js`가 읽는 JSON 키 · `timeseries_v5/sources.py`의 `SOURCE_REGISTRY`
- 최대 반복 8 · 산출물 `outputs/dead-code/`

## 3. DEFINITIONS
설계도 §3 표를 따르되 이 저장소 실측 반영: **C(주석 코드) 0건 · F(고아 모듈) 안전표면 0건 · G(의존성) 해당 없음**.
실질 대상은 **A(미사용 import/지역변수)**와 D/E(무참조 심볼, Deferred 우선).

## 4. RED-LINE — 절대 삭제·변경 금지
설계도 §4 전 조항에 더해 **이 저장소 고유**:
1. **바이트 봉인 소스** — `model_code_hash`가 해시하는 전부:
   `src/ai_fc/timeseries_v2/{contracts,market_archive,dfm_cache,features,model,backtest,pipeline,artifact}.py`,
   `src/ai_fc/timeseries/{model,backtest,events,ledger}.py`, `timeseries_v3|v4|v5|v8/**` (rglob — 파일 추가·삭제도 해시 변경).
   해시는 `data/timeseries_v{2,3,4,5,8}/ledgers/*.jsonl`의 봉인평가 행에 박제 → 한 줄만 바뀌어도 V2·V3·V8 검증 동시 파손.
2. **V7 보호 스코프** — `ai_fc.timeseries_v7.protection`의 ROOT_SPECS(31)·GLOB_SPECS(15)·FILE_SPECS(14).
   `src/ai_fc/timeseries*`, `scenario_v5`, `scenario_v5_2`, `scenario*.py`, `src/tests/timeseries_v5|v6`,
   `test_multivariate_timeseries*.py`, `test_scenario*.py`, `test_ralph_timeseries.py`,
   `tools/*timeseries*|*scenario*|*v6*|atlas*.py`, `.github/workflows/timeseries*|scenario*.yml`.
3. **V7 집행 모듈** `src/ai_fc/timeseries_v7/**` — `protection.py` 변경 시 `scope_contract_hash` 변동 → baseline 검증 실패.
4. **감사 증거 스냅샷** `reports/**`, `docs/audit/**`, `outputs/**` (MANIFEST.sha256 동봉).
5. **감사 증명서에 sha256이 박제된 도구** — 현재 확인분: `tools/verify_v7_protected.py`, `tools/freeze_v7_contract.py`.
   신규 판정법: 파일의 현재 sha256이 어떤 `*.sha256`/`MANIFEST*` 본문에 있는지 검사(§7-4).
6. **Tier 3 고정 파일** `src/ai_fc/{cli,dashboard,read_model_contract}.py`, `dashboard_parts/**` —
   `scenario_v5/audit.py` DELIVERY_PATHS + 다수 테스트가 소스 문자열을 grep.
7. 불변 데이터 — `forecasts/**`(오타도 수정 금지), `calibration/**`(append-only), `questions/registry.yaml`,
   `data/contracts/**`, `data/ml_history/**`, `data/timeseries*/**`. (CLAUDE.md 불변성 규칙 · AGENTS.md)
8. `docs/generated/**`는 손으로 고치지 말고 `cd src && python -m ai_fc inventory`로 재생성.

## 5. DECISION RULES
설계도 §5 + 이 저장소 판정표:
- Typer `@app.command` 핸들러 84개 → 유지(문자열 호출)
- `dualdb/dualdb/models/*` 및 `run`/`render_md` → 유지(importlib 디스패치)
- 미사용 인자(ARG001/002/005) → 전부 Tier 3(인터페이스·스텁 시그니처)
- **암묵적 검증 대입** — 값은 미사용이나 호출 자체가 예외를 던져 계약을 이루는 경우
  (`max()` 빈 시퀀스, `datetime.fromisoformat` 형식 검증) → **Tier 3**. ruff가 unsafe-fix로 표시하지만 이유는 말하지 않는다.
- **부작용 있는 대입**(`next(reader)` 등) → 바인딩만 제거하고 호출은 남긴다
- `config.py` 경로 상수·`official_sources.py` `*_request` → Deferred(스킬·문서 참조 가능성)

## 6. PROCEDURE
Phase 0 베이스라인(위 명령 전량 기록) → Phase 1 `ruff` 탐지 → Phase 2 증거 3종 triage →
Phase 3 큐 항목 하나씩 삭제·검증·커밋 → Phase 4 전체 검증·보고.
**Phase 3의 매 커밋 전 보호 가드(§2)를 반드시 재실행한다.**

## 7. EVIDENCE STANDARD (Tier 2 삭제 요건)
1. ruff 출력(버전·파일:라인)
2. 전역 검색 0건 — 코드 외 파일 포함
   `rg -n -w "<symbol>" --hidden -g '!.git' -g '!.venv' -g '!reports' -g '!outputs'`
3. `git log -S "<symbol>" --oneline | tail -5` — 최근 3개월 도입이면 Tier 3
4. **[이 저장소 필수] 감사 증명서 대조** — 파일의 현재 sha256이
   `outputs/**/{ARTIFACTS,MANIFEST}*.sha256` 본문에 있으면 즉시 Tier 3
5. **[이 저장소 필수] RED-LINE 자동 판정** — 추정하지 말고 코드로:
   `ai_fc.timeseries_v7.protection`의 SPEC과 각 `model_code_hash` 대상 집합을 읽어 대조

## 8. COMMIT & ROLLBACK
브랜치 `chore/dead-code-<YYYYMMDD>` · 커밋 = 한 카테고리 × 한 디렉토리 ·
`chore(dead-code): remove <category> in <scope> [Tier N, <count> items]` ·
실패 시 원인 삭제만 revert(테스트·설정 수정 금지) ·
**명시 경로만 `git add`** — 이 저장소는 다중 세션이 같은 작업트리를 편집할 수 있다.

## 9. REPORT
`outputs/dead-code/DEAD_CODE_REPORT.md` — Summary / Removed / False Positives / Deferred / Tool Runs / Reproduce.
False Positives에는 반드시 "RED-LINE 추가 제안"을 채운다.

## 10. COMPLETION & STOP
완료(전부 AND): ruff Tier1·2 잔여 0 · pytest 신규 실패 0 · 보호 가드 통과 · CLI 검증 6종 rc=0 ·
보고서 완비 · 작업트리 clean.
정지(하나라도 OR): 같은 항목 2회 revert · Tier2 강등률 50% 초과 · RED-LINE을 건드려야 진행 가능 ·
베이스라인 실패 테스트가 통과로 바뀜 · 검증 명령 실행 불가.
**최종 검증은 자기 커밋만 담긴 격리 worktree에서** 수행한다(동시 세션 오염 차단).
