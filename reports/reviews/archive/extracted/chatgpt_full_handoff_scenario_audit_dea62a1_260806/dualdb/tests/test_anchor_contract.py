from __future__ import annotations

from dualdb import db
from dualdb.ingest import seeds


def test_overlay_and_model_anchor_are_separate_and_consumed(tmp_path) -> None:
    conn = db.connect(tmp_path / "anchor.sqlite")
    try:
        seeds.ingest(conn)
        dotcom = conn.execute(
            "SELECT anchor_month, overlay_start, model_anchor FROM era "
            "WHERE era_id='dotcom'"
        ).fetchone()
        assert dict(dotcom) == {
            "anchor_month": "1996-01",
            "overlay_start": "1995-01",
            "model_anchor": "1996-01",
        }
        alignment = conn.execute(
            "SELECT date FROM alignment WHERE method='calendar_m' "
            "AND era_id='dotcom' AND cycle_index=0"
        ).fetchone()
        assert alignment["date"] == dotcom["model_anchor"]
    finally:
        conn.close()
