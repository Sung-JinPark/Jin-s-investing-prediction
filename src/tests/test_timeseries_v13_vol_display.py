"""V13-VOL 표시 투영 — fail-closed 가 먼저, 숫자는 네 게이트·핀·빌드 시점 신선도가 전부 성립할 때만.

V8 표시 테스트(test_timeseries_v8_display.py) 구조 미러: dict 빌더 + tmp_path repo + 실제 시장 달력 계약.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc import timeseries_v13_vol_display as display
from ai_fc.timeseries_v13 import contracts as C

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 8, 5, 0, tzinfo=timezone.utc)  # 월요일 05:00Z → 마지막 완료 세션 2026-09-04(금)


def _finish(body: dict) -> dict:
    body = dict(body)
    body.pop("content_hash", None)
    body["content_hash"] = C.canonical_hash(body)
    return body


def _cells() -> dict:
    out = {}
    for name in C.CELL_ORDER:
        h = int(name.rsplit("h", 1)[1])
        out[name] = {"model": "persistence_pb", "target": "vix_touch" if name.startswith("vix") else "rv_exceedance",
                     "h": h, "p": 0.42, "p_raw": 0.42, "se_raw": 0.03, "band80": [0.38, 0.46],
                     "derived_layer": "raw", "clim_base_rate": 0.31,
                     "reliability": "weak" if h == 63 else "good"}
    return out


def _latest(*, status: str = "live", as_of: str = "2026-09-04", sha: str = "a" * 64) -> dict:
    live = status == "live"
    body = {
        "schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "status": status,
        "as_of": as_of, "knowledge_cutoff": "2026-09-08T03:40:00+00:00",
        "probability_unit": "fraction", "probability_space": C.PROBABILITY_SPACE,
        "coefficients": {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": sha, "content_hash": "c" * 64,
                         "finalist_id": "V13VOL_champion_aec80c65038b"},
        "gate": {"design_gate_pass": live, "armed": live, "coefficients_pinned": live, "freshness_pass": live,
                 "holdout_status": "not_consumed", "reasons": [] if live else ["gates_not_armed"]},
        "freshness": {"rule": "nyse_trading_calendar", "as_of": as_of, "missing_sessions": 0,
                      "max_missing_sessions": 1, "status": "fresh"},
        "publication": {"customer_numbers_visible": live, "reference_opinion_only": True,
                        "combined_with_official_forecasts": False, "combined_with_scenario_v5_2": False,
                        "combined_with_timeseries_v8": False, "trading_signal": False,
                        "holdout_status": "not_consumed"},
        "footnote": "참고 의견 — 매매 신호 아님",
    }
    if live:
        body["inputs"] = {"vix_close": 18.2, "vix_close_ewma21": 17.9, "rv21_ann": 0.15, "rv21_ann_ewma21": 0.16}
        body["cells"] = _cells()
    return _finish(body)


def _repo(tmp_path: Path, *, tier: str, latest: dict | None, sha: str | None = "a" * 64,
          artifact_bytes: bytes | None = b"frozen") -> Path:
    root = tmp_path / "repo"
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / "data/contracts/market_calendar.yaml", root / "data/contracts/market_calendar.yaml") \
        if (ROOT / "data/contracts/market_calendar.yaml").exists() else None
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["publication"]["display_tier"] = tier
    contract["frozen_coefficients"] = {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": sha,
                                       "content_hash": "c" * 64, "finalist_id": "V13VOL_champion_aec80c65038b",
                                       "refit_prohibited": True}
    (root / C.CONTRACT_RELATIVE).write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if artifact_bytes is not None:
        (root / C.COEFFICIENTS_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
        (root / C.COEFFICIENTS_RELATIVE).write_bytes(artifact_bytes)
    if latest is not None:
        (root / C.LATEST_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
        (root / C.LATEST_RELATIVE).write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _pin_sha(monkeypatch):
    # 디스크 artifact 의 sha256 은 테스트 바이트 b"frozen" 이 아니라 계약 핀("a"*64)과 일치해야 live 가 된다.
    monkeypatch.setattr(display, "sha256_file", lambda path: "a" * 64 if path.read_bytes() == b"frozen" else "z" * 64)
    # 달력 계약은 실제 repo 것을 쓴다 (신선도 규칙 실측)
    from ai_fc import scenario
    real = scenario.load_calendar_contract
    monkeypatch.setattr("ai_fc.timeseries_v13.freshness.load_calendar_contract", lambda _root: real(ROOT))


def test_missing_pointer_yields_absent_surface_without_numbers(tmp_path) -> None:
    root = _repo(tmp_path, tier="t2_hidden_panel", latest=None)
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "absent" and proj["numbers_visible"] is False
    assert "cells" not in proj and "inputs" not in proj
    assert proj["publication"]["display_tier"] == "t2_hidden_panel"
    assert proj["publication"]["reference_opinion_only"] is True and proj["publication"]["trading_signal"] is False


def test_tampered_content_hash_fails_closed(tmp_path) -> None:
    latest = _latest(); latest["cells"]["vix25_h5"]["p"] = 0.99  # 해시 뒤 변조
    root = _repo(tmp_path, tier="t2_hidden_panel", latest=latest)
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "hold" and "cells" not in proj
    assert any("content hash" in r for r in proj["gate"]["reasons"])


def test_visibility_may_not_outrun_the_gate() -> None:
    latest = _latest(); latest["gate"]["armed"] = False
    with pytest.raises(display.TimeSeriesV13VolDisplayError, match="four gate"):
        display.validate_latest(_finish(latest))
    latest = _latest(status="hold"); latest["publication"]["customer_numbers_visible"] = True
    with pytest.raises(display.TimeSeriesV13VolDisplayError):
        display.validate_latest(_finish(latest))


def test_hold_surface_must_hide_cells_and_live_cells_must_be_sane() -> None:
    latest = _latest(status="hold"); latest["cells"] = _cells()
    with pytest.raises(display.TimeSeriesV13VolDisplayError, match="hide"):
        display.validate_latest(_finish(latest))
    latest = _latest(); latest["cells"]["rv_h5"]["band80"] = [0.5, 0.46]
    with pytest.raises(display.TimeSeriesV13VolDisplayError, match="out of order"):
        display.validate_latest(_finish(latest))
    latest = _latest(); latest["cells"]["rv_h5"]["model"] = "garch_t_sim"
    with pytest.raises(display.TimeSeriesV13VolDisplayError, match="model invalid"):
        display.validate_latest(_finish(latest))
    latest = _latest(); latest["publication"]["combined_with_timeseries_v8"] = True
    with pytest.raises(display.TimeSeriesV13VolDisplayError, match="isolated"):
        display.validate_latest(_finish(latest))


def test_coefficient_pin_mismatch_on_disk_holds_the_surface(tmp_path) -> None:
    root = _repo(tmp_path, tier="t2_hidden_panel", latest=_latest(), artifact_bytes=b"tampered")
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "hold" and "cells" not in proj
    assert any("coefficients_pin" in r for r in proj["gate"]["reasons"])
    root = _repo(tmp_path / "b", tier="t2_hidden_panel", latest=_latest(sha="b" * 64))
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "hold" and any("differs from contract" in r for r in proj["gate"]["reasons"])


def test_stale_pointer_holds_at_build_time_with_weekend_allowance(tmp_path) -> None:
    # 금요일 자료로 월요일 빌드 → 누락 0 → live
    root = _repo(tmp_path, tier="t2_hidden_panel", latest=_latest(as_of="2026-09-04"))
    assert display.load_projection(root, now=NOW)["status"] == "live"
    # 목요일 자료로 월요일 빌드 → 누락 1(금) → 허용 → live
    root = _repo(tmp_path / "thu", tier="t2_hidden_panel", latest=_latest(as_of="2026-09-03"))
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "live" and proj["freshness"]["missing_sessions"] == 1
    # 수요일 자료로 월요일 빌드 → 누락 2(목·금) → hold
    root = _repo(tmp_path / "wed", tier="t2_hidden_panel", latest=_latest(as_of="2026-09-02"))
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "hold" and "cells" not in proj
    assert any("stale_at_build" in r for r in proj["gate"]["reasons"])


def test_t0_tier_strips_numbers_even_when_pointer_is_live(tmp_path) -> None:
    root = _repo(tmp_path, tier="t0_internal", latest=_latest())
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "internal" and proj["numbers_visible"] is False
    assert "cells" not in proj and "inputs" not in proj
    assert proj["display_state"] == "validation_pending"


def test_t3_without_holdout_sets_bold_caveat_flag(tmp_path) -> None:
    root = _repo(tmp_path, tier="t3_live_card", latest=_latest())
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "live" and proj["publication"]["holdout_caveat_bold"] is True
    root2 = _repo(tmp_path / "t2", tier="t2_hidden_panel", latest=_latest())
    assert display.load_projection(root2, now=NOW)["publication"]["holdout_caveat_bold"] is False


def test_load_projection_end_to_end_live(tmp_path) -> None:
    root = _repo(tmp_path, tier="t2_hidden_panel", latest=_latest())
    proj = display.load_projection(root, now=NOW)
    assert proj["status"] == "live" and proj["numbers_visible"] is True
    assert proj["display_state"] == "research_reference"
    assert list(proj["cells"]) == list(C.CELL_ORDER)
    assert proj["cells"]["vix25_h63"]["reliability"] == "weak"
    assert proj["gate"]["coefficients_pinned"] is True and proj["gate"]["freshness_pass"] is True
    assert proj["reference_question"] == {"id": "vix-25-90d", "horizon_calendar_days": 90,
                                          "divergence_threshold_pp": 15, "action": "display_only"}
    assert proj["combined_with_existing_models"] is False
    assert proj["design_evidence"]["champion_cells"]["rv_h63"] == "persistence_pb"
