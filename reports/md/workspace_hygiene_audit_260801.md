# 작업폴더 위생 감사 보고서

기준일: 2026-08-01  
감사 대상: `C:/workspace/ai-investing-codex`  
감사 시점 HEAD: `codex/ui-sidebar-overhaul@88254e8`  
단계: **T2 1단계 보고서 전용 — 이 보고서를 쓰기 전 파일 이동·삭제 없음**

## 1. 요약

추적 파일은 301개이며, 감사 시작 시 미추적 항목은 선행 T1 산출물 1개뿐이었다. 원본 원장·시나리오·raw·seed에는 손대지 않았다. 가장 큰 위생 문제는 테스트·Python 생성물 약 15.5MiB, `_site`와 일반 OS/에디터 잔재에 대한 ignore 규칙 누락, `reports/md` 30개가 정본/이력 구분 없이 한 폴더에 모인 상태다. `dualdb/data/raw` 61.46MiB와 두 파생 SQLite는 모두 Git에서 제외되어 대용량 원본을 Git LFS로 옮길 필요는 없다.

### 10항 판정표

| # | 점검 | 판정 | 핵심 근거 |
|---:|---|---|---|
| 1 | 루트 청결 | **결함** | 루트에 `.pytest_cache`, `.tmp-pytest`, `__pycache__`가 존재. 나머지 루트 항목은 설정·소스·데이터·문서 및 명시적으로 분리된 Sites 저장소 |
| 2 | `.gitignore` 실효성 | **결함** | 두 SQLite·raw·Python cache는 ignore되지만 `_site`, `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.bak` 규칙이 없음 |
| 3 | 캐시·쓰레기 | **결함** | 제외 환경 밖 cache 디렉터리 16개, `.pyc` 138개/1.53MiB, `.tmp-pytest` 335파일/14.02MiB. OS/스왑 잔재는 0개 |
| 4 | `reports/md` 증식 | **결함** | 파일 30개, 전부 `snake_case_YYMMDD.md`이지만 `archive/`와 정본 표식이 없음 |
| 5 | 문서 정본성 | **결함** | 생성 inventory는 current이고 DB_MAP의 46/48 seed 수치도 일치하나, `docs/ARCHITECTURE.md`는 2026-07-15 기준 수기 상태로 최신 provider·daily scenario 구조를 포함하지 않음 |
| 6 | naming 일관성 | **통과** | `reports/md` 30개 모두 YYMMDD 접미사·snake_case, ISO 날짜/무날짜 0개. 소스는 Python snake_case, 문서는 기존 대문자 정본 규칙을 유지 |
| 7 | 죽은 코드·데이터 | **결함** | `cycle_compare`는 schema에 남은 0행 deprecated 후보이고 소비 코드 검색 결과가 없음. 빈 디렉터리는 `.tmp-pytest` 아래 생성 잔재에 집중 |
| 8 | 대용량 위생 | **통과** | raw 61.46MiB는 ignore·로컬 보존, `_site`는 부재·미추적, 최대 추적 파일은 165,689바이트. 현재 Git LFS 필요 없음 |
| 9 | 테스트 배치 | **통과** | 추적 테스트 49개가 `src/tests`·`dualdb/tests`에 있고 모두 `test_*.py` 규칙 |
| 10 | 시크릿 노출 | **통과** | `python -m ai_fc security-check` → `secret pattern scan clean`; secret 유사 파일명 추적 0개 |

판정 합계: 통과 4, 결함 6.  
처리 분류: 안전 조치 4묶음, 승인 필요 4묶음, 절대 금지 6경로군.

## 2. 결함 상세

### H-01. 생성 캐시와 테스트 샌드박스가 루트 및 소스 트리에 잔존

- 경로: `.pytest_cache/`, `.tmp-pytest/`, 루트·`src/`·`dualdb/` 아래 `__pycache__/`와 `*.pyc`
- 근거 출력: 제외 환경(`.git`, `.venv`, `node_modules`, `codex-forecast-demo`) 밖 cache 디렉터리 16개, `.pyc` 138개/1.53MiB. `.tmp-pytest`는 335파일/14.02MiB.
- 범주: **안전**
- 조치: workspace 경계를 확인한 뒤 생성 디렉터리만 삭제. 가상환경과 분리 Sites 저장소의 cache는 이 작업에서 제외.

### H-02. 생성 사이트와 일반 잔재 ignore 규칙 누락

- 경로: `.gitignore`
- 근거 출력: `git check-ignore -v _site/index.html`은 아무 규칙도 반환하지 않았고 현재 `.gitignore`에도 `/_site/`, `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.bak`가 없다. 반면 `db/index.db`, `dualdb/db/dualdb.sqlite`, raw, `*.pyc`는 기존 규칙을 반환했다.
- 범주: **안전**
- 조치: 프로젝트 전체 빌드 산출물 `/_site/`와 범용 OS/임시 잔재 규칙을 보강한다.

### H-03. 보고서 정본과 과거 작업 지시가 같은 레벨에 혼재

- 경로: `reports/md/`
- 근거 출력: 파일 30개, YYMMDD 30개, `archive/` 0개. 최근 20커밋에서도 설계서·구현 보고서·감사서가 반복 추가됐다.
- 범주: **안전한 이동 가능, 후보 선택은 불명확**
- 조치: 내용 변경 없이 `git mv`만 허용되는 `archive/<주제>/` 구조가 적합하다. 다만 `src/ai_fc/scenario.py`가 `nasdaq_weekly_scenario_v3_1_1_260715.md`를 문자열로 참조하므로 단순히 오래된 날짜만으로 묶어 이동하면 안 된다. 이번 안전 커밋에서는 후보를 임의 선택하지 않는다.

### H-04. 수기 아키텍처 문서의 최신 구현 반영 지연

- 경로: `docs/ARCHITECTURE.md`, 대조 정본 `docs/generated/inventory.generated.md`
- 근거 출력: `inventory --check` → `inventory current`. 생성 inventory는 질문 38, forecast body 21, resolution 6/unique event 3, source contract 7을 기록한다. `docs/ARCHITECTURE.md`의 제목 기준일은 2026-07-15이며 이후 추가된 provider adapter·shadow dual-run·read-model contract·daily scenario 자동화가 계층표에 없다.
- 범주: **승인 필요** (`docs/` 수기 문서 정리·통합)
- 조치: 생성 inventory를 숫자 정본으로 유지하고, ARCHITECTURE는 수치 없는 개념 문서로 갱신하거나 superseded 표식을 붙이는 방안을 선택한다.

### H-05. deprecated 테이블이 schema에 존속

- 경로: `dualdb/schema.sql`의 `cycle_compare`
- 근거 출력: `rg cycle_compare` 결과는 schema·DB_MAP·과거 설계/CHANGELOG뿐이며 소비 소스가 없다. `docs/DB_MAP.md`도 `0행`, `alignment`로 대체된 사실상 폐기 항목으로 표시한다.
- 범주: **승인 필요** (추적 schema 변경)
- 조치: 호환성 기간을 정한 뒤 deprecated view 전환 또는 다음 schema major에서 제거. 이번 작업에서는 변경하지 않는다.

### H-06. 전역 naming·보존 정책의 명문화 부족

- 경로: 저장소 전체 문서 정책
- 근거 출력: 보고서는 `snake_case_YYMMDD.md`로 일관되지만 문서 정본은 `DB_MAP.md`, ADR은 숫자-kebab, Python은 snake_case로 계층별 규칙이 다르다. 이는 즉시 결함 파일이 아니라 규칙 부재 문제다.
- 범주: **승인 필요** (소급 rename 금지)
- 조치: 새 파일에만 적용할 짧은 naming·retention 규칙을 `CONTRIBUTING` 또는 CLAUDE 운영 규칙에 추가하고, 기존 파일은 링크 안정성을 위해 유지한다.

## 3. 제안 목표 폴더 구조

아래는 현재 구조와 목표의 차이만 표시한다. 금지 경로는 위치를 그대로 유지한다.

```diff
 C:/workspace/ai-investing-codex/
-├─ .pytest_cache/                 # 생성 잔재
-├─ .tmp-pytest/                   # 생성 잔재
-├─ __pycache__/                   # 생성 잔재
 ├─ .github/
 ├─ calibration/                  # 보호: append-only
 ├─ data/
 │  ├─ ml_history/                # 보호: append-only
 │  ├─ scenarios/archive/         # 보호
 │  └─ raw/                       # 보호·Git 제외
 ├─ forecasts/                    # 보호: 불변 기록
 ├─ reports/md/
+│  ├─ archive/                    # 확정된 과거 산출만 git mv
+│  │  ├─ ui/
+│  │  ├─ forecast/
+│  │  └─ platform/
 │  └─ <현재 정본·최신 핸드오프>
 ├─ src/
 ├─ dualdb/
 │  ├─ data/raw/                  # 보호·Git 제외
 │  └─ db/                        # 파생 SQLite·Git 제외
 └─ _site/                        # 생성물·Git 제외
```

## 4. T2 2단계 안전 정리 커밋 목록

정리 순서는 감사 보고서 작성 완료 후에만 실행한다.

1. workspace 내부의 `.pytest_cache/`, `.tmp-pytest/`, `__pycache__/`, `*.pyc` 생성물 삭제.
2. 생성물 경계를 벗어나지 않는 빈 디렉터리 삭제.
3. `.gitignore`에 `/_site/`, `.DS_Store`, `Thumbs.db`, `*.tmp`, `*.bak` 보강.
4. 보고서 archive 이동은 참조와 보존 기준이 명확하지 않아 이번 안전 커밋에서 보류.

예정 커밋 메시지: `chore(hygiene): remove caches and harden generated ignores`

안전 정리 후 필수 게이트는 `pytest -q` 전체, `python -m ai_fc sync --rebuild`, Pages용 사이트 빌드다. 하나라도 실패하면 이 정리 커밋을 revert한다.

## 5. 사용자 승인 대기 목록

아래는 이번 작업에서 실행하지 않는다. 각 문항은 이후 **예/아니오**로 결정할 수 있다.

1. **예/아니오:** `reports/md`에 archive 정책 문서를 두고, 코드·README 참조가 없는 완료된 UI/설계 핸드오프만 주제별로 `git mv`할까요?
2. **예/아니오:** `docs/ARCHITECTURE.md`를 최신 구현으로 다시 쓰고 생성 inventory를 유일한 숫자 정본으로 명시할까요?
3. **예/아니오:** 다음 DualDB schema major에서 0행 `cycle_compare`를 제거하거나 호환 view로 바꿀까요?
4. **예/아니오:** 신규 파일 전용 naming/retention 규칙을 추가하되 기존 파일은 rename하지 않을까요?

## 보호 확인

이번 감사와 후속 안전 정리에서 다음 경로는 이동·수정·삭제하지 않는다.

- `forecasts/**`
- `calibration/*.csv`
- `data/ml_history/*.jsonl`
- `data/scenarios/archive/**`
- `forecasts/.hashes/**`
- `dualdb/data/seeds/**` 및 기타 seed 원본
- `data/raw/**`, `dualdb/data/raw/**`

## 실측 명령·출력 발췌

```text
git ls-files | Measure-Object
  301
git ls-files --others --exclude-standard
  reports/md/branch_agent_topology_explainer_260801.md

git check-ignore -v db/index.db dualdb/db/dualdb.sqlite
  .gitignore:3:/db/ db/index.db
  .gitignore:5:/dualdb/db/ dualdb/db/dualdb.sqlite

size inventory
  dualdb/data/raw  64,447,667 bytes / 61.46 MiB / 153 files
  db                 323,584 bytes / 0.31 MiB / 1 file
  _site              absent

reports/md
  30 files / YYMMDD 30 / ISO date 0 / undated 0

test layout
  49 tracked test_*.py files under src/tests and dualdb/tests

python -m ai_fc inventory --check
  inventory current: docs/generated/inventory.generated.md
python -m ai_fc security-check
  secret pattern scan clean
```
