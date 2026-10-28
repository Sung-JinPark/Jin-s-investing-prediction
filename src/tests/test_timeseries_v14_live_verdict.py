"""V14 라이브 전진 판정 verb — 계약 live_forward_gate 산술(60 · max(5, ceil(0.1n)) · CI90 · 귀무 · T7)과 범위·무쓰기.

해상 원장은 합성 행으로 직접 쓴다(임시 저장소). 귀무 추출 수는 등록값 120 그대로다 — verb 가 다른 값을 거부하므로
테스트도 줄이지 않는다(셀당 약 1초).
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v14 import contracts as C
from ai_fc.timeseries_v14 import live_verdict as V
from timeseries_v14_fixtures import make_repo, write_contract, write_jsonl

def _sha(root: Path) -> str:
    return C.load_contract_v14(root)["frozen_coefficients"]["sha256"]


def _row(cell: str, origin: str, sha: str, *, p: float, label: float, base: float, role: str,
         cutoff: str = "2027-06-01T00:00:00+00:00") -> dict:
    body = {"schema_version": 1, "resolution_id": f"v14cond-{origin}-{sha[:8]}-{cell}",
            "run_id": f"v14cond-{origin}-{sha[:8]}", "cell": cell, "origin": origin, "role": role,
            "target": "rv_conditional" if cell.startswith("crv") else "vix_conditional", "horizon_sessions": 5,
            "resolved_session": origin, "probability": p, "label": label, "climatology_base_rate": base,
            "brier_model": round((p - label) ** 2, 8), "brier_climatology": round((base - label) ** 2, 8),
            "coefficients_sha256": sha, "knowledge_cutoff": cutoff}
    body["content_hash"] = C.canonical_hash(body)
    return body


def _labels(n: int, events: int, seed: int) -> np.ndarray:
    y = np.zeros(n)
    y[np.random.default_rng(seed).choice(n, size=events, replace=False)] = 1.0
    return y


def _series(cell: str, sha: str, *, n: int, events: int, kind: str, role: str, seed: int = 1) -> list[dict]:
    """kind: good(정렬된 p) · bad(역정렬 p) · void(상수 p 가 잘못 보정된 기후를 자명하게 이김)."""
    y = _labels(n, events, seed)
    rows = []
    for i, label in enumerate(y):
        if kind == "good":
            p, base = (0.85 if label else 0.08), 0.3
        elif kind == "bad":
            p, base = (0.08 if label else 0.85), 0.3
        else:
            p, base = 0.3, 0.95
        origin = (date(2027, 1, 4) + timedelta(days=i)).isoformat()
        rows.append(_row(cell, origin, sha, p=p, label=float(label), base=base, role=role))
    return rows


def _repo(tmp_path: Path, champion: list[str]) -> Path:
    return make_repo(tmp_path, champion=champion)


def _verdict(root: Path, rows: list[dict]) -> dict:
    write_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE, rows)
    return V.live_verdict(root)


FAST_NULL_DRAWS = 6


@pytest.fixture
def fast_null(monkeypatch):
    """집계(T7·범위·무쓰기·국면 라벨) 시험 가속 — 귀무 구성은 그대로(같은 순열 생성기·seed·ℓ, 같은 decide)이되 앞 6개 순열만 평가.

    verb 가 넘기는 draws 는 여전히 등록값 120 이어야 한다(스텁이 확인). 등록 120 추출 귀무 자체는 셀 산술 시험
    (demotion/gate_passed · 귀무 초과 무효 · min_events)이 스텁 없이 그대로 돈다.
    """
    real_permutations = V.S.y_block_permutations

    def sampled(y, decide, *, draws, seed, block):
        assert draws == V.NULL_DRAWS == 120
        perms = list(real_permutations(y, draws=FAST_NULL_DRAWS, seed=seed, block=block))
        return sum(1 for perm in perms if decide(perm)) / len(perms)

    monkeypatch.setattr(V.S, "y_block_null_pass_rate", sampled)


# ── 셀 산술 ─────────────────────────────────────────────────────────────────
def test_registered_form_matches_the_contract_text() -> None:
    from timeseries_v14_fixtures import ROOT
    form = V.registered_form(C.load_contract_v14(ROOT))
    assert form["minimum"] == 60 and form["seed"] == 20261021 and form["null_threshold"] == 0.10
    assert [V.min_events_required(n) for n in (60, 61, 80, 100, 101)] == [6, 7, 8, 10, 11]


def test_contract_text_drift_refuses_to_compute(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    sha = _sha(root)

    def drift(contract: dict) -> None:
        contract["live_forward_gate"]["degeneracy"]["min_events_rule"] = "사건 >= 3"

    write_contract(root, champion=["crv_h5"], sha=sha, content_hash="c", mutate=drift)
    with pytest.raises(C.TimeSeriesV14Error, match="min_events_rule"):
        V.live_verdict(root)


@pytest.mark.parametrize("mutation,needle", [
    (lambda g: g["negative_control_construction"].update(draws=50), "negative_control_construction.draws"),
    (lambda g: g["negative_control_construction"].update(draws="120"), "negative_control_construction.draws"),
    (lambda g: g.pop("negative_control_construction"), "negative_control_construction"),
    (lambda g: g["negative_control_construction"].update(decide="CI90(ℓ13 · B=400 · seed 20261021) 하한 > 0"),
     "B=300"),
    (lambda g: g["negative_control_construction"].update(non_finite_rate="건너뛴다"), "verdict_void_negative_control"),
])
def test_negative_control_construction_drift_refuses_to_compute(tmp_path: Path, mutation, needle: str) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    real = V.registered_form(C.load_contract_v14(root))
    assert real["null_draws"] == 120 and real["null_boot_replicates"] == 300
    write_contract(root, champion=["crv_h5"], sha=_sha(root), content_hash="c",
                   mutate=lambda c: mutation(c["live_forward_gate"]))
    with pytest.raises(C.TimeSeriesV14Error, match=needle):
        V.live_verdict(root)


@pytest.mark.parametrize("draws", [0, 50, 119, 121, True, 120.0])
def test_draws_other_than_the_registered_120_are_refused(tmp_path: Path, draws) -> None:
    """draws=0 이면 통과율이 NaN 이 되고 `NaN > 0.10` 이 거짓이라 귀무를 건너뛴 채 판정이 나왔다 — 입구에서 거부한다."""
    root = _repo(tmp_path, ["crv_h5"])
    write_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE,
                _series("crv_h5", _sha(root), n=80, events=24, kind="bad", role="champion"))
    with pytest.raises(C.TimeSeriesV14Error, match="registered 120"):
        V.live_verdict(root, draws=draws)
    with pytest.raises(C.TimeSeriesV14Error, match="registered 120"):
        V.evaluate_cell(_series("crv_h5", _sha(root), n=80, events=24, kind="bad", role="champion"), draws=draws)


def test_non_finite_null_rate_voids_the_verdict(tmp_path: Path, monkeypatch) -> None:
    """귀무 통과율이 정의되지 않으면(NaN) 강등·통과로 새지 않고 verdict_void_negative_control 로 닫는다."""
    root = _repo(tmp_path, ["crv_h5"])
    calls: list[int] = []

    def undefined(y, decide, *, draws, seed, block):
        calls.append(draws)
        return float("nan")

    monkeypatch.setattr(V.S, "y_block_null_pass_rate", undefined)
    result = _verdict(root, _series("crv_h5", _sha(root), n=80, events=24, kind="bad", role="champion"))
    cell = result["cells"]["crv_h5"]
    assert calls == [120]
    assert cell["paired_loss_vs_climatology"]["ci90"][0] <= 0, "귀무가 없었다면 demotion_candidate 였다"
    assert cell["status"] == "verdict_void_negative_control" and cell["null_invalid"] is True
    assert cell["negative_control_pass_rate"] is None and cell["negative_control_finite"] is False
    assert "non-finite" in cell["note"] and "bss" not in cell and "brier_model" not in cell
    assert result["T7"]["testable_cells"] == []
    assert "null_non_finite" in V.render_table(result)
    import json
    json.loads(V.main_json(result), parse_constant=lambda token: (_ for _ in ()).throw(AssertionError(token)))


def test_insufficient_sample_below_sixty_shows_no_brier(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    cell = _verdict(root, _series("crv_h5", _sha(root), n=59, events=20, kind="good", role="champion"))["cells"]["crv_h5"]
    assert cell["status"] == "insufficient_sample" and cell["matured"] == 59 and "59/60" in cell["note"]
    assert not {"brier_model", "brier_climatology", "bss", "paired_loss_vs_climatology"} & set(cell)
    assert cell["expected_events_model"] > 0 and cell["events"] == 20


@pytest.mark.parametrize("n,events,status", [
    (60, 5, "untestable"),          # need max(5, 6) = 6
    (60, 55, "untestable"),         # 비사건 5 < 6
    (80, 7, "untestable"),          # need 8
    (80, 8, "gate_passed_descriptive"),
])
def test_min_events_rule_is_max_five_or_ten_percent(tmp_path: Path, n: int, events: int, status: str) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    cell = _verdict(root, _series("crv_h5", _sha(root), n=n, events=events, kind="good", role="champion"))["cells"]["crv_h5"]
    assert cell["status"] == status, cell.get("note")
    assert cell["min_events_required"] == V.min_events_required(n)
    if status == "untestable":
        assert "brier_model" not in cell and "paired_loss_vs_climatology" not in cell


def test_demotion_candidate_versus_gate_passed_descriptive(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["crv_h5", "crv_h21"])
    sha = _sha(root)
    rows = (_series("crv_h5", sha, n=80, events=24, kind="good", role="champion")
            + _series("crv_h21", sha, n=80, events=24, kind="bad", role="champion", seed=2))
    cells = _verdict(root, rows)["cells"]
    good, bad = cells["crv_h5"], cells["crv_h21"]
    assert good["status"] == "gate_passed_descriptive" and good["paired_loss_vs_climatology"]["ci90"][0] > 0
    assert good["negative_control_pass_rate"] <= 0.10 and good["bss"] > 0
    assert bad["status"] == "demotion_candidate" and bad["paired_loss_vs_climatology"]["ci90"][0] <= 0
    # 공유 구현 그대로(ℓ13 · B2000 · seed 20261021) — 같은 d 로 다시 계산하면 같은 CI
    from ai_fc.timeseries_v13 import scoring as S
    p = np.array([r["probability"] for r in sorted(rows[:80], key=lambda r: r["origin"])])
    y = np.array([r["label"] for r in sorted(rows[:80], key=lambda r: r["origin"])])
    assert S.block_boot_ci((0.3 - y) ** 2 - (p - y) ** 2, seed=20261021, b=2000, block=13)["ci90"] == \
        good["paired_loss_vs_climatology"]["ci90"]


def test_negative_control_above_threshold_voids_the_verdict(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    cell = _verdict(root, _series("crv_h5", _sha(root), n=80, events=24, kind="void", role="champion"))["cells"]["crv_h5"]
    assert cell["paired_loss_vs_climatology"]["ci90"][0] > 0, "실제 계열에서는 기후를 이긴다"
    assert cell["negative_control_pass_rate"] > 0.10 and cell["status"] == "verdict_void_negative_control"
    assert "bss" not in cell


def test_episode_count_is_a_label_not_a_hold_reason(tmp_path: Path, fast_null) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    sha = _sha(root)
    rows = []
    for i in range(80):                           # 사건 10개가 한 국면(연속) — 국면 1 < 5
        label = 1.0 if 30 <= i < 40 else 0.0
        origin = (date(2027, 1, 4) + timedelta(days=i)).isoformat()
        rows.append(_row("crv_h5", origin, sha, p=0.85 if label else 0.08, label=label, base=0.3, role="champion"))
    cell = _verdict(root, rows)["cells"]["crv_h5"]
    assert cell["episode_thin"] is True and cell["episodes"]["event_runs"] == 1
    assert cell["status"] in V.TESTABLE + ("verdict_void_negative_control",)


def test_distinct_origin_counting_prefers_the_pinned_sha(tmp_path: Path) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    sha = _sha(root)
    rows = _series("crv_h5", sha, n=59, events=20, kind="good", role="champion")
    stale = [_row("crv_h5", r["origin"], "0" * 64, p=0.5, label=r["label"], base=0.3, role="champion",
                  cutoff="2027-12-31T00:00:00+00:00") for r in rows[:10]]
    cell = _verdict(root, rows + stale)["cells"]["crv_h5"]
    assert cell["matured"] == 59 and cell["status"] == "insufficient_sample", "원점은 한 번만 센다"
    # 고른 행이 핀 sha 행이다 — 비핀 행은 knowledge_cutoff 가 더 늦지만(최근 우선이면 그쪽이 뽑힌다) Σp 에 들어가지 않는다
    pinned_sum = round(sum(r["probability"] for r in rows), 3)
    latest_first_sum = round(sum(r["probability"] for r in rows[10:]) + sum(r["probability"] for r in stale), 3)
    assert pinned_sum != latest_first_sum, "두 선택이 구별되는 합성 자료여야 시험이 된다"
    assert cell["expected_events_model"] == pinned_sum
    selected = V._cell_rows(root)["crv_h5"]
    assert len(selected) == 59 and {r["coefficients_sha256"] for r in selected} == {sha}
    assert sorted(r["resolution_id"] for r in selected) == sorted(r["resolution_id"] for r in rows)


# ── 범위 · T7 ───────────────────────────────────────────────────────────────
def test_t7_cannot_trigger_with_one_champion_cell_and_says_so(tmp_path: Path, fast_null) -> None:
    root = _repo(tmp_path, ["crv_h5"])
    sha = _sha(root)
    rows = (_series("crv_h5", sha, n=80, events=24, kind="bad", role="champion")
            + _series("crv_h21", sha, n=80, events=24, kind="bad", role="shadow", seed=3)
            + _series("cvix25_h5", sha, n=80, events=24, kind="bad", role="shadow", seed=4))
    result = _verdict(root, rows)
    t7 = result["T7"]
    assert result["cells"]["crv_h5"]["status"] == "demotion_candidate"
    assert t7["cannot_trigger_by_construction"] is True and t7["would_trigger"] is False
    assert t7["scope_cells"] == ["crv_h5"] and t7["demotion_candidates"] == ["crv_h5"]
    assert "T7 cannot trigger" in V.render_table(result)
    # shadow 셀도 계산·인쇄되지만 판정 범위 밖
    for name in ("crv_h21", "cvix25_h5"):
        assert result["cells"][name]["status"] == "demotion_candidate"
        assert result["cells"][name]["in_verdict_scope"] is False and result["cells"][name]["role"] == "shadow"
    assert result["cells"]["crv_h5"]["in_verdict_scope"] is True
    assert "out_of_verdict_scope" in V.render_table(result)


@pytest.mark.parametrize("kinds,trigger", [
    ({"crv_h5": "bad", "crv_h21": "bad"}, True),                       # 2/2 강등 → 과반
    ({"crv_h5": "bad", "crv_h21": "good"}, False),                     # 1/2 — 과반 아님
    ({"crv_h5": "bad", "crv_h21": "bad", "cvix25_h21": "good"}, True),   # 2/3
    ({"crv_h5": "bad", "crv_h21": "good", "cvix25_h21": "good"}, False),
])
def test_t7_majority_over_testable_champion_cells(tmp_path: Path, fast_null, kinds: dict, trigger: bool) -> None:
    root = _repo(tmp_path, list(kinds))
    sha = _sha(root)
    rows = []
    for seed, (cell, kind) in enumerate(kinds.items(), start=5):
        rows += _series(cell, sha, n=80, events=24, kind=kind, role="champion", seed=seed)
    t7 = _verdict(root, rows)["T7"]
    assert t7["cannot_trigger_by_construction"] is False
    assert t7["testable_cells"] == [c for c in C.CELL_ORDER if c in kinds]
    assert t7["would_trigger"] is trigger and t7["applies_termination"] is False


def test_t7_denominator_excludes_untestable_void_and_shadow_cells(tmp_path: Path, fast_null) -> None:
    root = _repo(tmp_path, ["crv_h5", "crv_h21", "crv_h63"])
    sha = _sha(root)
    rows = (_series("crv_h5", sha, n=80, events=24, kind="bad", role="champion")
            + _series("crv_h21", sha, n=80, events=3, kind="bad", role="champion", seed=6)      # untestable
            + _series("crv_h63", sha, n=80, events=24, kind="void", role="champion", seed=7)    # 무효
            + _series("cvix25_h5", sha, n=80, events=24, kind="bad", role="shadow", seed=8))
    result = _verdict(root, rows)
    t7 = result["T7"]
    assert result["cells"]["crv_h21"]["status"] == "untestable"
    assert result["cells"]["crv_h63"]["status"] == "verdict_void_negative_control"
    assert t7["testable_cells"] == ["crv_h5"] and t7["would_trigger"] is False and "not armed" in t7["note"]


def test_verdict_verb_writes_nothing(tmp_path: Path, fast_null) -> None:
    root = _repo(tmp_path, ["crv_h5", "crv_h21"])
    sha = _sha(root)
    write_jsonl(root / C.RESOLUTION_LEDGER_RELATIVE,
                _series("crv_h5", sha, n=80, events=24, kind="bad", role="champion")
                + _series("crv_h21", sha, n=80, events=24, kind="bad", role="champion", seed=9))

    def snapshot() -> dict[str, str]:
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob("*")) if p.is_file()}

    before = snapshot()
    result = V.live_verdict(root)
    V.render_table(result); V.main_json(result)
    assert result["writes"] == 0 and result["read_only"] is True and result["T7"]["would_trigger"] is True
    assert snapshot() == before
