from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_replay_lock_is_exact_and_has_required_runtime_coordinates() -> None:
    lock = ROOT / "locks/timeseries_v6/requirements.replay.lock"
    rows = [
        row.strip()
        for row in lock.read_text(encoding="utf-8").splitlines()
        if row.strip() and not row.lstrip().startswith("#")
    ]
    assert rows == sorted(rows, key=str.casefold)
    assert all(re.fullmatch(r"[A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_,.\-]+\])?==[^\s]+", row) for row in rows)
    coordinates = {
        row.split("==", 1)[0].lower().replace("_", "-"): row.split("==", 1)[1]
        for row in rows
    }
    assert coordinates["numpy"] == "2.3.5"
    assert coordinates["pandas"] == "2.3.3"
    assert coordinates["scipy"] == "1.16.3"
    assert coordinates["scikit-learn"] == "1.7.2"
    assert coordinates["exchange-calendars"] == "4.13.2"
    assert coordinates["statsmodels"] == "0.14.6"
    assert "python-frontmatter" in coordinates
    assert "duckdb" in coordinates


def test_runtime_receipt_binds_image_lock_and_python() -> None:
    receipt = json.loads(
        (ROOT / "data/timeseries_v6/manifests/runtime_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["python"] == "3.12.11"
    assert receipt["platform"] == "linux/amd64"
    assert receipt["base_image_digest"].startswith("sha256:")
    assert len(receipt["requirements_lock_sha256"]) == 64
    assert receipt["container_smoke_test"]["returncode"] == 0
    assert receipt["v5_audit_replay"]["returncode"] == 0
