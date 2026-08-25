import sys
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.atlas import AtlasError, AtlasStore, AtlasTask, AtlasWorker


def test_durable_dependency_loop_checkpoint_and_resume(tmp_path: Path) -> None:
    store = AtlasStore(tmp_path / "atlas.sqlite")
    tasks = [
        AtlasTask("a", "test", "materializer", (), (sys.executable, "-c", "print('a')")),
        AtlasTask("b", "test", "trainer_cpu", ("a",), (sys.executable, "-c", "print('b')")),
    ]
    first_hash = store.register_plan(tasks)
    assert store.register_plan(tasks) == first_hash
    worker = AtlasWorker(store, worker_id="w", capabilities={"materializer", "trainer_cpu"}, root=tmp_path)
    result = worker.run_until_terminal()
    assert [row["state"] for row in result] == ["succeeded", "succeeded"]
    assert all(row["checkpoint_sha256"] for row in result)
    assert AtlasStore(tmp_path / "atlas.sqlite").status()[1]["state"] == "succeeded"


def test_three_identical_blockers_end_in_hold_without_infinite_loop(tmp_path: Path) -> None:
    store = AtlasStore(tmp_path / "atlas.sqlite")
    store.register_plan([AtlasTask("bad", "test", "evaluator", (), (sys.executable, "-c", "import sys;sys.stderr.write('same');sys.exit(1)"), max_attempts=5)])
    worker = AtlasWorker(store, worker_id="w", capabilities={"evaluator"}, root=tmp_path)
    assert worker.run_until_terminal(max_iterations=10)[0]["state"] == "hold"
    assert store.status()[0]["attempt_count"] == 3


def test_commands_and_capabilities_are_fail_closed() -> None:
    with pytest.raises(AtlasError, match="executable"):
        AtlasTask("x", "test", "reviewer", (), ("powershell", "bad")).validate()
    with pytest.raises(AtlasError, match="publication"):
        AtlasTask("x", "test", "reviewer", (), (sys.executable, "-c", "git push")).validate()
