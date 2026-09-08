"""V13-VOL 라이브 파이프라인 — hold(미무장)·live·멱등 append·재동결 새 행·verify 교차검사·신선도 helper."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import features as F
from ai_fc.timeseries_v13 import freshness as FR
from ai_fc.timeseries_v13 import pipeline as P

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_RELATIVE = Path("data/contracts/nyse_holidays.yaml")


class _Obs:
    def __init__(self, series_id: str, day: str, value: float):
        self._row = {"series_id": series_id, "observation_time": day, "value": value}

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002 — pydantic 시그니처 흉내
        return dict(self._row)


def _synthetic_observations(last_day: date, n: int = 420) -> list[_Obs]:
    calendar = yaml.safe_load((ROOT / CALENDAR_RELATIVE).read_text(encoding="utf-8"))
    from ai_fc.scenario import future_trading_days
    # future_trading_days 는 asof 이후 count 개 거래일을 돌려준다 — last_day 를 확실히 지나도록 넉넉히 뽑아 절단한다
    days = [d for d in future_trading_days(last_day - timedelta(days=int(n * 1.6)), n + 200, calendar) if d <= last_day][-n:]
    assert days[-1] == last_day, days[-1]
    rng = np.random.default_rng(11)
    vix = 15 + np.abs(np.cumsum(rng.normal(scale=0.4, size=len(days))))
    ndx = 10000 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(days))))
    out = []
    for d, v, q in zip(days, vix, ndx):
        out.append(_Obs("VIX", d.isoformat(), float(v))); out.append(_Obs("NASDAQCOM", d.isoformat(), float(q)))
    return out


def _frozen_artifact(finalist: str = "V13VOL_champion_test0000") -> dict:
    cells = {}
    for spec in C.cell_specs():
        target = spec["target"]
        cells[spec["name"]] = {
            "model": "persistence_pb", "target": target, "h": spec["h"],
            **({"K": spec["K"]} if target == "vix_touch" else {"theta": spec["theta"]}),
            "feature_names": F.feature_names("persistence_pb", target),
            "beta": [-0.5, 0.8], "mu": [18.0 if target == "vix_touch" else 0.17],
            "sd": [7.0 if target == "vix_touch" else 0.08], "cov_beta": [[0.01, 0.001], [0.001, 0.02]],
            "n_fit": 2000, "clim_base_rate": 0.4, "baseline_pb": None, "iso_map": None, "derived_layer": "raw",
            "gate_evidence": {"design_pass": True},
        }
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "finalist_id": finalist,
            "alpha_ewma": C.EWMA_ALPHA, "rv_nan_fill_median": 0.1694207105468098, "cells": cells,
            "reconciliation": {"pass": True}}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _repo(tmp_path: Path, *, armed: bool = True, finalist: str = "V13VOL_champion_test0000") -> Path:
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / CALENDAR_RELATIVE, root / CALENDAR_RELATIVE)
    artifact = _frozen_artifact(finalist)
    path = root / C.COEFFICIENTS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["gates"]["armed"] = armed
    contract["frozen_coefficients"] = {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": C.sha256_file(path),
                                       "content_hash": artifact["content_hash"], "finalist_id": finalist,
                                       "refit_prohibited": True}
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return root


LAST = date(2026, 9, 4)                                    # 금요일 종가
NOW = datetime(2026, 9, 8, 5, 0, tzinfo=timezone.utc)      # 노동절 다음 화요일 05:00Z


@pytest.fixture(autouse=True)
def _archive(monkeypatch):
    obs = _synthetic_observations(LAST)
    monkeypatch.setattr(P, "read_market_observations", lambda *_args, **_kwargs: obs)


def test_publish_writes_hold_pointer_without_numbers_when_not_armed(tmp_path) -> None:
    root = _repo(tmp_path, armed=False)
    result = P.publish_latest_timeseries_v13_vol(root, now=NOW)
    assert result["status"] == "hold" and result["customer_numbers_visible"] is False
    assert any("gates_not_armed" in r for r in result["reasons"])
    pointer = json.loads((root / C.LATEST_RELATIVE).read_text(encoding="utf-8"))
    assert pointer["status"] == "hold" and "cells" not in pointer and "inputs" not in pointer
    assert not (root / C.LIVE_LEDGER_RELATIVE).exists(), "hold 는 원장에 쓰지 않는다"


def test_publish_live_pointer_has_nine_cells_ledger_row_and_is_idempotent(tmp_path) -> None:
    root = _repo(tmp_path)
    first = P.publish_latest_timeseries_v13_vol(root, now=NOW)
    assert first["status"] == "live" and first["ledger_appended"] is True and first["as_of"] == LAST.isoformat()
    pointer = json.loads((root / C.LATEST_RELATIVE).read_text(encoding="utf-8"))
    assert set(pointer["cells"]) == set(C.CELL_ORDER)
    for cell in pointer["cells"].values():
        lo, hi = cell["band80"]
        assert 0 <= lo <= cell["p"] <= hi <= 1 and cell["model"] == "persistence_pb"
    assert pointer["freshness"]["status"] == "fresh" and pointer["freshness"]["missing_sessions"] == 0
    # 같은 as_of·같은 계수 재실행 → 원장 행 추가 없음(멱등), 포인터는 재작성되어도 verify 가 통과한다
    again = P.publish_latest_timeseries_v13_vol(root, now=NOW + timedelta(hours=1))
    assert again["status"] == "live" and again["ledger_appended"] is False
    rows = [json.loads(l) for l in (root / C.LIVE_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if l]
    assert len(rows) == 1 and rows[0]["run_id"].startswith(f"v13vol-{LAST.isoformat()}-")
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]


def test_refreeze_appends_a_new_ledger_row_instead_of_colliding(tmp_path) -> None:
    root = _repo(tmp_path)
    P.publish_latest_timeseries_v13_vol(root, now=NOW)
    # 계수 재동결(다른 finalist/sha) → 같은 as_of 라도 새 행
    artifact = _frozen_artifact("V13VOL_champion_test1111")
    artifact["cells"]["vix25_h5"]["beta"] = [-0.4, 0.9]
    artifact.pop("content_hash"); artifact["content_hash"] = C.canonical_hash(artifact)
    path = root / C.COEFFICIENTS_RELATIVE
    path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    contract = yaml.safe_load((root / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["frozen_coefficients"].update({"sha256": C.sha256_file(path), "content_hash": artifact["content_hash"],
                                            "finalist_id": "V13VOL_champion_test1111"})
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = P.publish_latest_timeseries_v13_vol(root, now=NOW)
    assert result["status"] == "live" and result["ledger_appended"] is True
    rows = [json.loads(l) for l in (root / C.LIVE_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if l]
    assert len(rows) == 2 and len({r["run_id"] for r in rows}) == 2
    assert P.verify_timeseries_v13_vol(root)["ok"] is True


def test_verify_detects_ledger_pointer_divergence_and_pin_break(tmp_path) -> None:
    root = _repo(tmp_path)
    P.publish_latest_timeseries_v13_vol(root, now=NOW)
    ledger = root / C.LIVE_LEDGER_RELATIVE
    rows = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l]
    rows[0]["cells"]["vix25_h5"]["p"] = 0.999            # 원장 셀 변조 (content_hash 도 깨진다)
    ledger.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is False
    assert any("ledger/pointer cell mismatch" in e for e in verify["errors"])
    assert any("hash mismatch" in e for e in verify["errors"])
    # 계수 파일 변조 → 핀 불일치
    (root / C.COEFFICIENTS_RELATIVE).write_bytes(b"{}")
    assert any("coefficients" in e for e in P.verify_timeseries_v13_vol(root)["errors"])


def test_stale_archive_holds_the_pointer(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    stale = _synthetic_observations(date(2026, 9, 1))
    monkeypatch.setattr(P, "read_market_observations", lambda *_args, **_kwargs: stale)
    result = P.publish_latest_timeseries_v13_vol(root, now=NOW)      # 화요일 자료로 다음 주 화요일 발행 → 누락 3
    assert result["status"] == "hold" and any("stale" in r for r in result["reasons"])


def test_freshness_helper_covers_weekend_holiday_and_pre_close_cases() -> None:
    # 보통 월요일 05:00Z: 마지막 완료 세션 = 직전 금요일
    monday = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    assert FR.last_completed_session(ROOT, monday) == date(2026, 9, 11)
    assert FR.missing_sessions(ROOT, date(2026, 9, 11), monday)[0] == 0
    assert FR.missing_sessions(ROOT, date(2026, 9, 10), monday)[0] == 1
    assert FR.missing_sessions(ROOT, date(2026, 9, 9), monday)[0] == 2
    # 노동절(9-07 월) 다음 화요일 05:00Z: 마지막 완료 세션 = 9-04 금 (연휴는 세션이 아니다)
    assert FR.last_completed_session(ROOT, NOW) == date(2026, 9, 4)
    assert FR.missing_sessions(ROOT, date(2026, 9, 3), NOW)[0] == 1
    # 토요일 01:30Z (금요일 자료가 아직 아카이브에 없을 때): 마지막 완료 세션 = 금요일, 목요일 자료 → 누락 1 → 허용
    saturday = datetime(2026, 9, 12, 1, 30, tzinfo=timezone.utc)
    assert FR.last_completed_session(ROOT, saturday) == date(2026, 9, 11)
    assert FR.freshness_report(ROOT, "2026-09-10", saturday)["status"] == "fresh"
    assert FR.freshness_report(ROOT, "2026-09-09", saturday)["status"] == "stale"
    # 평일 장중(16:15 ET 이전): 당일은 아직 완료 세션이 아니다
    midday = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)
    assert FR.last_completed_session(ROOT, midday) == date(2026, 9, 9)
    assert FR.freshness_report(ROOT, None, midday)["status"] == "no_observation"
