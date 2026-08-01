from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.db import ingest
from ai_fc.model_registry import Lifecycle, arena_rows, register_defaults, transition


def test_defaults_include_champion_and_non_promoted_shadows(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "db" / "index.db")
    register_defaults(conn, tmp_path)
    rows = {row["model_id"]: row for row in arena_rows(conn)}
    assert rows["bl.gbm_v1"]["lifecycle"] == "champion"
    assert rows["shadow.chronos2"]["lifecycle"] == "shadow"
    assert rows["shadow.chronos2"]["promotion_enabled"] is False


def test_shadow_cannot_promote_without_approval_and_gate(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "db" / "index.db")
    register_defaults(conn, tmp_path)
    with pytest.raises(PermissionError, match="explicit user approval"):
        transition(conn, "shadow.chronos2", Lifecycle.CHAMPION, approved=True)
