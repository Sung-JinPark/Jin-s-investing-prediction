from __future__ import annotations

import textwrap
from pathlib import Path

from ai_fc import inventory
from ai_fc.db import ingest


def test_inventory_is_generated_and_detects_source_drift(tmp_path: Path) -> None:
    (tmp_path / "questions").mkdir()
    registry = tmp_path / "questions" / "registry.yaml"
    registry.write_text(textwrap.dedent("""\
        version: 1
        questions: []
    """), encoding="utf-8")
    (tmp_path / "forecasts").mkdir()
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n",
        encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    ingest.sync(conn, tmp_path)
    target = inventory.write_inventory(tmp_path, conn)
    assert target.exists()
    assert inventory.inventory_is_current(tmp_path, conn)
    registry.write_text("version: 1\nquestions: []\nupdated: changed\n", encoding="utf-8")
    assert not inventory.inventory_is_current(tmp_path, conn)
