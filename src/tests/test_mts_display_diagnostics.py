"""U1 — MTS 표시 진단 차선: 계약 핀·fail-closed·배지 규칙(lag 0/1)·validator·JS 렌더·예산·경계·실원장 오라클.

쓰기는 tmp_path 사본에만. 실저장소는 읽기만 한다(as_of 고정). 배지는 라벨이지 검정이 아니다 —
참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_fc import mts_display_diagnostics as D
from ai_fc import read_model_contract as RMC
from ai_fc.mts_research.label_basis import LABEL_BASIS_RELATIVE
from ai_fc.mts_research.monitor_thresholds import PINNED_THRESHOLD_HASH, THRESHOLDS_RELATIVE
from ai_fc.timeseries_v8.contracts import canonical_hash

ROOT = Path(__file__).resolve().parents[2]
INSTRUCTION = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
V8 = "shadow.mf_dfm_varx_calibrated_v8"
CARD = {"model_id": V8, "numbers_visible": True, "as_of": "2026-11-09"}
SCRIPT = ROOT / "src/ai_fc/dashboard_parts/dashboard.js"


# ---------------------------------------------------------------------------
# 합성 root
# ---------------------------------------------------------------------------


def _hblock(h: int, *, n: int = 11, k: int = 11, state: str = "normal", breaches=(), shock_days=()) -> dict:
    return {"h": h, "n": n, "window_k": k, "state": state, "breaches": list(breaches),
            "shock_days": list(shock_days), "label": "연구 라벨 · 복수 에피소드", "single_episode": False,
            "L1": {"skill": 0.0123, "ci90_block": [-0.03, 0.06], "threshold_window_matches_n": n == k,
                   "sealed": {"percentile": 0.512}}}


def _default_bases() -> dict:
    def basis() -> dict:
        return {"representative": {"h21": _hblock(21, n=7, k=8, state="insufficient"), "h5": _hblock(5)},
                "post_dated": {"h1": _hblock(1, n=12, k=12, state="near_tail")}}
    return {name: basis() for name in D.LIVE_BASES}


def _root(tmp_path: Path, *, flags=("C6",), stalled=(), c6_triggered=("switch", "near_tie"),
          monitor_as_of="2026-11-09", live_as_of="2026-11-09", live_bases=None, latest_overrides=None,
          ledger_hash="x", summary=None) -> Path:
    root = tmp_path / "repo"
    for relative in (D.CONTRACT_RELATIVE, THRESHOLDS_RELATIVE, LABEL_BASIS_RELATIVE):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    latest = {"as_of": monitor_as_of, "status": "ok", "flags": list(flags), "threshold_hash": PINNED_THRESHOLD_HASH,
              "threshold_status": "ok", "c12_stalled_series": list(stalled), "c6_triggered": list(c6_triggered)}
    latest.update(latest_overrides or {})
    derived = {"schema_version": 1, "monitor_version": "coherence_monitor_v1", "n_dates": 21,
               "retrospective_rows": 21, "first_as_of": "2026-10-02", "last_as_of": monitor_as_of,
               "ledger_last_content_hash": "x", "latest": latest,
               "indicator_summary": summary or {key: {"n_dates_evaluated": 21, "n_flagged": 17, "n_episodes": 3}
                                                for key in ("C1", "C6", "C8", "C12")}}
    path = root / D.COHERENCE_DERIVED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(derived, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    ledger = root / D.COHERENCE_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"content_hash": ledger_hash}) + "\n", encoding="utf-8")
    live = {"schema_version": 1, "status": "ok", "threshold_status": "ok", "threshold_hash": PINNED_THRESHOLD_HASH,
            "as_of_session": live_as_of, "last_resolved_origin": "2026-10-30",
            "bases": live_bases if live_bases is not None else _default_bases()}
    (root / D.LIVE_DERIVED).write_text(json.dumps(live, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return root


def _ids(projection: dict) -> list[str]:
    return [badge["id"] for badge in projection["badges"]]


# ---------------------------------------------------------------------------
# 계약
# ---------------------------------------------------------------------------


def test_contract_hash_pinned_and_fields() -> None:
    contract = yaml.safe_load((ROOT / D.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    assert canonical_hash(contract) == D.PINNED_CONTRACT_HASH
    assert contract["thresholds"]["canonical_hash"] == PINNED_THRESHOLD_HASH
    character = contract["character"]
    assert character["display_only"] is True and character["numbers_changed"] is False
    assert character["auto_reforecast"] is False and character["notice"] == "참고 의견, 매매 신호 아님"
    assert set(contract["badges"]) == {"C1", "C6", "C8", "C12", "L1"}
    assert "C11" in contract["excluded"]
    approval = contract["approval"]
    assert approval["literal_template_match"] is False
    assert approval["approval_form"] == "delegated_bundle_instruction"
    assert approval["approval_text"] == INSTRUCTION
    assert approval["template_text"] != INSTRUCTION
    assert approval["instructed_at_upper_bound"] == "2026-11-11T09:03:44Z"
    assert contract["fold"]["basis_mixing"] == "prohibited"
    assert contract["badges"]["L1"]["horizons"] == [5, 21]
    assert contract["freshness"]["coherence_origin_badge_max_lag_sessions"] == 0
    assert contract["label_basis_source"] == LABEL_BASIS_RELATIVE.as_posix()
    assert "V13-D16" in contract["cross_reference"]
    assert "official_basis" not in contract and "diagnostic_bases" not in contract
    assert contract["read_model"]["budget_bytes"] == 8000
    assert "data/mts_research/ledgers/fed_ebp_v1.jsonl" in contract["batch"]["commit_allowlist"]


def test_research_contract_still_audit_only() -> None:
    draft = yaml.safe_load((ROOT / "data/mts_research/contracts/mts_research_v1.draft.yaml").read_text(encoding="utf-8"))
    text = json.dumps(draft, ensure_ascii=False, default=str)
    assert "audit_only" in text

    def find(node, key):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    yield v
                yield from find(v, key)
        elif isinstance(node, list):
            for item in node:
                yield from find(item, key)

    assert list(find(draft, "production_publish_enabled")) and all(
        value is False for value in find(draft, "production_publish_enabled"))
    assert "audit_only" in list(find(draft, "mode"))


# ---------------------------------------------------------------------------
# 배지 규칙
# ---------------------------------------------------------------------------


def test_ok_path_filters_c11_and_optional_c12(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1", "C6", "C11", "C12"), stalled=("FED_EBP",))
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "ok" and out["coherence_status"] == "ok" and out["origin_badges"] == "shown"
    assert _ids(out) == ["C1", "C6"]
    c6 = out["badges"][1]
    assert c6["detail"] == ["λ 전환", "근소차"]
    contract = yaml.safe_load((ROOT / D.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    for badge in out["badges"]:
        assert set(contract["mandatory_badge_fields"]["coherence"]) <= set(badge)
        assert badge["card_origin_match"] is True
    assert out["coherence"]["c12_stalled_series"] == ["FED_EBP"]


def test_c12_badge_when_v8_input_stalls(tmp_path) -> None:
    out = D.load_projection(_root(tmp_path, flags=("C12",), stalled=("DGS2", "FED_EBP")), timeseries=CARD)
    assert _ids(out) == ["C12"]
    assert out["badges"][0]["detail"] == ["DGS2"] and out["badges"][0]["label"] == "시장 입력 수집 정지"


def test_origin_badges_need_same_origin(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1", "C6", "C8", "C12"), stalled=("VIX",), monitor_as_of="2026-11-06")
    out = D.load_projection(root, timeseries=CARD)
    assert out["coherence_status"] == "ok" and out["as_of_lag_sessions"] == 1
    assert _ids(out) == ["C12"]
    assert out["badges"][0]["card_origin_match"] is False
    assert out["origin_badges"] == "suppressed_card_origin_differs"


@pytest.mark.parametrize(("monitor", "expected"), [("2026-11-05", "as_of_mismatch"), ("2026-11-10", "as_of_mismatch")])
def test_coherence_lag_rules(tmp_path, monitor, expected) -> None:
    out = D.load_projection(_root(tmp_path, flags=("C1", "C12"), stalled=("VIX",), monitor_as_of=monitor),
                            timeseries=CARD)
    assert out["coherence_status"] == expected and _ids(out) == []


@pytest.mark.parametrize(("live_as_of", "expected"), [
    ("2026-11-10", "ok"), ("2026-11-11", "as_of_mismatch"), ("2026-11-02", "ok"), ("2026-10-30", "as_of_mismatch")])
def test_live_lag_rules(tmp_path, live_as_of, expected) -> None:
    out = D.load_projection(_root(tmp_path, live_as_of=live_as_of), timeseries=CARD)
    assert out["live_status"] == expected
    assert (out["live"] is not None) == (expected == "ok")


def test_contract_tamper_hides_everything(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1",))
    path = root / D.CONTRACT_RELATIVE
    path.write_text(path.read_text(encoding="utf-8").replace("budget_bytes: 8000", "budget_bytes: 8001"),
                    encoding="utf-8")
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "contract_hash_mismatch" and out["badges"] == [] and out["live"] is None


def test_threshold_tamper_hides_everything(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1",))
    path = root / THRESHOLDS_RELATIVE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["coherence"]["C1_vol_staleness_max"] = 1.2
    path.write_text(json.dumps(payload), encoding="utf-8")
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "threshold_hash_mismatch" and out["badges"] == [] and out["live"] is None


def test_label_basis_tamper_drops_live_only(tmp_path) -> None:
    root = _root(tmp_path, flags=("C6",))
    path = root / LABEL_BASIS_RELATIVE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["official_basis"]["label_basis"] = "xnas_diagnostic_v1"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = D.load_projection(root, timeseries=CARD)
    assert out["live_status"] == "label_basis_hash_mismatch" and out["live"] is None
    assert _ids(out) == ["C6"]


def test_stale_derived_hides_coherence_badges(tmp_path) -> None:
    grid = _default_bases()
    grid["ledger_grid"]["representative"]["h21"] = _hblock(21, state="breach", breaches=["L1_skill_below_q05"])
    out = D.load_projection(_root(tmp_path, flags=("C1",), ledger_hash="y", live_bases=grid), timeseries=CARD)
    assert out["coherence_status"] == "derived_stale"
    assert _ids(out) == ["L1"]


def test_derived_threshold_hash_mismatch(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1",), latest_overrides={"threshold_hash": "0" * 64})
    out = D.load_projection(root, timeseries=CARD)
    assert out["coherence_status"] == "derived_hash_mismatch" and _ids(out) == []


@pytest.mark.parametrize("card", [
    {**CARD, "numbers_visible": False}, None, {**CARD, "model_id": "shadow.v5"}])
def test_hidden_v8_card_carries_nothing(tmp_path, card) -> None:
    out = D.load_projection(_root(tmp_path, flags=("C1", "C6")), timeseries=card)
    assert out["status"] == "v8_hidden" and out["badges"] == [] and out["live"] is None


def test_l1_badge_only_for_grid_breach_and_shock_count(tmp_path) -> None:
    contract = yaml.safe_load((ROOT / D.CONTRACT_RELATIVE).read_text(encoding="utf-8"))

    def run(bases, name):
        return D.load_projection(_root(tmp_path / name, flags=(), live_bases=bases), timeseries=CARD)

    bases = _default_bases()
    bases["ledger_grid"]["representative"]["h21"] = _hblock(21, n=7, k=8, state="breach",
                                                            breaches=["L1_skill_below_q05"])
    out = run(bases, "zero")
    assert _ids(out) == ["L1"]
    badge = out["badges"][0]
    assert badge["h"] == 21 and badge["n_shock_days"] == 0 and badge["single_episode"] is False
    assert set(contract["mandatory_badge_fields"]["L1"]) <= set(badge)
    bases["ledger_grid"]["representative"]["h21"]["shock_days"] = ["2026-11-05"]
    assert run(bases, "one")["badges"][0]["single_episode"] is True
    h63 = _default_bases()
    h63["ledger_grid"]["representative"]["h63"] = _hblock(63, state="breach", breaches=["L1_skill_below_q05"])
    assert _ids(run(h63, "h63")) == []
    xnas = _default_bases()
    for name in D.LIVE_BASES[1:]:
        xnas[name]["representative"]["h5"] = _hblock(5, state="breach", breaches=["L1_skill_below_q05"])
    assert _ids(run(xnas, "xnas")) == []
    out = run(_default_bases(), "plain")
    assert _ids(out) == []
    assert [name for name, block in out["live"]["bases"].items() if block["official"]] == ["ledger_grid"]
    for block in out["live"]["bases"].values():
        for item in block["horizons"]:
            assert "label" not in item and "single_episode" not in item
            assert item["state_label"] == contract["fold"]["state_labels"][item["state"]]


def test_horizons_sorted_numerically(tmp_path) -> None:
    bases = _default_bases()
    for h in (5, 21):
        bases["ledger_grid"]["representative"][f"h{h}"] = _hblock(h, state="breach", breaches=["L1_skill_below_q05"])
    out = D.load_projection(_root(tmp_path, flags=(), live_bases=bases), timeseries=CARD)
    assert [item["h"] for item in out["live"]["bases"]["ledger_grid"]["horizons"]] == [1, 5, 21]
    assert [badge["h"] for badge in out["badges"]] == [5, 21]


def test_unregistered_live_state_drops_live(tmp_path) -> None:
    bases = _default_bases()
    bases["ledger_grid"]["representative"]["h5"]["state"] = "weird"
    out = D.load_projection(_root(tmp_path, live_bases=bases), timeseries=CARD)
    assert out["live_status"] == "unavailable:ValueError" and out["live"] is None


def _rewrite_json(path: Path, mutate) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(mutate(value), ensure_ascii=False), encoding="utf-8")


def _null_l1(report: dict) -> dict:
    report["bases"]["ledger_grid"]["representative"]["h5"]["L1"] = None
    return report


def _latest_list(derived: dict) -> dict:
    derived["latest"] = ["oops"]
    return derived


@pytest.mark.parametrize(("target", "mutate", "lane"), [
    ("coherence", lambda d: [d], "coherence_status"),                       # derived 최상위가 list
    ("coherence", _latest_list, "coherence_status"),                        # latest 가 list
    ("live", _null_l1, "live_status"),                                      # bases.ledger_grid.….h5.L1 = null
    ("live", lambda d: [d], "live_status"),                                 # live derived 최상위가 list
])
def test_malformed_derived_fails_closed_without_raising(tmp_path, target, mutate, lane) -> None:
    """리뷰 B1: 봇이 쓴 기형 derived 1개가 예외로 사이트 빌드를 죽이면 안 된다 — 그 차선만 배지 0."""
    root = _root(tmp_path, flags=("C6",))
    _rewrite_json(root / (D.COHERENCE_DERIVED if target == "coherence" else D.LIVE_DERIVED), mutate)
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "ok"
    assert out[lane] == "unavailable:AttributeError"
    if lane == "coherence_status":
        assert out["coherence"] is None and _ids(out) == []
        assert out["live_status"] == "ok"                                   # 다른 차선은 살아 있다
    else:
        assert out["live"] is None and "L1" not in _ids(out)
        assert out["coherence_status"] == "ok" and _ids(out) == ["C6"]


def test_any_unexpected_exception_closes_whole_projection(tmp_path, monkeypatch) -> None:
    root = _root(tmp_path, flags=("C6",))

    def boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(D, "load_contract", boom)
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "unavailable:RuntimeError" and out["badges"] == [] and out["live"] is None
    assert out["display_only"] is True and out["notice"] == "참고 의견, 매매 신호 아님"


def test_derived_latest_not_ok_has_own_status(tmp_path) -> None:
    root = _root(tmp_path, flags=("C1",), latest_overrides={"status": "insufficient_inputs"})
    out = D.load_projection(root, timeseries=CARD)
    assert out["coherence_status"] == "derived_latest_not_ok" and _ids(out) == []
    root = _root(tmp_path / "b", flags=("C1",))
    _rewrite_json(root / D.LIVE_DERIVED, lambda d: {**d, "status": "partial"})
    out = D.load_projection(root, timeseries=CARD)
    assert out["live_status"] == "derived_latest_not_ok" and out["live"] is None


def test_missing_calendar_dependency_does_not_break_build(tmp_path, monkeypatch) -> None:
    root = _root(tmp_path, flags=("C12",), stalled=("VIX",), monitor_as_of="2026-11-06", live_as_of="2026-11-06")
    monkeypatch.setitem(sys.modules, "exchange_calendars", None)
    out = D.load_projection(root, timeseries=CARD)
    assert out["status"] == "ok" and out["badges"] == []
    for key in ("coherence_status", "live_status"):
        assert out[key] in {"unavailable:ImportError", "unavailable:MtsSessionError"}, out[key]


def test_dashboard_survives_missing_diagnostics_module(tmp_path, monkeypatch) -> None:
    from ai_fc import dashboard
    from ai_fc.db import ingest
    from test_dashboard import LEDGER, REGISTRY_YAML

    repo = tmp_path / "site"
    (repo / "questions").mkdir(parents=True)
    (repo / "questions" / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    (repo / "forecasts").mkdir()
    (repo / "calibration").mkdir()
    (repo / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    for relative in (Path("data/contracts/calendar_sources.yaml"), Path("data/calendar/events.csv")):
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_bytes((ROOT / relative).read_bytes())
    conn = ingest.connect(repo / "db" / "index.db")
    try:
        ingest.sync(conn, repo)
        model = dashboard.build_read_model(conn, repo)
        assert model["mts_display_diagnostics"]["status"] == "contract_missing"
        assert model["mts_display_diagnostics"]["badges"] == []

        def schema_crash(*_args, **_kwargs):
            raise AttributeError("'list' object has no attribute 'get'")

        monkeypatch.setattr(D, "load_contract", schema_crash)     # 호출 쪽은 try 밖 — 로더가 스스로 닫아야 한다
        model = dashboard.build_read_model(conn, repo)
        assert model["mts_display_diagnostics"]["status"] == "unavailable:AttributeError"
        assert model["mts_display_diagnostics"]["badges"] == []
        monkeypatch.setitem(sys.modules, "ai_fc.mts_display_diagnostics", None)
        model = dashboard.build_read_model(conn, repo)
    finally:
        conn.close()
    diag = model["mts_display_diagnostics"]
    assert diag["status"] in {"unavailable:ImportError", "unavailable:ModuleNotFoundError"}
    assert diag["badges"] == [] and diag["display_only"] is True


def _worst_case_root(tmp_path: Path) -> Path:
    bases = {}
    for name in D.LIVE_BASES:
        bases[name] = {"representative": {f"h{h}": _hblock(h, state="breach", breaches=["L1_skill_below_q05"],
                                                            shock_days=["2026-11-05", "2026-11-06"])
                                          for h in (5, 21, 63)},
                       "post_dated": {"h1": _hblock(1, state="near_tail")}}
    return _root(tmp_path, flags=("C1", "C6", "C8", "C12"), stalled=("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXBGS",
                                                                     "FED_EBP"),
                 c6_triggered=("switch", "near_tie", "disagree"), live_bases=bases)


def test_payload_budget_worst_case(tmp_path) -> None:
    from ai_fc import dashboard

    out = D.load_projection(_worst_case_root(tmp_path), timeseries=CARD)
    assert _ids(out) == ["C1", "C6", "C8", "C12", "L1", "L1"]
    size = len(json.dumps(out, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
    assert dashboard.MTS_DISPLAY_DIAGNOSTICS_BUDGET_BYTES == 8000
    assert size < 0.9 * dashboard.MTS_DISPLAY_DIAGNOSTICS_BUDGET_BYTES, size
    assert dashboard._guard_mts_display_diagnostics_budget(out) is out


def test_deterministic(tmp_path) -> None:
    root = _worst_case_root(tmp_path)
    assert D.load_projection(root, timeseries=CARD) == D.load_projection(root, timeseries=CARD)


def test_real_ledger_oracle_fixed_as_of(tmp_path) -> None:
    """실 원장의 as_of ≤ 2026-11-09 접두부(append-only 라 고정) — 카드 11-09 면 C6 하나."""
    from ai_fc.mts_research.artifacts import read_chain
    from ai_fc.mts_research.audits.coherence import build_derived_summary

    rows = [row for row in read_chain(ROOT, D.COHERENCE_LEDGER) if row["as_of"] <= "2026-11-09"]
    assert len(rows) == 27
    root = tmp_path / "repo"
    for relative in (D.CONTRACT_RELATIVE, THRESHOLDS_RELATIVE, LABEL_BASIS_RELATIVE):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)
    ledger = root / D.COHERENCE_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                              for row in rows), encoding="utf-8")
    (root / D.COHERENCE_DERIVED).parent.mkdir(parents=True, exist_ok=True)
    (root / D.COHERENCE_DERIVED).write_text(json.dumps(build_derived_summary(rows), ensure_ascii=False),
                                            encoding="utf-8")
    out = D.load_projection(root, timeseries=CARD)
    assert out["coherence_status"] == "ok" and _ids(out) == ["C6"]
    c6 = out["badges"][0]
    assert (c6["n_flagged"], c6["n_evaluated"], c6["n_episodes"], c6["single_episode"]) == (17, 21, 3, False)
    assert c6["detail"] == ["λ 전환", "근소차"]
    assert out["coherence"]["c12_stalled_series"] == ["FED_EBP"]
    later = D.load_projection(root, timeseries={**CARD, "as_of": "2026-11-10"})
    assert _ids(later) == [] and later["origin_badges"] == "suppressed_card_origin_differs"


# ---------------------------------------------------------------------------
# read-model validator·schema
# ---------------------------------------------------------------------------


def _diag_errors(diag: dict, *, visible: bool = True) -> list[str]:
    model = {"timeseries": {"numbers_visible": visible}, "mts_display_diagnostics": diag}
    return [error for error in RMC.validate(model) if error.startswith("mts_display_diagnostics")]


def test_read_model_validator_rules(tmp_path) -> None:
    bases = _default_bases()
    bases["ledger_grid"]["representative"]["h21"] = _hblock(21, state="breach", breaches=["L1_skill_below_q05"])
    good = D.load_projection(_root(tmp_path, flags=("C6", "C12"), stalled=("VIX",), live_bases=bases),
                             timeseries=CARD)
    assert _ids(good) == ["C6", "C12", "L1"]
    assert _diag_errors(good) == []
    assert _diag_errors(json.loads(json.dumps(good)), visible=False)

    def mutated(fn) -> dict:
        diag = json.loads(json.dumps(good))
        fn(diag)
        return diag

    cases = [
        lambda d: d.update(status="derived_stale"),
        lambda d: d["badges"][0].update(id="C11"),
        lambda d: d["live"]["bases"]["xnas_diagnostic_v1.matched_ledger_rows"].update(official=True),
        lambda d: d["badges"][0].update(n_flagged=99),
        lambda d: d["badges"][0].update(card_origin_match=False),
        lambda d: d["badges"][2].update(h=63),
        lambda d: d["badges"][2].update(single_episode=True),
        lambda d: d["live"]["bases"]["ledger_grid"]["horizons"][0].update(label="복수 에피소드"),
        lambda d: d.update(notice="매수"),
        lambda d: d.update(quantiles=[1]),
        lambda d: d.update(display_only=False),
    ]
    for index, fn in enumerate(cases):
        assert _diag_errors(mutated(fn)), index


def test_schema_declares_optional_key() -> None:
    schema = RMC.schema()
    assert "mts_display_diagnostics" in schema["properties"]
    assert "mts_display_diagnostics" not in schema["required"]


# ---------------------------------------------------------------------------
# dashboard.js (node)
# ---------------------------------------------------------------------------


def _js_block() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    return source[source.index("/* ── MTS 감시 배지(U1"):source.index("function timeseriesScore100Card(")]


def _render(tmp_path: Path, diag: dict | None, ts: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    stubs = "\n".join(line for line in source.splitlines()
                      if line.startswith("const hasNumeric=") or line.startswith("const esc="))
    program = tmp_path / "mts.js"
    program.write_text(stubs + f"\nlet DATA={json.dumps({'mts_display_diagnostics': diag}, ensure_ascii=False)};\n"
                       + _js_block()
                       + f"\nconst ts={json.dumps(ts)};\n"
                       + "process.stdout.write(JSON.stringify({badges:tsMonitorBadges(ts),fold:tsMonitorFold(ts)}));",
                       encoding="utf-8")
    result = subprocess.run([node, str(program)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_js_badges_and_fold_render_labels_only(tmp_path) -> None:
    root = _root(tmp_path, flags=("C6",))
    diag = D.load_projection(root, timeseries=CARD)
    out = _render(tmp_path, diag, CARD)
    assert 'data-mts-badge="C6"' in out["badges"]
    assert "λ 전환·근소차 · 발동 λ 전환+근소차 · 17/21일 · 에피소드 3" in out["badges"]
    assert _render(tmp_path, diag, {**CARD, "as_of": "2026-11-10"}) == {"badges": "", "fold": ""}
    assert _render(tmp_path, {**diag, "status": "derived_stale"}, CARD) == {"badges": "", "fold": ""}
    for label in ("원장 grid(공식)", "XNAS 진단 — 원장 동일 행", "XNAS 진단 — 확정 목표 전체(잠정 포함)"):
        assert label in out["fold"]
    assert "사후 기록" in out["fold"] and "최근 창 skill" in out["fold"]
    assert "<details" in out["fold"]

    bases = _default_bases()
    bases["ledger_grid"]["representative"]["h21"] = _hblock(21, n=7, k=8, state="breach",
                                                            breaches=["L1_skill_below_q05"])
    l1 = D.load_projection(_root(tmp_path / "l1", flags=(), live_bases=bases), timeseries=CARD)
    rendered = _render(tmp_path, l1, CARD)
    assert "21거래일 n=7/k=8 · 충격일 없음" in rendered["badges"]
    assert "복수 에피소드" not in rendered["badges"] + rendered["fold"]

    c12 = D.load_projection(_root(tmp_path / "c12", flags=("C12",), stalled=("VIX",), monitor_as_of="2026-11-06"),
                            timeseries=CARD)
    rendered = _render(tmp_path, c12, CARD)
    assert "(11-06 기준)" in rendered["badges"]
    assert "원점 배지 미표시" in rendered["fold"]
    assert "data-ts-chart" not in _js_block()


def test_hero_and_live_section_call_sites() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("function renderTimeseriesV8(")
    body = source[start:source.index("\nfunction ", start + 10)]
    assert "${tsInputStateChip(ts)}${tsMonitorBadges(ts)}" in body
    assert "${tsV8ForwardDisclosure(ts)}${tsMonitorFold(ts)}" in body
    hidden_start = source.index("function renderTimeseries(")
    hidden = source[source.index("if(!visible){", hidden_start):source.index("const horizons=[1,5,21,63];", hidden_start)]
    assert "tsMonitorBadges" not in hidden and "tsMonitorFold" not in hidden
    # 정의 1 + 호출 1 — 다른 화면(보류·V13 카드)에는 싣지 않는다
    assert source.count("tsMonitorBadges(ts)") == 2 and source.count("tsMonitorFold(ts)") == 2


# ---------------------------------------------------------------------------
# 경계
# ---------------------------------------------------------------------------


def test_new_file_names_avoid_protected_globs() -> None:
    from test_mts_research_protected_glob_names import _protected

    for relative in ("data/mts_research/contracts/mts_display_diagnostics_v1.yaml",
                     "src/ai_fc/mts_display_diagnostics.py",
                     ".github/workflows/mts-coherence-monitor.yml",
                     "src/tests/test_mts_coherence_catch_up.py",
                     "src/tests/test_mts_display_diagnostics.py",
                     "src/tests/test_mts_coherence_monitor_workflow.py",
                     "src/tests/test_mts_v8_live_monitor_if_stale.py"):
        assert _protected(relative) == [], relative


def _research_readers() -> dict[str, set[str]]:
    """mts_research 밖 src/ai_fc 모듈 중 연구 계층을 import 하거나 'data/mts_research/' 문자열 상수를 가진 것."""
    base = ROOT / "src/ai_fc"
    hits: dict[str, set[str]] = {}
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(base).as_posix()
        if relative.startswith("mts_research/"):
            continue
        why: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "mts_research" in module.split(".") or any(alias.name == "mts_research" for alias in node.names):
                    why.add("import")
            elif isinstance(node, ast.Import):
                if any("mts_research" in alias.name.split(".") for alias in node.names):
                    why.add("import")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "data/mts_research/" in node.value:
                why.add("path")
        if why:
            hits[relative] = why
    return hits


def test_research_ledger_readers_outside_mts_research_are_pinned() -> None:
    assert set(_research_readers()) == {
        "timeseries_v8_display.py", "timeseries_daily6m/display.py", "mts_display_diagnostics.py"}
    contract = yaml.safe_load((ROOT / D.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    allowed = {item["path"] for item in contract["allowed_reads"]} | {D.CONTRACT_RELATIVE.as_posix()}
    tree = ast.parse((ROOT / "src/ai_fc/mts_display_diagnostics.py").read_text(encoding="utf-8"))
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("data/")}
    assert constants and constants <= allowed
