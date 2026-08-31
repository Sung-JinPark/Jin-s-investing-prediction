# Phase 1 — 탐지 원문 (ruff 0.16.5)

명령: `.venv/Scripts/python.exe -m ruff check . --output-format concise`
(exclude = pyproject [tool.ruff].extend-exclude = RED-LINE 집합)

## 규칙별 집계
```
     23 F401
     22 ARG001
     12 ARG005
      9 ARG002
      8 F841
```

## 파일별 집계
```
      7 src\tests\test_sprint2.py
      5 src\tests\test_provider_shadow.py
      3 tools\ralph_v7.py
      3 tools\audit_v5_gate.py
      3 src\tests\timeseries_v7\test_v7_worker.py
      3 src\tests\test_llm_provider.py
      3 src\tests\test_lite_tier.py
      3 src\ai_fc\statistics_lab.py
      3 dualdb\tests\test_twins.py
      2 tools\verify_v7_protected.py
      2 src\tests\timeseries_v7\test_v7_control_plane.py
      2 src\tests\test_ws1_factory.py
      2 src\tests\test_quant_feed.py
      2 src\tests\test_cross_asset.py
      2 src\tests\test_audit_fixes.py
      2 src\ai_fc\orchestrator.py
      2 src\ai_fc\evaluation.py
      2 scripts\build_data_integrity_review_pack.py
      2 dualdb\dualdb\ingest\seeds.py
      2 dualdb\dualdb\ingest\ritter.py
      1 tools\freeze_v7_contract.py
      1 tools\finalize_v7_wait_data.py
      1 tools\capture_dashboard_screenshots.py
      1 tools\build_v7_replay_pack.py
      1 src\tests\timeseries_v7\test_v7_pit_boundaries.py
      1 src\tests\timeseries_v7\test_v7_collectors.py
      1 src\tests\timeseries_v7\test_gate_feasibility.py
      1 src\tests\test_ws2_benchmark.py
      1 src\tests\test_sprint1.py
      1 src\tests\test_quant.py
```

## 원문
```
dualdb\dualdb\__main__.py:41:24: F401 [*] `json` imported but unused
dualdb\dualdb\ingest\ritter.py:84:38: ARG001 Unused function argument: `since`
dualdb\dualdb\ingest\ritter.py:97:64: ARG001 Unused function argument: `now`
dualdb\dualdb\ingest\seeds.py:26:38: ARG001 Unused function argument: `since`
dualdb\dualdb\ingest\seeds.py:27:5: F841 Local variable `now` is assigned to but never used
dualdb\dualdb\ingest\yahoo.py:62:29: F841 [*] Local variable `exc` is assigned to but never used
dualdb\tests\test_twins.py:49:29: ARG005 Unused lambda argument: `n`
dualdb\tests\test_twins.py:56:26: ARG005 Unused lambda argument: `i`
dualdb\tests\test_twins.py:56:29: ARG005 Unused lambda argument: `n`
scripts\build_data_integrity_review_pack.py:7:8: F401 [*] `io` imported but unused
scripts\build_data_integrity_review_pack.py:459:5: ARG001 Unused function argument: `matrix`
src\ai_fc\cross_asset.py:776:23: ARG001 Unused function argument: `macro_assumptions`
src\ai_fc\dashboard.py:215:5: F841 Local variable `qmap` is assigned to but never used
src\ai_fc\db\ingest.py:764:60: ARG001 Unused function argument: `report`
src\ai_fc\evaluation.py:6:18: F401 [*] `math.log` imported but unused
src\ai_fc\evaluation.py:7:20: F401 [*] `typing.Iterable` imported but unused
src\ai_fc\official_data_workbook.py:11:8: F401 [*] `hashlib` imported but unused
src\ai_fc\orchestrator.py:11:8: F401 [*] `json` imported but unused
src\ai_fc\orchestrator.py:442:26: ARG001 Unused function argument: `q`
src\ai_fc\quant\feed.py:256:5: F841 Local variable `header` is assigned to but never used
src\ai_fc\quant\runner.py:9:28: F401 [*] `datetime.datetime` imported but unused
src\ai_fc\registry.py:268:5: F841 Local variable `segments` is assigned to but never used
src\ai_fc\statistics_lab.py:1176:5: F841 Local variable `by_key` is assigned to but never used
src\ai_fc\statistics_lab.py:2701:5: F841 Local variable `observation_through` is assigned to but never used
src\ai_fc\statistics_lab.py:2765:5: F841 Local variable `generated_time` is assigned to but never used
src\tests\test_audit_fixes.py:257:25: ARG001 Unused function argument: `a`
src\tests\test_audit_fixes.py:257:30: ARG001 Unused function argument: `kw`
src\tests\test_cross_asset.py:409:29: ARG001 Unused function argument: `start`
src\tests\test_cross_asset.py:409:36: ARG001 Unused function argument: `end`
src\tests\test_lite_tier.py:85:28: ARG001 Unused function argument: `client`
src\tests\test_lite_tier.py:85:44: ARG001 Unused function argument: `user`
src\tests\test_lite_tier.py:85:50: ARG001 Unused function argument: `budget`
src\tests\test_llm_provider.py:21:22: ARG001 Unused function argument: `system`
src\tests\test_llm_provider.py:21:30: ARG001 Unused function argument: `user`
src\tests\test_llm_provider.py:21:36: ARG001 Unused function argument: `budget`
src\tests\test_provider_shadow.py:22:24: ARG002 Unused method argument: `system`
src\tests\test_provider_shadow.py:22:32: ARG002 Unused method argument: `user`
src\tests\test_provider_shadow.py:22:62: ARG002 Unused method argument: `max_search_uses`
src\tests\test_provider_shadow.py:27:25: ARG002 Unused method argument: `system`
src\tests\test_provider_shadow.py:27:33: ARG002 Unused method argument: `user`
src\tests\test_quant.py:11:52: F401 [*] `ai_fc.quant.seasonality.summarize` imported but unused
src\tests\test_quant_feed.py:77:57: ARG005 Unused lambda argument: `args`
src\tests\test_quant_feed.py:77:65: ARG005 Unused lambda argument: `kwargs`
src\tests\test_sprint1.py:8:8: F401 [*] `shutil` imported but unused
src\tests\test_sprint2.py:82:55: ARG005 Unused lambda argument: `a`
src\tests\test_sprint2.py:82:60: ARG005 Unused lambda argument: `k`
src\tests\test_sprint2.py:86:63: ARG005 Unused lambda argument: `kw`
src\tests\test_sprint2.py:92:60: ARG005 Unused lambda argument: `self`
src\tests\test_sprint2.py:92:67: ARG005 Unused lambda argument: `a`
src\tests\test_sprint2.py:92:72: ARG005 Unused lambda argument: `k`
src\tests\test_sprint2.py:137:42: ARG001 Unused function argument: `monkeypatch`
src\tests\test_ws1_factory.py:126:28: ARG001 Unused function argument: `start`
src\tests\test_ws1_factory.py:126:41: ARG001 Unused function argument: `end`
src\tests\test_ws2_benchmark.py:6:22: F401 [*] `datetime.date` imported but unused
src\tests\timeseries_v7\test_gate_feasibility.py:2:8: F401 [*] `pytest` imported but unused
src\tests\timeseries_v7\test_v7_collectors.py:133:81: ARG005 Unused lambda argument: `at`
src\tests\timeseries_v7\test_v7_control_plane.py:3:22: F401 [*] `datetime.datetime` imported but unused
src\tests\timeseries_v7\test_v7_control_plane.py:3:32: F401 [*] `datetime.timezone` imported but unused
src\tests\timeseries_v7\test_v7_pit_boundaries.py:5:8: F401 [*] `pytest` imported but unused
src\tests\timeseries_v7\test_v7_worker.py:20:21: ARG002 Unused method argument: `lease`
src\tests\timeseries_v7\test_v7_worker.py:23:25: ARG002 Unused method argument: `lease`
src\tests\timeseries_v7\test_v7_worker.py:26:38: ARG002 Unused method argument: `lease`
tools\audit_v5_gate.py:26:55: F401 [*] `datetime.timezone` imported but unused
tools\audit_v5_gate.py:918:28: ARG001 Unused function argument: `output`
tools\audit_v5_gate.py:918:42: ARG001 Unused function argument: `repo_root`
tools\build_v7_replay_pack.py:9:8: F401 [*] `sys` imported but unused
tools\capture_dashboard_screenshots.py:25:42: ARG002 Unused method argument: `args`
tools\finalize_v7_wait_data.py:8:8: F401 [*] `hashlib` imported but unused
tools\freeze_v7_contract.py:7:8: F401 [*] `hashlib` imported but unused
tools\ralph_v7.py:17:5: F401 [*] `ai_fc.timeseries_v7.scheduler.GenerationEvidence` imported but unused
tools\ralph_v7.py:17:25: F401 [*] `ai_fc.timeseries_v7.scheduler.decide_generation` imported but unused
tools\ralph_v7.py:17:44: F401 [*] `ai_fc.timeseries_v7.scheduler.generation_input_hash` imported but unused
tools\verify_v7_protected.py:7:8: F401 [*] `hashlib` imported but unused
tools\verify_v7_protected.py:27:5: F401 [*] `ai_fc.timeseries_v7.protection.load_baseline` imported but unused
Found 74 errors.
[*] 24 fixable with the `--fix` option (7 hidden fixes can be enabled with the `--unsafe-fixes` option).
```
