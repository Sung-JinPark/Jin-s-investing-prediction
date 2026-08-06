# Reproduction Evidence

## Commands

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\workspace\ai-investing\src;C:\workspace\ai-investing\dualdb'

python -m pytest -q -p no:cacheprovider `
  src/tests/test_provider_shadow.py `
  src/tests/test_l0_batch1.py `
  src/tests/test_llm_provider.py `
  src/tests/test_sprint2.py `
  src/tests/test_sprint1.py `
  src/tests/test_audit_fixes.py::test_krun_median_fixed_rule

python -m pytest -q -p no:cacheprovider
python tools/reproduce_scenario_snapshot.py
git diff --quiet -- calibration forecasts data/scenarios/nasdaq_latest.json
git diff --check
```

## Observed results

```text
Targeted: 58 passed in 10.53s
Full: 404 passed in 83.14s
Scenario: expected 83/2/15, reproduced 83/2/15
Quantile cells: 1764
Quantile mismatches: 0
Durable HEAD diff exit: 0
git diff --check: clean
```

## Dynamic contract probe

```text
valid ACCEPTED 60
ci_excludes REJECTED ProviderOutputError
math_mismatch REJECTED ProviderOutputError
numeric_strings ACCEPTED_AS int float
expired_dry_run REJECTED PreflightError expired-fixture는 기한(2026-08-05) 경과 — resolve 대상
```

The dynamic probe is non-persistent: it uses an in-memory SQLite connection, a synthetic question, and monkeypatched registry/clock functions.
