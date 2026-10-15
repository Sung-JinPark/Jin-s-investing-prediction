"""USD presentation preserves native earnings, source receipts and point-in-time cutoffs."""

import copy
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_fc import event_consensus as ec

ROOT = Path(__file__).resolve().parents[2]
FX = Path("data/calendar/display_fx/eur_usd_2026-10-14.json")


@pytest.fixture
def display_root(tmp_path):
    ledger = tmp_path / ec.LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / ec.LEDGER_RELATIVE, ledger)
    shutil.copytree(ROOT / FX.parent, tmp_path / FX.parent)
    return tmp_path


def _cutoff(root):
    fx = json.loads((root / FX).read_text(encoding="utf-8"))
    return datetime.fromisoformat(fx["captured_at"])


def test_usd_projection_joins_same_quarter_without_changing_ledger_or_scoring(display_root):
    ledger = display_root / ec.LEDGER_RELATIVE
    original = ledger.read_bytes()
    rows = ec.load_event_consensus(display_root, _cutoff(display_root))["asml_2026_q3"]
    by_metric = {row["metric"]: row for row in rows}
    eps, revenue = by_metric["eps_reported"], by_metric["revenue_reported"]
    assert eps["actual"] == "EUR 12.95" and eps["comparison_allowed"] is False
    assert eps["display_conversion"]["actual"] == "$14.50"
    assert eps["display_conversion"]["actual_value"] == pytest.approx(14.497525)
    assert eps["display_conversion"]["consensus_row_id"] == by_metric["eps"]["row_id"]
    assert revenue["display_conversion"]["actual"] == "$13,056M"
    assert revenue["actual"] == "EUR 11,662M"
    assert "display_conversion" not in by_metric["gross_margin_reported"]
    assert by_metric["eps"]["actual"] is None
    assert ledger.read_bytes() == original


def test_capture_cutoff_does_not_backdate_the_release_date_rate(display_root):
    before = _cutoff(display_root) - timedelta(microseconds=1)
    rows = ec.load_event_consensus(display_root, before)["asml_2026_q3"]
    assert all("display_conversion" not in row for row in rows)


@pytest.mark.parametrize("patch", [
    {"unit": "EUR_per_USD"}, {"base_currency": "USD"},
    {"rate": "NaN"}, {"rate": "0"}, {"rate": "-1"},
    {"rate": "1.2"}, {"source_hash": "0" * 64},
    {"available_at": "2026-10-14T05:00:00Z"},
])
def test_invalid_fx_is_rejected_with_an_auditable_reason(display_root, patch):
    path = display_root / FX
    fx = json.loads(path.read_text(encoding="utf-8"))
    fx.update(patch)
    path.write_text(json.dumps(fx), encoding="utf-8")
    with pytest.raises(ec.ConsensusError, match="display FX"):
        ec.load_event_consensus(display_root, _cutoff(display_root))


def test_no_quarter_currency_or_provider_actual_is_overwritten(display_root):
    rows = ec.load_event_consensus(display_root, _cutoff(display_root))["asml_2026_q3"]
    for changes in ({"period_end": "2026-12-31"}, {"currency": None}, {"actual": "$14.51"}):
        events = {"asml_2026_q3": copy.deepcopy(rows)}
        for row in events["asml_2026_q3"]:
            row.pop("display_conversion", None)
            if row["metric"] == "eps":
                row.update(changes)
        ec._attach_display_fx(display_root, events, _cutoff(display_root))
        eps = next(row for row in events["asml_2026_q3"] if row["metric"] == "eps_reported")
        assert "consensus_row_id" not in eps["display_conversion"]
