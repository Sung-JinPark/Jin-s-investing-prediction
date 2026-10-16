"""V13-VOL 홀드아웃 가드 — 승인 없이는 데이터를 읽기 전에 거부하고, 1회만 소모된다.

이 테스트는 실제 홀드아웃 창을 읽지 않는다(tmp repo + 합성 관측). 실제 소모는 2026-09-09에 1회 있었고
그 사실은 `data/timeseries_v13/ledgers/holdout_scorings.jsonl` 이 증명한다 — 마지막 테스트가 그 규율을 검사한다.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import features as F
from ai_fc.timeseries_v13 import holdout as H

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_RELATIVE = Path("data/contracts/nyse_holidays.yaml")
NOW = "2026-09-08T05:00:00+00:00"
FINALIST = "V13VOL_champion_test0000"


class _Obs:
    def __init__(self, series_id: str, day: str, value: float):
        self._row = {"series_id": series_id, "observation_time": day, "value": value}

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002
        return dict(self._row)


def _observations(first: date, last: date) -> list[_Obs]:
    from ai_fc.scenario import future_trading_days
    calendar = yaml.safe_load((ROOT / CALENDAR_RELATIVE).read_text(encoding="utf-8"))
    span = (last - first).days + 10
    days = [d for d in future_trading_days(first - timedelta(days=1), span, calendar) if d <= last]
    rng = np.random.default_rng(9)
    vix = 16 + np.abs(np.cumsum(rng.normal(scale=0.35, size=len(days))))
    ndx = 10000 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(days))))
    out: list[_Obs] = []
    for d, v, q in zip(days, vix, ndx):
        out.append(_Obs("VIX", d.isoformat(), float(v)))
        out.append(_Obs("NASDAQCOM", d.isoformat(), float(q)))
    return out


def _frozen(finalist: str = FINALIST) -> dict:
    cells = {}
    for spec in C.cell_specs():
        target = spec["target"]
        cells[spec["name"]] = {
            "model": "persistence_pb", "target": target, "h": spec["h"],
            **({"K": spec["K"]} if target == "vix_touch" else {"theta": spec["theta"]}),
            "feature_names": F.feature_names("persistence_pb", target),
            "beta": [-0.4, 0.9], "mu": [18.0 if target == "vix_touch" else 0.17],
            "sd": [7.0 if target == "vix_touch" else 0.08],
            "cov_beta": [[0.01, 0.0], [0.0, 0.02]], "n_fit": 2000,
            "clim_base_rate": 0.4, "baseline_pb": None, "iso_map": None, "derived_layer": "raw",
            "gate_evidence": {"design_pass": True},
        }
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION,
            "finalist_id": finalist, "alpha_ewma": C.EWMA_ALPHA,
            "rv_nan_fill_median": 0.1694207105468098, "cells": cells,
            "reconciliation": {"pass": True}}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _receipt(receipt_id: str = "v13-approval:V13-D3:test:r1", *, decision: str = "V13-D3",
             text: str | None = None, finalist: str = FINALIST, scope: bool = True) -> dict:
    return {"receipt_id": receipt_id, "decision_id": decision,
            "approved_at": "2026-09-09T11:00:00+09:00",
            "approver_role": "repository_owner_and_operator",
            "approval_text": text if text is not None else f"V13-D3 홀드아웃 1회 소모 승인 finalist={finalist}",
            "approval_scope": {"holdout_single_scoring": scope},
            "semantic_reference": {"finalist_id": finalist}, "source": "test"}


def _repo(tmp_path: Path, *, amended: bool = True, receipts: list[dict] | None = None,
          finalist: str = FINALIST, holdout_rows: list[dict] | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / CALENDAR_RELATIVE, root / CALENDAR_RELATIVE)
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["development_protocol"]["holdout_execution_path"] = (
        "named_verb_guarded" if amended else "absent_by_construction")
    contract["gates"]["champion"]["finalist_id"] = finalist
    contract["gates"]["champion"]["cells"] = {name: "persistence_pb" for name in C.CELL_ORDER}
    artifact = _frozen(finalist)
    path = root / C.COEFFICIENTS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    contract["frozen_coefficients"] = {"path": C.COEFFICIENTS_RELATIVE.as_posix(),
                                       "sha256": C.sha256_file(path),
                                       "content_hash": artifact["content_hash"],
                                       "finalist_id": finalist, "refit_prohibited": True}
    (root / C.CONTRACT_RELATIVE).write_text(
        yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ledgers = root / "data/timeseries_v13/ledgers"
    ledgers.mkdir(parents=True, exist_ok=True)
    (ledgers / "approvals.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in (receipts or [])), encoding="utf-8")
    if holdout_rows:
        (ledgers / "holdout_scorings.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in holdout_rows), encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _archive(monkeypatch):
    """홀드아웃 창을 덮는 합성 관측. 호출되면 '데이터를 읽었다'는 뜻이라 거부 테스트에서 실패 신호가 된다."""
    calls: list[int] = []

    def _read(*_a, **_k):
        calls.append(1)
        return _observations(date(2013, 1, 2), date(2018, 12, 31))

    monkeypatch.setattr(H, "read_market_observations", _read)
    return calls


def test_holdout_refuses_before_the_contract_is_amended(tmp_path, _archive) -> None:
    root = _repo(tmp_path, amended=False, receipts=[_receipt()])
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="amended"):
        H.score_holdout(root, approval_receipt_id="v13-approval:V13-D3:test:r1")
    assert not _archive, "계약 개정 전에는 관측을 읽지 않는다"


def test_holdout_without_an_approval_receipt_is_refused_before_reading_data(tmp_path, _archive) -> None:
    root = _repo(tmp_path, receipts=[])
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="user-approval"):
        H.score_holdout(root, approval_receipt_id="")
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="not found"):
        H.score_holdout(root, approval_receipt_id="nope")
    assert not _archive, "승인 없이는 관측을 읽지 않는다"
    assert not (root / C.HOLDOUT_LEDGER_RELATIVE).exists()


def test_holdout_rejects_wrong_decision_scope_text_or_finalist(tmp_path, _archive) -> None:
    cases = [
        (_receipt(decision="V13-D5"), "not a V13-D3"),
        (_receipt(text="   "), "verbatim approval text"),
        (_receipt(text="승인합니다"), "must name V13-D3"),
        (_receipt(scope=False), "approval scope"),
        (_receipt(finalist="V13VOL_champion_other"), "must name V13-D3"),
    ]
    for i, (receipt, pattern) in enumerate(cases):
        root = _repo(tmp_path / f"c{i}", receipts=[receipt])
        with pytest.raises(H.TimeSeriesV13HoldoutError, match=pattern):
            H.score_holdout(root, approval_receipt_id=receipt["receipt_id"])
    assert not _archive


def test_holdout_is_consumed_once_per_finalist_and_respects_the_budget(tmp_path, _archive) -> None:
    prior = {"finalist_id": FINALIST, "window_role": "holdout", "status": "fail"}
    root = _repo(tmp_path, receipts=[_receipt()], holdout_rows=[prior])
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="already consumed"):
        H.score_holdout(root, approval_receipt_id="v13-approval:V13-D3:test:r1")
    exhausted = [{"finalist_id": f"V13VOL_champion_{i}", "window_role": "holdout"} for i in range(3)]
    root = _repo(tmp_path / "full", receipts=[_receipt()], holdout_rows=exhausted)
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="budget is exhausted"):
        H.score_holdout(root, approval_receipt_id="v13-approval:V13-D3:test:r1")
    assert not _archive


def test_holdout_scores_only_the_window_and_appends_regardless_of_result(tmp_path) -> None:
    root = _repo(tmp_path, receipts=[_receipt()])
    row = H.score_holdout(root, approval_receipt_id="v13-approval:V13-D3:test:r1",
                          knowledge_cutoff=NOW)
    assert row["window"] == ["2015-01-01", "2018-12-31"]
    assert row["panel_truncated_at"] == "2018-12-31" and row["sealed_bytes_read"] is False
    assert row["status"] in {"pass", "partial", "fail"}
    assert row["holdout_user_approval"].startswith("V13-D3")
    for cell in row["cells"].values():
        if cell.get("first_origin"):
            assert cell["first_origin"] >= "2015-01-01" and cell["last_origin"] <= "2018-12-31"
    rows = [json.loads(line) for line in
            (root / C.HOLDOUT_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1, "결과와 무관하게 정확히 한 행"
    body = {k: v for k, v in rows[0].items() if k != "content_hash"}
    assert C.canonical_hash(body) == rows[0]["content_hash"]
    # 두 번째 시도는 거부된다
    with pytest.raises(H.TimeSeriesV13HoldoutError, match="already consumed"):
        H.score_holdout(root, approval_receipt_id="v13-approval:V13-D3:test:r1")
    assert H.verify_holdout(root)["ok"] is True


def test_holdout_module_has_no_refit_path_and_no_sealed_verb() -> None:
    source = (ROOT / "src/ai_fc/timeseries_v13/holdout.py").read_text(encoding="utf-8")
    assert "logit_fit" not in source, "홀드아웃 모듈에 적합 함수가 있으면 안 된다 (holdout_refit 금지)"
    assert "block_bootstrap_cov" not in source, "계수 재추정 경로 금지"
    assert "sealed_backtest" not in source and "2019-01-01" not in source, "봉인창 진입점 부재"
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert not [w for w in workflows if "timeseries-v13-vol-holdout" in w.read_text(encoding="utf-8")], \
        "홀드아웃 verb 는 어떤 워크플로에서도 호출되지 않는다 (무인 자동화 밖)"


def test_real_holdout_ledger_obeys_the_contract() -> None:
    """실제 저장소의 소모 기록 — 승인·예산·창 규율."""
    rows = [json.loads(line) for line in
            (ROOT / C.HOLDOUT_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if line] \
        if (ROOT / C.HOLDOUT_LEDGER_RELATIVE).is_file() else []
    contract = C.load_contract_v13(ROOT)
    protocol = contract["development_protocol"]
    assert len({r["finalist_id"] for r in rows}) <= protocol["holdout_maximum_finalists"]
    for row in rows:
        assert row["window"] == contract["stopping_points"]["holdout"]["window"]
        assert row["sealed_bytes_read"] is False
        assert row["holdout_user_approval"].strip()
        assert row["finalist_id"] == contract["gates"]["champion"]["finalist_id"]
    if rows:
        publication = contract["publication"]
        assert publication["holdout_status"] == rows[-1]["status"]
        assert sorted(publication["holdout_fail_cells"]) == sorted(rows[-1]["fail_cells"])
        assert sorted(publication["holdout_pass_cells"]) == sorted(rows[-1]["pass_cells"])
        # 배선 자격 = 홀드아웃 PASS ∧ 설계창 국면 가드 통과 (계약 degeneracy_guard.consequences.wiring)
        thin = set(contract["live_display"]["episode_thin_cells"])
        expected = sorted(set(rows[-1]["pass_cells"]) - thin)
        assert sorted(publication["wiring_eligible_cells"]) == expected
    assert H.verify_holdout(ROOT)["ok"] is True
