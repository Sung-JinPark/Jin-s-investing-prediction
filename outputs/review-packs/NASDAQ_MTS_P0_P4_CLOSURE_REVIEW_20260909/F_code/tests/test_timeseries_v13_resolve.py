"""V13-VOL 라이브 전진 채점 — 성숙 판정·멱등·기후 고정·검증.

이 원장이 C1(배포 이후 실제로 확정된 표본)의 유일한 경로다. 설계창 성적과 섞이면 안 되므로
라벨은 아카이브 거래일 인덱스로만 성숙시키고, 기후는 계약 고정값을 쓴다.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import resolve as R

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_RELATIVE = Path("data/contracts/nyse_holidays.yaml")
NOW = datetime(2026, 9, 8, 5, 0, tzinfo=timezone.utc)


class _Obs:
    def __init__(self, series_id: str, day: str, value: float):
        self._row = {"series_id": series_id, "observation_time": day, "value": value}

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002
        return dict(self._row)


def _sessions(last: date, n: int) -> list[date]:
    from ai_fc.scenario import future_trading_days
    calendar = yaml.safe_load((ROOT / CALENDAR_RELATIVE).read_text(encoding="utf-8"))
    days = [d for d in future_trading_days(last - timedelta(days=int(n * 1.7)), n + 200, calendar) if d <= last]
    return days[-n:]


def _observations(last: date, n: int, *, spike_from: int | None = None) -> list[_Obs]:
    days = _sessions(last, n)
    rng = np.random.default_rng(4)
    vix = np.full(len(days), 14.0) + rng.normal(scale=0.2, size=len(days))
    if spike_from is not None:
        vix[spike_from:] = 32.0            # 원점 이후 VIX 30 터치를 확실히 만든다
    ndx = 10000 * np.exp(np.cumsum(rng.normal(scale=0.008, size=len(days))))
    out: list[_Obs] = []
    for d, v, q in zip(days, vix, ndx):
        out.append(_Obs("VIX", d.isoformat(), float(v)))
        out.append(_Obs("NASDAQCOM", d.isoformat(), float(q)))
    return out


def _repo(tmp_path: Path, live_rows: list[dict]) -> Path:
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / CALENDAR_RELATIVE, root / CALENDAR_RELATIVE)
    shutil.copy(ROOT / C.CONTRACT_RELATIVE, root / C.CONTRACT_RELATIVE)
    ledger = root / C.LIVE_LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in live_rows), encoding="utf-8")
    return root


def _live_row(origin: str, *, run_id: str, p: float = 0.5) -> dict:
    return {"schema_version": 1, "run_id": run_id, "as_of": origin,
            "knowledge_cutoff": "2026-09-08T00:00:00+00:00", "model_id": C.MODEL_ID,
            "finalist_id": "V13VOL_champion_test0000", "coefficients_sha256": "a" * 64,
            "holdout_status": "not_consumed",
            "cells": {name: {"p": p, "band80": [max(0.0, p - 0.1), min(1.0, p + 0.1)],
                             "model": "persistence_pb"} for name in C.CELL_ORDER}}


def test_climatology_map_uses_the_contract_fixed_values() -> None:
    contract = C.load_contract_v13(ROOT)
    clim = R.climatology_map(contract)
    assert set(clim) == set(C.CELL_ORDER)
    base = contract["climatology_base_rates"]
    assert clim["vix25_h5"] == base["vix_touch"]["K25_h5"]
    assert clim["vix30_h63"] == base["vix_touch"]["K30_h63"]
    assert clim["rv_h21"] == base["rv_exceedance"]["h21"]


def test_unmatured_origins_are_pending_not_scored(tmp_path, monkeypatch) -> None:
    last = date(2026, 9, 4)
    monkeypatch.setattr(R, "read_market_observations", lambda *_a, **_k: _observations(last, 400))
    root = _repo(tmp_path, [_live_row(last.isoformat(), run_id="v13vol-a")])
    out = R.resolve_live_timeseries_v13_vol(root, now=NOW)
    assert out["resolved"] == 0 and out["pending"] == 9
    assert not (root / R.RESOLUTION_LEDGER_RELATIVE).exists(), "성숙 전에는 원장을 만들지 않는다"


def test_matured_origins_are_scored_once_and_labels_are_realised(tmp_path, monkeypatch) -> None:
    last = date(2026, 9, 4)
    days = _sessions(last, 400)
    origin = days[-90]                                  # h5·h21·h63 전부 성숙
    spike = len(days) - 89                              # 원점 다음 세션부터 VIX 32
    monkeypatch.setattr(R, "read_market_observations",
                        lambda *_a, **_k: _observations(last, 400, spike_from=spike))
    root = _repo(tmp_path, [_live_row(origin.isoformat(), run_id="v13vol-a", p=0.6)])
    out = R.resolve_live_timeseries_v13_vol(root, now=NOW)
    assert out["resolved"] == 9 and out["pending"] == 0
    rows = [json.loads(line) for line in (root / R.RESOLUTION_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 9
    by_cell = {r["cell"]: r for r in rows}
    # VIX 가 원점 직후 32로 뛰므로 vix25·vix30 계열은 전부 터치(label 1)
    for name in ("vix25_h5", "vix30_h5", "vix25_h63", "vix30_h63"):
        assert by_cell[name]["label"] == 1.0, name
        assert by_cell[name]["brier_model"] == pytest.approx((0.6 - 1.0) ** 2)
    for row in rows:
        assert row["resolved_session"] > row["origin"]
        assert row["climatology_base_rate"] > 0
        body = {k: v for k, v in row.items() if k != "content_hash"}
        assert C.canonical_hash(body) == row["content_hash"]
    # 멱등: 다시 돌려도 추가되지 않는다
    again = R.resolve_live_timeseries_v13_vol(root, now=NOW)
    assert again["resolved"] == 0 and again["total_resolutions"] == 9
    assert R.matured_counts(root)["vix25_h5"] == 1
    assert R.verify_live_resolutions(root)["ok"] is True


def test_horizon_maturity_is_measured_in_archive_sessions(tmp_path, monkeypatch) -> None:
    last = date(2026, 9, 4)
    days = _sessions(last, 400)
    origin = days[-10]                                  # h5 만 성숙, h21·h63 미성숙
    monkeypatch.setattr(R, "read_market_observations", lambda *_a, **_k: _observations(last, 400))
    root = _repo(tmp_path, [_live_row(origin.isoformat(), run_id="v13vol-a")])
    out = R.resolve_live_timeseries_v13_vol(root, now=NOW)
    assert out["resolved"] == 3 and out["pending"] == 6
    cells = {json.loads(line)["cell"] for line in
             (root / R.RESOLUTION_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines()}
    assert cells == {"vix25_h5", "vix30_h5", "rv_h5"}


def test_verify_detects_tampered_resolution_rows(tmp_path, monkeypatch) -> None:
    last = date(2026, 9, 4)
    days = _sessions(last, 400)
    monkeypatch.setattr(R, "read_market_observations", lambda *_a, **_k: _observations(last, 400))
    root = _repo(tmp_path, [_live_row(days[-90].isoformat(), run_id="v13vol-a")])
    R.resolve_live_timeseries_v13_vol(root, now=NOW)
    path = root / R.RESOLUTION_LEDGER_RELATIVE
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["label"] = 0.5
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    out = R.verify_live_resolutions(root)
    assert out["ok"] is False
    assert any("hash mismatch" in e for e in out["errors"])
    assert any("label must be 0 or 1" in e for e in out["errors"])


def test_resolution_ledger_is_registered_and_verb_exists() -> None:
    registry = yaml.safe_load((ROOT / "data/contracts/ledger_registry.yaml").read_text(encoding="utf-8"))["ledgers"]
    entry = next((row for row in registry if row["id"] == "timeseries_v13_vol_live_resolutions"), None)
    assert entry and entry["path"] == R.RESOLUTION_LEDGER_RELATIVE.as_posix()
    cli = (ROOT / "src/ai_fc/cli.py").read_text(encoding="utf-8")
    assert "timeseries-v13-vol-resolve" in cli
    gate = C.load_contract_v13(ROOT)["live_forward_gate"]
    assert gate["execution_path"] == "named_verb_guarded"
    assert gate["outcomes_written_to"].startswith(R.RESOLUTION_LEDGER_RELATIVE.as_posix())
