# Test execution note

- Collection: 473 tests.
- Monolithic command: `pytest -q --junitxml=.../full_pytest.xml` was interrupted after 355.73 seconds by an output-pipe `OSError: [Errno 22] Invalid argument`; its partial XML is retained and is not reported as a pass.
- Complete partition 1: `pytest -q src/tests` — 419 passed in 214.57 seconds.
- Complete partition 2: `pytest -q dualdb/tests` — 54 passed in 66.36 seconds.
- Combined complete collection: 473 passed, 0 failed, 0 errors, 0 skipped.
- Targeted Scenario V5.2 suite: 36 passed in 19.88 seconds.

The package summary uses the two complete non-overlapping partitions and keeps the failed monolithic attempt as separate raw evidence.
