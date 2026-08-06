# 1. Repository Baseline

## 1.1 Intake scope

- Project root: `C:\workspace\ai-investing`
- Intake date: 2026-08-06 KST
- Phase: Phase 2 — Codex intake, baseline revalidation, and implementation preparation
- Application source, model outputs, databases, ledgers, and snapshots were not modified.
- The archived `AI_INVESTING_PHASE1_AUDIT_PACK_260806.zip` is intentionally absent. Its absence is not a defect. ZIP manifest and whole-ZIP SHA-256 verification are explicitly outside this intake scope.
- The only repository files created in this phase are `AGENTS.md` and this report.

## 1.2 Git and worktree state

| Item | Observed value | Evidence |
|---|---|---|
| Current branch | `main` | `git status --short --branch` |
| Current HEAD | `9c4b876a9d446a43f261054fd3dc33ea7f1211b6` | `git rev-parse HEAD` |
| Upstream | `origin/main` at the same SHA | `git rev-parse origin/main` |
| Latest commit | `docs(handoff): add ChatGPT project and path audit package` | `git log -1` |
| Current worktree | `C:/workspace/ai-investing`, branch `main` | `git worktree list --porcelain` |
| Additional worktree | `C:/workspace/ai-investing-codex`, branch `codex/ui-sidebar-overhaul` | `git worktree list --porcelain`; not inspected because it is outside the specified project root |
| Tracked diff before intake | none | `git diff --stat`, `git diff --cached --stat` |
| Existing untracked material | Phase 1 audit/prompts and several review-package/report artifacts | `git status --short`; preserved without modification |
| Existing `AGENTS.md` | none inside the project root | exact-name repository search before creation |

The source-code baseline remains the Phase 1 implementation lineage. Comparing `dea62a1..HEAD` showed handoff/report artifacts and generated audit material, not application-source changes. The untracked Phase 1 files are pre-existing user work and were not staged, deleted, or reformatted.

## 1.3 Repository structure and principal entry points

| Area | Path | Entry point or role |
|---|---|---|
| Primary Python package | `src/ai_fc/` | `src/ai_fc/__main__.py` delegates to `src/ai_fc/cli.py::main`; package script is `ai-fc = ai_fc.cli:main` |
| Forecast orchestration | `src/ai_fc/orchestrator.py` | `run_forecast` performs preflight, research, aggregation, rendering, and official write |
| Question registry | `questions/registry.yaml`, `src/ai_fc/registry.py` | `load_registry`, `compute_due` |
| Forecast schema/provider validation | `src/ai_fc/schemas.py`, `src/ai_fc/llm_provider.py` | `ForecastResult`, `Adjustment`, `validate_forecast_output` |
| File and ledger writes | `src/ai_fc/files.py` | `write_forecast_exclusive`, `append_ledger_row`, `append_cost_log_row`, `append_benchmark_row` |
| Resolution/calibration | `src/ai_fc/resolver.py` | `resolve_question` appends resolved and benchmark outcomes |
| Read-model ingestion | `src/ai_fc/db/ingest.py`, `src/ai_fc/db/schema.sql` | `_sync_benchmark`, `v_benchmark_corrected`, `v_benchmark_valid` |
| Probability boundary | `src/ai_fc/probability.py` | `normalize_probability` requires an explicit source unit and emits canonical `[0,1]` fractions |
| Scenario model | `src/ai_fc/scenario.py`, `src/ai_fc/scenario_structure.py` | scenario simulation, quantiles, structural display paths, revision upgrades |
| DualDB package | `dualdb/dualdb/`, `dualdb/pyproject.toml` | `python -m dualdb`; ingest/derive/models/coverage/report/export commands |
| DualDB analog/context | `dualdb/dualdb/models/knn_analog.py`, `dualdb/dualdb/export/context_bridge.py` | historical neighbor computation and context serialization |
| Tests | `src/tests/`, `dualdb/tests/`, `conftest.py` | root `conftest.py` adds `src` and `dualdb` to the test import path |
| CI | `.github/workflows/verify.yml` and related workflows | Python 3.12 editable install, test, sync/audit/security/verification checks |

The official forecast path is:

`questions/registry.yaml` → `registry.load_registry` → `orchestrator.run_forecast` → research providers → `aggregator.KRunMedian` → `llm_provider.validate_forecast_output` → frontmatter/evidence rendering → `files.validate_new_record` → `_write_records` → exclusive forecast file plus append-only ledger/cost files.

# 2. Runtime and Dependencies

## 2.1 Runtime

| Item | Observed value | Assessment |
|---|---|---|
| OS | Windows 11 / PowerShell | CONFIRMED by runtime inspection |
| Active Python | CPython 3.12.10 | Matches `requires-python = ">=3.12"` |
| Python executable | `C:\Users\91ssj\AppData\Local\Programs\Python\Python312\python.exe` | Used for all intake tests |
| Additional registered Python | 3.14 present | Not used |
| pytest | 9.0.3 | Current root suite passed |
| pip | 25.0.1 | Available |
| uv | not installed | Environment limitation, not a code defect |
| `ai-fc` editable/package install | not installed | Root `python -m ai_fc` therefore fails unless `PYTHONPATH` is set or the command runs from `src` |
| `dualdb` installed package | not installed | Tests work because `conftest.py` injects the local path |

## 2.2 Package management and dependency declaration

- Root `pyproject.toml` declares `ai-fc` version 0.2.0, Python 3.12+, and the `uv_build` backend.
- Root workspace includes `dualdb`; `dualdb/pyproject.toml` uses the same Python floor and build backend.
- Optional PIT dependencies are declared as `duckdb>=1.3` and `pyarrow>=18`.
- No `uv.lock`, `requirements*.txt`, Poetry lock, or other environment lock was found. Exact transitive dependency reproduction is therefore not locked.
- The active environment already contains the packages required by the executed tests, including Typer, Pydantic, PyYAML, python-frontmatter, NumPy, SciPy, Pillow, DuckDB, and PyArrow. No package was installed, deleted, or upgraded during intake.
- `.github/workflows/verify.yml` uses Python 3.12 and `pip install -e ".[pit]" pytest`, then runs the source test suite and repository verification commands.

## 2.3 Import behavior

- From the repository root, `python -m ai_fc --help` returns `No module named ai_fc` because the package is not installed and the source layout is not automatically on `sys.path`.
- From `src`, `python -m ai_fc --help` succeeds.
- Root pytest succeeds because `conftest.py` explicitly inserts both `src` and `dualdb` into `sys.path`.
- This is an environment/launch-path issue, not a failing application import under the documented editable-install CI setup.

# 3. Test Baseline

## 3.1 Supplied Phase 1 logs

The required Phase 1 logs were read rather than treated as ground truth:

- `AI_INVESTING_MAIN_TEST_LOG_260806.txt` records the prior main-suite result.
- `AI_INVESTING_LEDGER_TEST_LOG_260806.txt` records ledger-focused checks.
- `AI_INVESTING_CLI_AUDIT_LOG_260806.txt` records CLI audit output.

These logs provide provenance, but the current-root suite and selected behavior were independently rerun.

## 3.2 Independent current-root results

All commands used `PYTHONDONTWRITEBYTECODE=1`, UTF-8 output, explicit local `PYTHONPATH`, and disabled pytest cache to avoid persistent test artifacts.

| Test | Result | Interpretation |
|---|---|---|
| Collection only | `383 tests collected in 3.53s` | Current root exposes the expected full test count |
| L0-adjacent targeted baseline | `17 passed in 9.51s` | Existing record validation, forecast write, provider-output, probability-contract, benchmark, and quant-integrity tests pass |
| Full current-root suite | `383 passed in 146.17s` | Current repository baseline is green |
| Scenario snapshot reproducer | weights `83/2/15`, 1,764 quantile cells, 0 mismatches, `passed=true` | Current scenario snapshot is deterministic under its serialized inputs |
| Extracted handoff package suite | `6 failed, 347 passed, 30 skipped in 105.87s` | Package-only reproduction is incomplete: failures are missing browser/UX evidence and missing `.git`, not current-root code regressions |

The extracted package failure categories were independently separated:

- missing UI/browser evidence: four dashboard evidence failures;
- missing UX audit report: one failure;
- missing Git metadata: one verifier failure;
- full raw data and full DualDB database are absent from the package;
- current project root, by contrast, contains `dualdb/db/dualdb.sqlite` (85,536,768 bytes), 454 raw-data files under `dualdb/data/raw`, and the U1 audit evidence.

No permanent database, snapshot, forecast, or ledger was changed by the executed tests.

# 4. Phase 1 Audit Claim Verification

## 4.1 Decision policy

The verdict vocabulary is restricted to: `CONFIRMED`, `PARTIALLY CONFIRMED`, `NOT CONFIRMED`, `BLOCKED BY MISSING DATA`, and `BLOCKED BY ENVIRONMENT`. A Phase 1 register status such as FAIL or PARTIAL is not copied into the Phase 2 verdict; each claim is checked against current code, data, or an independently executed test.

## 4.2 Defect-register verification

| ID | Phase 2 verdict | Independent evidence |
|---|---|---|
| HND-001 | NOT CONFIRMED | ZIP manifest and whole-ZIP SHA-256 verification are excluded by instruction. `docs/audit/phase1_260806/AI_INVESTING_PHASE1_ARTIFACT_SHA256_260806.txt` was read but its hashes were not treated as a fresh ZIP-integrity verification. |
| HND-002 | CONFIRMED | The extracted package test run produced `6 failed, 347 passed, 30 skipped`; the failures map to absent browser/UX evidence and absent `.git`. The current root independently produces `383 passed`, proving that package reproducibility and current-code health are different questions. |
| MOD-001 | CONFIRMED | `src/ai_fc/scenario_structure.py::_structural_paths` applies a shared detrended residual/strength form across scenarios. Independent snapshot inspection found pairwise normalized-path correlations effectively 1 within 2026 and 2027. |
| MOD-002 | CONFIRMED | `dualdb/dualdb/models/knn_analog.py::run` computes neighbor dates/distances/forward returns, while `dualdb/dualdb/export/context_bridge.py` serializes aggregate analog/era context rather than full neighbor lineage used to construct the display path; `src/ai_fc/scenario_structure.py::_analog_shape` consumes overlays. |
| MOD-003 | CONFIRMED | `src/ai_fc/scenario_structure.py` recalibrates selection alternatives to the same target depth, so calibrated depth invariance is mechanically induced rather than an untouched sensitivity result. |
| MOD-004 | CONFIRMED | The innovation-cycle reference originates from the fixed 26-value `_ANALOG_VALUES` series in `src/ai_fc/scenario.py`; the dashboard label presents it as a representative innovation-cycle line rather than an explicitly current selected-era ensemble. |
| MOD-005 | CONFIRMED | `src/ai_fc/scenario_structure.py::_year_residual`/`_structural_paths` process calendar-year segments separately, creating a potential January state reset instead of one continuous conditional process. |
| MOD-006 | CONFIRMED | The current scenario snapshot contains S2 sample count 302/20,000 and displays 2%; scenario generation uses a fixed reference and trailing GBM parameters. The reproducer confirmed the current `83/2/15` result, not its parameter robustness. |
| DATA-001 | CONFIRMED | The latest scenario r8 disclosure note contains the same lead disclosure repeatedly; the append behavior is in scenario upgrade logic and is not idempotent. No snapshot was modified during intake. |
| PRM-001 | CONFIRMED | `src/ai_fc/reasoning_core.py::build_user_prompt` inserts retrieved research text into the reasoning prompt without an explicit untrusted-data boundary or instruction-in-evidence rejection contract. |
| PRM-002 | CONFIRMED | `src/ai_fc/llm_provider.py::_citation_count` counts provider annotations, while text preservation and `src/ai_fc/quality.py` URL parsing use different representations; claim-to-source annotation objects are not durably preserved. |
| PRM-003 | CONFIRMED | `src/ai_fc/schemas.py::ForecastResult` and `src/ai_fc/llm_provider.py::validate_forecast_output` enforce bounds/order but not CI containment or anchor arithmetic. Pure validation probes accepted point 80 with CI `[45,75]` and anchor 55/no adjustments/final 63. |
| PRM-004 | CONFIRMED | `src/ai_fc/quality.py` grades URL/domain-tier properties, not claim-level entailment, availability, independence, or contradiction. |
| PRM-005 | CONFIRMED | DualDB digest context is injected generically rather than through a question-domain allowlist; the stored AAPL evidence contains market-cycle/analog context despite being a quarterly EPS question. |
| PRM-006 | CONFIRMED | `src/ai_fc/aggregator.py::KRunMedian` repeats identical question/evidence input and takes the median; no evidence split, role split, or registered diversity source is applied. |
| GOV-001 | CONFIRMED | `docs/DECISIONS.md` requires dated snapshots, while `src/ai_fc/llm_provider.py::require_dated_openai_snapshot` also accepts explicit tier slugs; documentation and runtime identity policy are not identical. |
| CAL-001 | CONFIRMED | `calibration/ledger.csv` contains six rows but only three unique resolved questions, with multiple revisions of one FOMC question. This is insufficient to establish generalized calibration skill. |
| OPS-001 | CONFIRMED | Registry inspection found 38 questions: 34 active and 4 resolved; 22 active items lack a forecast and AMD Q2 remained active after its 2026-08-04 deadline. `src/ai_fc/registry.py::compute_due` has expiry handling, but registry state can remain stale. |
| DATA-002 | CONFIRMED | The extracted handoff package lacks the full SQLite/raw source set needed to reconstruct exact neighbors and episodes. This is a package-scope limitation only: the current project root contains the full local DB/raw set, so current L0 implementation is not blocked by it. |
| PRM-007 | CONFIRMED | `src/ai_fc/schemas.py::ForecastResult.question_check` is free text and `src/ai_fc/orchestrator.py::run_forecast` has no typed READY/HOLD gate. The AAPL evidence/forecast records acknowledged ambiguity without a deterministic hold. |
| PRM-008 | CONFIRMED | `src/ai_fc/orchestrator.py::_research_status` and `refine_research_status` can produce `degraded`, but no guard exists between the refined status and `_write_records`. `src/ai_fc/files.py::validate_new_record` also accepts degraded status. A pure probe returned no validation error for degraded. |
| PRM-009 | CONFIRMED | Research-agent profiles do not forbid forecast probabilities, and stored AAPL evidence contains an upstream YES 48% / NO 52% recommendation, allowing anchoring before final judgment. |
| DATA-003 | CONFIRMED | `calibration/benchmark_ledger.csv` contains market probabilities `22.0` and `5.0`, with impossible Brier values `484` and `25`. `src/ai_fc/db/schema.sql::v_benchmark_valid` excludes them; no append-only correction CLI with explicit source units and supersedes exists. |

### Verdict count

- `CONFIRMED`: 22
- `PARTIALLY CONFIRMED`: 0
- `NOT CONFIRMED`: 1
- `BLOCKED BY MISSING DATA`: 0
- `BLOCKED BY ENVIRONMENT`: 0

`HND-001` is unconfirmed because its verification was deliberately excluded, not because an integrity failure was found.

## 4.3 Additional L0-specific probes

| Probe | Observed behavior | L0 consequence |
|---|---|---|
| CI excludes point | Accepted by `validate_forecast_output` | L0-2 required |
| Anchor arithmetic mismatch | Accepted by `validate_forecast_output` | L0-3 required |
| `research_status=degraded` | Accepted by `files.validate_new_record` | L0-4 required at official write boundary |
| Forecast expired AMD question | `orchestrator.run_forecast` raised `PreflightError` before research/write | L0-5 core behavior already exists; regression and write-time hardening remain |
| Benchmark correction | Invalid rows are filtered from `v_benchmark_valid`; pending generic corrections exist without approved normalized values | L0-6 needs an explicit, append-only correction workflow; source units remain NOT CONFIRMED |

# 5. L0 Implementation Mapping

No L0 implementation was started in this phase. The table below is an implementation map, not a completed-work claim.

| ID | 문제 | 현재 동작 | 대상 파일 | 대상 symbol | 추가할 validator 또는 guard | 테스트 파일 | 정상 테스트 | 실패 테스트 | backward compatibility 위험 | ledger 영향 | 권장 구현 배치 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L0-1 | 질문 READY/HOLD 상태 게이트 부재 | Registry has `active/resolved` status and free-text `question_check`; no typed READY/HOLD. All 38 registry entries have missing/empty `required_snapshots`, so empty lists bypass snapshot completeness. | `src/ai_fc/models.py`; `src/ai_fc/registry.py`; `src/ai_fc/orchestrator.py`; `questions/registry.yaml` only in a later approved migration | `Question`; `load_registry`; `run_forecast` | Add a typed `question_gate`/state with explicit `READY` or `HOLD`; validate after load and immediately before official write. HOLD must stop before official output. Do not silently default legacy active questions to READY. | Prefer new `src/tests/test_question_gate_v2.py`, plus focused cases in `src/tests/test_sprint2.py` | Explicit READY with valid question/snapshots reaches existing write path | HOLD, missing required snapshot definition, ambiguous resolution, or invalid state produces no official forecast/ledger append | High: legacy registry lacks the field. A migration/default policy could accidentally release all questions. Existing forecast files remain readable and must not be rewritten. | HOLD creates no official forecast or benchmark row; if research already incurred cost, cost handling must remain auditable | Batch A |
| L0-2 | CI가 point probability를 포함하는지 미검사 | Bounds and low≤high are checked, but point outside CI passes provider and file validators | `src/ai_fc/schemas.py`; `src/ai_fc/llm_provider.py`; `src/ai_fc/files.py` | `ForecastResult`; `validate_forecast_output`; `validate_new_record` | Add deterministic `ci_low <= probability <= ci_high` validation in the typed model/provider boundary, with defense-in-depth on rendered frontmatter | New `src/tests/test_forecast_contract_v2.py`; extend provider-output/record validation tests | Point equal to bounds or inside interval passes | Point below low or above high fails before any write | Low to medium: existing invalid legacy records must remain readable; enforce on new writes, not historical ingestion | Prevents new inconsistent official rows; no historical mutation | Batch A |
| L0-3 | anchor + signed adjustments = final 산술 미검사 | `Adjustment` stores positive `delta_pp` plus direction, but no sum check exists. K-run aggregation can also pair a median final with one representative reasoning object. | `src/ai_fc/schemas.py`; `src/ai_fc/llm_provider.py`; `src/ai_fc/aggregator.py`; `src/ai_fc/orchestrator.py` | `Adjustment`; `ForecastResult`; `validate_forecast_output`; `KRunMedian.aggregate`; `_frontmatter` | Compute signed sum (`up=+`, `down=-`) and require final probability within a declared rounding tolerance, recommended 0.5 percentage point / 0.005 fraction. Preserve an arithmetic receipt in new output metadata. Ensure the aggregate’s explanation and final value are from a coherent run or explicitly recomputed. | `src/tests/test_forecast_contract_v2.py`; aggregator regression tests | Exact and tolerance-bound positive/negative adjustment chains pass | Direction inversion, missing delta, total mismatch, or representative/final mismatch fails | Medium: legacy forecasts omit anchor/adjustment receipt in frontmatter; validate new provider objects and new writes without retroactive failure | Rejects internally inconsistent official forecasts before append | Batch A |
| L0-4 | degraded research가 공식 원장에 기록됨 | `_research_status` and refinement set degraded, then rendering/write proceeds. File validator accepts degraded. | `src/ai_fc/orchestrator.py`; optionally a new pure guard module; `src/ai_fc/files.py` for defense-in-depth metadata validation | `run_forecast`; `_research_status`; `_write_records`; `_persist_failed_costs` or current cost append path | Add `validate_official_write_gate(question, research_status, now, mode)` after refinement and immediately before `_write_records`. Permit only registered allowed states such as `ok`/`ok_low_primary`; degraded remains scratch/shadow. Preserve incurred provider costs even when official write is blocked. | New `src/tests/test_official_write_gate_v2.py`; extend `src/tests/test_sprint2.py` | Allowed research status writes forecast and ledger exactly once | Degraded/failed produces no official forecast or result/benchmark append; incurred cost record remains append-only | Medium: current AAPL degraded revision must remain readable and must not be deleted. Define whether `ok_low_primary` is allowed before coding. | Stops new degraded official rows; does not edit existing AAPL row; cost ledger may still receive a run-cost record | Batch B |
| L0-5 | deadline 경과 active 질문 기록 차단 | `orchestrator.run_forecast` already rejects when `q.deadline < date.today()`; direct probe on AMD raised `PreflightError`. `registry.compute_due` routes expired active questions toward resolution. No dedicated regression test or final write-time recheck was identified. | `src/ai_fc/orchestrator.py`; `src/ai_fc/registry.py` | `run_forecast`; `_now_kst`; `compute_due`; official write guard from L0-4 | Retain current preflight, use the repository’s KST clock consistently instead of bare `date.today()`, and recheck deadline at the official append boundary to close a long-run time-of-check/time-of-use gap | `src/tests/test_official_write_gate_v2.py`; `src/tests/test_due_expiry_v2.py` | Deadline today under the declared cutoff policy is accepted; resolved/non-active behavior remains unchanged | Deadline yesterday, state changed during run, or expired active question produces no official output | Low if cutoff semantics are explicit; timezone behavior could alter edge-of-day runs | Existing ledger untouched; blocks only new expired writes | Batch B |
| L0-6 | 잘못된 benchmark probability unit를 원본 수정 없이 정정할 공식 도구 부재 | `normalize_probability` supports explicit units; DB read view can apply approved generic corrections and excludes invalid values. Two bad rows and two pending correction entries remain. No CLI/tool enforces source unit, reviewer approval, or explicit supersedes. | New `src/ai_fc/benchmark_corrections.py`; `src/ai_fc/cli.py`; `src/ai_fc/probability.py`; `src/ai_fc/db/ingest.py`; `src/ai_fc/db/schema.sql`; a new append-only correction ledger or additive supersedes sidecar under `calibration/` after approval | New `validate_benchmark_correction`/`append_benchmark_correction`; `normalize_probability`; `_sync_benchmark`; `v_benchmark_corrected`; CLI command registration in `main` | Require target row key, raw value, declared source unit, normalized fraction, evidence URI/hash, reviewer/status, revision ID, and explicit `supersedes`. Append a new correction revision; never mutate the benchmark row or existing pending correction. Do not infer `22.0→0.22` or `5.0→0.05` without source-unit evidence. | New `src/tests/test_benchmark_corrections_v2.py`; extend probability-contract, ledger append-only, and DB-view tests | Approved correction with explicit unit and supersedes appears in corrected/valid view while source row remains byte-identical | Missing unit/evidence/supersedes, out-of-range normalized value, duplicate revision, or attempt to update/delete is rejected | High: existing generic `calibration/corrections.csv` has no explicit supersedes column. Rewriting its header would violate append-only history; use an additive ledger/sidecar or versioned schema | Adds correction rows only; original invalid benchmark rows and pending corrections remain preserved | Batch C |

### L0 gate placement

The reliable ordering is:

1. Registry load and typed question-state validation.
2. Initial READY/non-expired/definition preflight before any provider call.
3. Existing required-snapshot collection and provider-result contract checks.
4. CI and anchor-arithmetic validation on each structured forecast result.
5. Aggregation-coherence validation.
6. Refined research-status evaluation.
7. Final write-time READY/non-expired/research-status recheck.
8. Exclusive forecast write and append-only result ledger.
9. Cost logging on both accepted and blocked-after-provider paths.

# 6. Ledger and Data Integrity

## 6.1 Current write paths

- Official forecast content is rendered in `src/ai_fc/orchestrator.py` and passed to `_write_records`.
- `_write_records` writes evidence and calls `src/ai_fc/files.py::write_forecast_exclusive`, which uses exclusive file creation rather than overwrite.
- `append_ledger_row`, `append_cost_log_row`, and `append_benchmark_row` append CSV records.
- `src/ai_fc/resolver.py::resolve_question` appends calibration and benchmark outcomes and then synchronizes read models.
- `src/ai_fc/db/ingest.py::_sync_benchmark` and the DB views consume ledgers; `v_benchmark_valid` filters probability values outside `[0,1]`.

## 6.2 Integrity assessment

| Control | Status | Evidence/qualification |
|---|---|---|
| Forecast file overwrite prevention | CONFIRMED | `files.write_forecast_exclusive` uses exclusive creation |
| CSV append helpers | CONFIRMED | `files.append_ledger_row`, `append_cost_log_row`, and `append_benchmark_row` append rather than update rows |
| Canonical probability boundary | CONFIRMED | `probability.normalize_probability` requires explicit unit and validates fraction range |
| Invalid benchmark quarantine | CONFIRMED | `db/schema.sql::v_benchmark_valid` excludes out-of-range probabilities |
| Explicit benchmark correction supersedes chain | NOT CONFIRMED | Existing generic correction structure lacks the explicit supersedes field required by L0-6 |
| Degraded official-write prevention | NOT CONFIRMED | Current refined degraded status can reach `_write_records` |
| Expired question preflight | CONFIRMED | `orchestrator.run_forecast` blocked the expired AMD case |
| Final write-time expiry recheck | NOT CONFIRMED | No second deadline/state check immediately before append was found |

The two invalid benchmark rows must remain untouched. The pending entries in `calibration/corrections.csv` do not establish the original source unit; the normalized values are therefore NOT CONFIRMED. L0-6 must require evidence rather than apply a magnitude-based conversion.

## 6.3 Data availability distinction

- Current root: full local DualDB SQLite and raw files are present; L0 work is not blocked by missing data.
- Extracted Phase 1 review package: raw/full database and exact neighbor lineage are absent; package-only deep-model reconstruction is blocked.
- No durable data was rebuilt or synchronized during intake.

# 7. Prompt v2 Mapping

`prompts/v2/AI_INVESTING_PROMPT_V2_BLUEPRINT_260806.md` was mapped to current code as follows.

| Prompt v2 concern | Current implementation point | Intake result | L0/next mapping |
|---|---|---|---|
| Typed question proceed/hold decision | `schemas.ForecastResult.question_check`, `registry.Question`, `orchestrator.run_forecast` | Free text only; no deterministic READY/HOLD | L0-1 |
| CI contains point probability | `schemas.ForecastResult`, `llm_provider.validate_forecast_output`, `files.validate_new_record` | Missing and independently reproduced | L0-2 |
| Anchor/decomposition arithmetic | `schemas.Adjustment`, `ForecastResult`, `aggregator.KRunMedian` | Missing and independently reproduced | L0-3 |
| Research quality controls official status | `quality.refine_research_status`, `orchestrator.run_forecast` | Status is recorded but degraded does not block official write | L0-4 |
| Deadline/state validity | `orchestrator.run_forecast`, `registry.compute_due` | Initial expired guard exists; write-time recheck/timezone hardening needed | L0-5 |
| Canonical probability unit and correction governance | `probability.normalize_probability`, benchmark ledger/read views | Fraction contract exists; correction tool/supersedes/evidence gate missing | L0-6 |
| Untrusted research boundary | `reasoning_core.build_user_prompt` | Missing | Post-L0 prompt-security batch |
| Claim-level citation provenance | `llm_provider`, `quality.py` | Annotation/text representations diverge | Post-L0 provenance batch |
| Domain-relevant retrieval | DualDB digest/base-rate path | Generic context can enter unrelated questions | Post-L0 relevance batch |
| Research/judgment separation | `agents/profiles.py`, stored evidence | Upstream research can give probabilities | Post-L0 agent-contract batch |
| Ensemble independence | `aggregator.KRunMedian` | Identical-input repetitions measure sampling variability | Post-L0 ensemble-design batch |
| Point-in-time discipline | data fields and DualDB contracts | Repository has PIT concepts, but every future implementation must enforce `available_at <= as_of` and preserve vintage | Cross-cutting gate in `AGENTS.md` and tests |

Prompt v2 should be treated as a specification source, not executable truth. Its L0 clauses have concrete code targets above; its broader prompt-security, provenance, relevance, and ensemble proposals are intentionally deferred until after L0 acceptance.

# 8. Risks and Unknowns

| Risk or unknown | Classification | Required resolution before/while implementing |
|---|---|---|
| Original unit/evidence for benchmark values 22.0 and 5.0 | Missing-data provenance; values themselves are present | Do not infer. Require a source artifact or reviewer-signed unit declaration before approving correction values. |
| READY/HOLD migration for 38 legacy registry entries | Design/backward-compatibility risk | Choose an explicit migration policy. Default-to-READY is unsafe; default-to-HOLD can halt all forecasts. Record each release decision. |
| All registry entries have absent/empty `required_snapshots` | Code/data-contract weakness | Distinguish intentionally no-snapshot questions from undefined requirements; an empty list must not silently mean complete for questions that require a resolution snapshot. |
| K-run median result versus representative explanation arithmetic | Model-contract risk | Ensure final probability, anchor, and adjustments originate from one coherent object or construct a new aggregate explanation with its own receipt. |
| Deadline uses `date.today()` | Environment/timezone edge risk | Standardize on `_now_kst().date()` and define whether deadline-day execution remains allowed. |
| Degraded run costs when official write is blocked | Ledger semantics risk | Preserve incurred cost append without creating a forecast/result row; test both zero-call and post-call hold paths. |
| Existing generic correction CSV lacks `supersedes` | Append-only schema risk | Use a new versioned correction ledger or additive supersedes sidecar. Do not rewrite the existing header/history. |
| No dependency lock and `uv` absent | Environment reproducibility limitation | Use current green Python 3.12 baseline for L0; add/update locks only under separate authorization. |
| Root `python -m ai_fc` fails without install/PYTHONPATH | Environment launch limitation | Use editable install in CI or the exact `PYTHONPATH` commands in §10. Not an L0 code blocker. |
| Phase 1 package lacks full data/UI/Git metadata | Package reproducibility limitation | Do not use the package as the sole runtime baseline. Current root is the implementation source of truth. |
| Phase 1 ZIP integrity | Scope exclusion | NOT CONFIRMED by design; do not reinterpret as a defect. |

There is no current environment blocker to implement and test L0 in the project root. There are design decisions—especially READY/HOLD migration and benchmark correction provenance—that must be made explicitly rather than guessed.

# 9. Recommended Implementation Batches

## Batch A — Pure forecast and question contracts

1. Add L0-1 typed READY/HOLD contract and pure guard without migrating registry data yet.
2. Add L0-2 CI containment and L0-3 signed-adjustment arithmetic validators.
3. Add targeted validator/provider/aggregator tests using in-memory objects and temporary paths.
4. Run shadow validation against stored forecast objects; do not rewrite them.

Acceptance boundary: invalid structured outputs and HOLD questions are rejected deterministically before official writes; existing files remain readable and byte-unchanged.

## Batch B — Official write boundary

1. Add L0-4 allowed-research-state guard after quality refinement.
2. Harden L0-5 with KST deadline semantics and a final pre-append recheck.
3. Verify cost logging for runs blocked after provider calls.
4. Test allowed, degraded, expired, and state-changed-during-run cases with temporary ledgers.

Acceptance boundary: no degraded or expired official row is appended; permitted runs retain current behavior; incurred costs remain auditable.

## Batch C — Append-only benchmark correction workflow

1. Freeze and document a versioned correction schema with explicit unit, evidence, revision, and supersedes.
2. Implement a pure validator and append-only CLI/tool.
3. Extend DB ingestion/read views to select the latest approved correction without mutating source rows.
4. Add byte-identity tests for original ledger rows and rejection tests for missing provenance.

Acceptance boundary: an approved correction is visible in the corrected read model, the original bad row remains byte-identical, and an unevidenced `22→0.22`/`5→0.05` guess is impossible.

## Batch D — Regression and shadow acceptance

1. Run targeted L0 tests, then the full 383-test baseline.
2. Run scenario snapshot reproduction and confirm no probability/path/snapshot change.
3. Compare forecast/read-model outputs before and after on disposable copies.
4. Report failures as code, environment, or missing-data categories.

Post-L0 prompt security, provenance, domain relevance, research/judgment separation, and ensemble independence should be separate batches. They must not be mixed into the L0 diff.

# 10. Exact Test Commands

The following PowerShell commands reproduce the non-mutating intake baseline from the project root. They intentionally disable bytecode and pytest cache creation.

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\workspace\ai-investing\src;C:\workspace\ai-investing\dualdb'

python -m pytest --collect-only -q -p no:cacheprovider
# Expected current baseline: 383 tests collected

python -m pytest -q -p no:cacheprovider `
  src/tests/test_sprint1.py `
  src/tests/test_sprint2.py `
  src/tests/test_llm_provider.py `
  src/tests/test_probability_contract.py `
  src/tests/test_ws2_benchmark.py `
  src/tests/test_quant_integrity_v2.py
# Intake result: 17 passed

python -m pytest -q -p no:cacheprovider
# Intake result: 383 passed in 146.17s

python tools/reproduce_scenario_snapshot.py
# Intake result: weights 83/2/15; quantile cells 1764; mismatches 0; passed true

Push-Location -LiteralPath 'src'
python -m ai_fc --help
Pop-Location
# Expected: CLI help succeeds from src in the current uninstalled environment
```

The extracted-package diagnostic was run separately with the same environment protections:

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing\reports\review_packages\chatgpt_full_handoff_scenario_audit_dea62a1_260806'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = "$PWD\src;$PWD\dualdb"
python -m pytest -q -p no:cacheprovider
# Intake result: 6 failed, 347 passed, 30 skipped
# Failure class: missing package evidence/.git, not a current-root regression
```

For L0 implementation, add the new targeted test files first and run them before the full suite:

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\workspace\ai-investing\src;C:\workspace\ai-investing\dualdb'

python -m pytest -q -p no:cacheprovider `
  src/tests/test_question_gate_v2.py `
  src/tests/test_forecast_contract_v2.py `
  src/tests/test_official_write_gate_v2.py `
  src/tests/test_due_expiry_v2.py `
  src/tests/test_benchmark_corrections_v2.py

python -m pytest -q -p no:cacheprovider
python tools/reproduce_scenario_snapshot.py
```

Any future ledger/DB audit command that can regenerate read models should run only against a disposable copy or in explicit check-only mode after its mutation behavior is verified. This intake did not run a command that could persistently synchronize the official database.
