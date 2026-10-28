"""tools/v14_freeze_champion.py — 설계창 전체 조건부 PB 동결(합성 데이터·임시 루트만).

실저장소 루트로는 돌리지 않는다: champion 은 rung-2 1회 평가 뒤에만 정해지고, 실제 동결·첫 발행은 orchestrator 몫이다.
고정하는 것: 덮어쓰기 거부(아카이브 읽기 전) · _logit_fit 대사 < 1e-10 · rung 러너 정의 패리티 · 2015+ 미열람 ·
rung 결과 없으면 거부 · champion 셀이 최신 rung 에서 PB 가 아니면 거부 · 산출물이 V14 로더의 fail-closed 대조를 통과.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v14 import contracts as C
from ai_fc.timeseries_v14 import pipeline as P
from timeseries_v14_fixtures import CHAMPION, ROOT, Obs, make_repo, roles_for, write_contract

sys.path.insert(0, str(ROOT / "tools"))
T = pytest.importorskip("v14_freeze_champion")
P0 = pytest.importorskip("v14_cond_diagnostics")

RUNG_KEYS = ("rung1_conditional_blocks", "rung2_conditional_blocks")


def _weekdays(start: str, end: str) -> list[str]:
    days = np.arange(np.datetime64(start), np.datetime64(end) + 1, dtype="datetime64[D]")
    return [str(d) for d in days if np.is_busday(d)]


def _synthetic(seed: int = 5, *, post_2014_shift: float = 0.0) -> list[Obs]:
    """2005-01-03 ~ 2016-12-30 평일. VIX = 17·exp(0.35·AR1) (평온·25+ 모두 출현) · NASDAQCOM 변동성 국면 전환(RV21 이 θ 를 넘나든다).

    post_2014_shift 는 2015+ 값만 바꾼다 — 적합 결과가 그대로여야 한다(2015+ 미열람).
    """
    days = _weekdays("2005-01-03", "2016-12-30")
    rng = np.random.default_rng(seed)
    n = len(days)
    x = np.zeros(n); z = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.97 * x[i - 1] + rng.normal(scale=0.25)
        z[i] = 0.98 * z[i - 1] + rng.normal(scale=0.2)
    vix = 17.0 * np.exp(0.35 * x)
    returns = rng.normal(scale=0.0065 * np.exp(0.5 * z))
    ndx = 2000.0 * np.exp(np.cumsum(returns))
    out: list[Obs] = []
    for d, v, q in zip(days, vix, ndx):
        bump = post_2014_shift if d >= "2015-01-01" else 0.0
        out.append(Obs("VIX", d, float(v + bump * 10))); out.append(Obs("NASDAQCOM", d, float(q * (1 + bump))))
    return out


def _outcomes(champion: list[str], *, override: dict[str, str] | None = None) -> dict:
    outcomes = {c: {"champion": C.MODEL_NAME if c in champion else "hold", "rule": "b" if c in champion else "c"}
                for c in C.CELL_ORDER}
    for cell, value in (override or {}).items():
        outcomes[cell]["champion"] = value
    return outcomes


def _freeze_root(tmp_path: Path, *, champion: list[str] = CHAMPION, rung2_results: bool = True,
                 override: dict[str, str] | None = None, rung2_commit: str | None = "deadbeef") -> Path:
    root = make_repo(tmp_path, champion=champion, pin=False)
    (root / C.COEFFICIENTS_RELATIVE).unlink()            # 동결 전 상태 — 합성 계수 파일 없음

    def mutate(contract: dict) -> None:
        contract["rung2_conditional_blocks"]["prereg_commit"] = rung2_commit

    write_contract(root, champion=champion, sha=None, content_hash=None, mutate=mutate)
    contract = C.load_contract_v14(root)
    for key in RUNG_KEYS:
        path = root / contract[key]["results_path"]
        if key == "rung2_conditional_blocks" and not rung2_results:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"adopted": [], "champion_rule_outcomes": _outcomes(champion, override=override if key.startswith("rung2") else None)}
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return root


def _run(root: Path) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = T.main(["--root", str(root)])
    return code, buffer.getvalue()


def _printed(text: str, key: str) -> str:
    return next(line.split("=", 1)[1] for line in text.splitlines() if line.startswith(key + "="))


def _reject_constant(token: str):
    raise AssertionError(f"non-JSON constant {token}")


@pytest.fixture
def archive(monkeypatch):
    obs = _synthetic()
    monkeypatch.setattr(T, "read_market_observations", lambda _root: obs)
    return obs


def test_freeze_writes_once_reconciles_and_refuses_to_overwrite(tmp_path: Path, archive, monkeypatch) -> None:
    root = _freeze_root(tmp_path)
    code, text = _run(root)
    assert code == 0, text
    out = root / C.COEFFICIENTS_RELATIVE
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)      # NaN/Infinity 토큰 없음
    assert C.canonical_hash({k: v for k, v in payload.items() if k != "content_hash"}) == payload["content_hash"]
    assert _printed(text, "sha256") == C.sha256_file(out) and _printed(text, "content_hash") == payload["content_hash"]
    rec = payload["reconciliation"]
    assert rec["pass"] is True and rec["max_abs_beta_diff"] < 1e-10 and rec["max_abs_mu_sd_diff"] < 1e-10
    assert rec["definition_parity_pass"] is True
    assert all(v == 0 for cell in rec["definition_parity"].values() for v in cell.values())
    assert {name: cell["role"] for name, cell in payload["cells"].items()} == roles_for(CHAMPION)
    assert payload["prereg"]["champion_source"] == "rung2_conditional_blocks"
    assert payload["prereg"]["rung1_conditional_blocks"]["prereg_commit"] == "a93801cf"
    assert payload["prereg"]["rung2_conditional_blocks"]["prereg_commit"] == "deadbeef"
    # 산출물은 V14 로더의 fail-closed 대조(sha256·content_hash·셀 사양·역할·대사)를 통과한다
    frozen = C.load_frozen_coefficients(root, expected_sha256=_printed(text, "sha256"),
                                        expected_content_hash=_printed(text, "content_hash"))
    assert set(frozen["cells"]) == set(C.CELL_ORDER)
    # 두 번째 실행은 아카이브를 읽기 전에 거부하고 바이트를 건드리지 않는다
    monkeypatch.setattr(T, "read_market_observations", lambda _root: (_ for _ in ()).throw(AssertionError("read")))
    code, text = _run(root)
    assert code == 2 and "REFUSED" in text and "덮어쓰지 않는다" in text
    assert out.read_bytes() == raw


def test_fit_subset_and_climatology_match_the_rung_runner_definitions(tmp_path: Path, archive) -> None:
    root = _freeze_root(tmp_path)
    assert _run(root)[0] == 0
    payload = json.loads((root / C.COEFFICIENTS_RELATIVE).read_text(encoding="utf-8"))
    contract = C.load_contract_v14(root)
    panel = T.fit_panel(archive, contract)
    vix, rv = panel["vix"], panel["rv21"]
    design = np.array([str(d) >= "2007-01-01" for d in panel["dates"]])
    for spec in P0.v14_cell_specs(contract):                   # rung 러너 정의로 독립 재구성
        y = P0.full_labels(spec, vix, rv)
        level = P0.champion_feature(spec, vix, rv)
        m = design & P0.conditional_subset(spec, vix, rv) & np.isfinite(y) & np.isfinite(level)
        cell = payload["cells"][spec["name"]]
        assert cell["n_fit"] == int(m.sum()) and cell["events_fit"] == int(y[m].sum())
        assert cell["clim_base_rate"] == float(y[m].mean())
        assert 0 < cell["events_fit"] < cell["n_fit"], "합성 경로가 사건·비사건을 모두 만든다"
        assert cell["fit_first_origin"] >= "2007-01-01" and cell["fit_last_origin"] <= "2014-12-31"


def test_freeze_panel_never_includes_dates_after_2014(tmp_path: Path, monkeypatch) -> None:
    obs = _synthetic()
    assert max(o.observation_time for o in obs) > "2016-01-01", "합성 아카이브는 2015+ 를 담고 있다"
    roots = {"a": _freeze_root(tmp_path / "a"), "b": _freeze_root(tmp_path / "b")}
    panel = T.fit_panel(obs, C.load_contract_v14(roots["a"]))
    assert str(panel["dates"][-1]) <= "2014-12-31" and str(panel["dates"][0]) >= "2005-01-01"
    cells = {}
    for name, shift in (("a", 0.0), ("b", 0.7)):               # 2015+ 값만 다른 두 아카이브
        shifted = _synthetic(post_2014_shift=shift)
        monkeypatch.setattr(T, "read_market_observations", lambda _root, rows=shifted: rows)
        assert _run(roots[name])[0] == 0
        payload = json.loads((roots[name] / C.COEFFICIENTS_RELATIVE).read_text(encoding="utf-8"))
        assert payload["panel_last_date"] <= "2014-12-31" and payload["fit_window"] == ["2007-01-01", "2014-12-31"]
        cells[name] = payload["cells"]
    assert cells["a"] == cells["b"], "2015+ 바이트는 적합에 들어가지 않는다"


def test_freeze_refuses_before_the_rung2_result_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(T, "read_market_observations", lambda _root: (_ for _ in ()).throw(AssertionError("read")))
    root = _freeze_root(tmp_path, rung2_results=False)
    code, text = _run(root)
    assert code == 2 and "rung2_conditional_blocks results file is missing" in text
    assert not (root / C.COEFFICIENTS_RELATIVE).exists()
    root = _freeze_root(tmp_path / "null", rung2_commit=None)
    code, text = _run(root)
    assert code == 2 and "prereg_commit is null" in text
    assert not (root / C.COEFFICIENTS_RELATIVE).exists()


def test_freeze_refuses_when_a_champion_cell_is_not_pb_in_the_latest_rung(tmp_path: Path, archive) -> None:
    root = _freeze_root(tmp_path, champion=["crv_h5", "cvix25_h21"], override={"cvix25_h21": "hold"})
    code, text = _run(root)
    assert code == 2 and "cvix25_h21" in text and "not conditional_persistence_pb" in text
    assert not (root / C.COEFFICIENTS_RELATIVE).exists()


def test_frozen_artifact_drives_a_live_publish(tmp_path: Path, archive, monkeypatch) -> None:
    """동결 산출물을 핀하면 라이브 발행이 그 계수로 돈다(통합) — 핀 전에는 hold."""
    from timeseries_v14_fixtures import D0, install, now_after, observations, quiet_paths, sessions, write_receipt

    root = _freeze_root(tmp_path)
    code, text = _run(root)
    assert code == 0
    days = sessions(D0, 120)
    vix, ndx = quiet_paths(120)
    install(monkeypatch, P, observations(days, vix, ndx))
    write_receipt(root)
    assert P.publish_latest_timeseries_v14(root, now=now_after(D0))["status"] == "hold"     # 핀 null
    write_contract(root, champion=CHAMPION, sha=_printed(text, "sha256"), content_hash=_printed(text, "content_hash"),
                   mutate=lambda c: c["rung2_conditional_blocks"].update(prereg_commit="deadbeef"))
    result = P.publish_latest_timeseries_v14(root, now=now_after(D0))
    assert result["status"] == "live" and all(result["condition_met"].values())
    assert P.verify_timeseries_v14(root)["ok"] is True
