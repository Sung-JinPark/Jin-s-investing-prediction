from __future__ import annotations

from pathlib import Path

from ai_fc.db import ingest, queries


def test_repeated_fomc_rounds_form_one_unique_event(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "db" / "index.db")
    for round_no, probability in enumerate((15, 3, 12, 6), start=1):
        fid = f"2026-07-{9 + round_no:02d}_fomc_r{round_no}"
        conn.execute(
            """INSERT INTO forecasts
               (forecast_id,question_id,round,forecast_ts,probability,path,file_sha256)
               VALUES (?,?,?,?,?,?,?)""",
            (fid, "fomc", round_no, f"2026-07-{9 + round_no:02d}T09:00:00",
             probability, f"{fid}.md", f"h{round_no}"))
        conn.execute(
            """INSERT INTO resolutions
               (forecast_id,resolved_date,question_id,forecast_date,probability,
                outcome,brier,domain,ledger_line)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (fid, "2026-07-31", "fomc", f"2026-07-{9 + round_no:02d}",
             probability, 0, (probability / 100) ** 2, "macro", round_no))
    ingest._rebuild_resolution_events(conn, ingest.DriftReport())
    assert conn.execute("SELECT COUNT(*) FROM resolution_event").fetchone()[0] == 1
    event = conn.execute("SELECT * FROM resolution_event").fetchone()
    assert event["forecast_count"] == 4
    assert event["representative_probability"] != event["first_probability"]
    assert queries.gate_status_v2(conn)["n_events"] == 1
    assert queries.gate_status_v2(conn)["display_only"] is True


def test_invalid_benchmark_probability_is_excluded_not_silently_scaled(tmp_path: Path) -> None:
    conn = ingest.connect(tmp_path / "db" / "index.db")
    conn.execute(
        """INSERT INTO benchmark_scores
           (forecast_id,resolved_date,llm_prob,llm_brier,market_prob,market_brier)
           VALUES ('bad','2026-07-31',0.2,0.04,22.0,484.0)""")
    conn.execute(
        """INSERT INTO benchmark_scores
           (forecast_id,resolved_date,llm_prob,llm_brier,market_prob,market_brier)
           VALUES ('good','2026-07-31',0.3,0.09,0.4,0.16)""")
    row = conn.execute(
        "SELECT * FROM v_benchmark_pairwise WHERE pair='llm_vs_market'"
    ).fetchone()
    assert row["n"] == 1
    assert row["other_brier"] == 0.16


def test_strict_sync_rolls_back_on_forecast_tamper(tmp_path: Path) -> None:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(
        "version: 1\nquestions: []\n", encoding="utf-8")
    forecasts = tmp_path / "forecasts" / "2099"
    forecasts.mkdir(parents=True)
    path = forecasts / "2099-01-01_fixture_r1.md"
    path.write_text(
        "---\nforecast_id: 2099-01-01_fixture_r1\nquestion_id: fixture\n"
        "timestamp: 2099-01-01 09:00 KST\nprobability: 40\n---\nbody\n",
        encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(
        "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n",
        encoding="utf-8")
    conn = ingest.connect(tmp_path / "db" / "index.db")
    ingest.sync(conn, tmp_path)
    before = conn.execute("SELECT probability FROM forecasts").fetchone()[0]
    path.write_text(path.read_text(encoding="utf-8").replace("probability: 40", "probability: 90"),
                    encoding="utf-8")
    report = ingest.sync(conn, tmp_path, strict=True)
    assert not report.ok
    assert conn.execute("SELECT probability FROM forecasts").fetchone()[0] == before
