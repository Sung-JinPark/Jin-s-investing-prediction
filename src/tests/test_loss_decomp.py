"""T04 — 손실 3분해와 NFP 계열 가드를 고정한다.

`Brier = 0.4356` 이라는 숫자 하나로는 무엇이 잘못됐는지 알 수 없다. 질문을 잘못 골랐는지,
운이 나빴는지, 예측이 정직 확률에서 벗어났는지가 구별되지 않고, 셋은 대응이 다르다.
분해가 항등식임을 매번 확인하고, 정직 확률이 **등록 시점 고정값**에서만 오도록 못박는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


# ── 항등식 ───────────────────────────────────────────────────────────

def test_three_pieces_sum_to_the_brier() -> None:
    from ai_fc.loss_decomp import decompose_one
    for q, p, y in ((0.66, 0.59, 0), (0.74, 0.68, 0), (0.11, 0.10, 1),
                    (0.85, 0.85, 1), (0.04, 0.04, 0), (0.5, 0.5, 1)):
        d = decompose_one(question_id="q", forecast_id="f", outcome=y,
                          stated_probability=q, brier=(q - y) ** 2,
                          honest_probability=p, honest_source="test")
        assert d.check_identity(), (q, p, y)
        assert d.floor == pytest.approx(p * (1 - p))
        assert d.floor + d.draw + d.anchor_excess == pytest.approx((q - y) ** 2)


def test_draw_has_zero_mean_under_the_honest_probability() -> None:
    """뽑기 항의 기댓값은 0 이다 — E[(p−y)²] = p(1−p)."""
    from ai_fc.loss_decomp import decompose_one
    p = 0.3
    draws = []
    for y, weight in ((1, p), (0, 1 - p)):
        d = decompose_one(question_id="q", forecast_id="f", outcome=y,
                          stated_probability=p, brier=(p - y) ** 2,
                          honest_probability=p, honest_source="test")
        draws.append(weight * d.draw)
    assert sum(draws) == pytest.approx(0.0, abs=1e-12)


def test_anchor_excess_is_zero_when_the_forecast_equals_the_honest_probability() -> None:
    from ai_fc.loss_decomp import decompose_one
    d = decompose_one(question_id="q", forecast_id="f", outcome=0,
                      stated_probability=0.59, brier=0.59 ** 2,
                      honest_probability=0.59, honest_source="test")
    assert d.anchor_excess == pytest.approx(0.0)
    assert d.brier == pytest.approx(d.floor + d.draw)


def test_anchor_excess_can_be_negative_when_the_forecast_beat_the_honest_probability() -> None:
    """'실력' 축은 부호가 양쪽으로 열려 있어야 한다 — 벌점 전용이면 분해가 아니라 훈계다."""
    from ai_fc.loss_decomp import decompose_one
    d = decompose_one(question_id="q", forecast_id="f", outcome=0,
                      stated_probability=0.40, brier=0.16,
                      honest_probability=0.59, honest_source="test")
    assert d.anchor_excess < 0


# ── 정직 확률의 출처 ─────────────────────────────────────────────────

def test_honest_probability_comes_only_from_registration_time_fields() -> None:
    from ai_fc.loss_decomp import honest_probability_of
    p, src = honest_probability_of({"prereg": {"honest_probability_estimate": 0.09}})
    assert p == pytest.approx(0.09) and "prereg" in src

    p, src = honest_probability_of({"notes": "등록필터: (a) ... [C5 Q3 · 예상확률 20% (첫 예측 전 고정)]"})
    assert p == pytest.approx(0.20) and "첫 예측 전 고정" in src

    p, src = honest_probability_of({"notes": "[C5 Q3 대체 · 예상확률 80% (리서치 이후 산정 — 제외)]"})
    assert p is None and "리서치 이후 산정" in src

    p, src = honest_probability_of({"notes": "근거 없음"})
    assert p is None and "기록돼 있지 않다" in src


def test_undecomposable_rows_are_counted_not_hidden() -> None:
    """분해 불가 행을 조용히 빼면 평균이 '분해된 것들의 세계'만 보여준다."""
    from ai_fc.loss_decomp import decompose_one, summarize
    rows = [
        decompose_one(question_id="a", forecast_id="fa", outcome=0, stated_probability=0.2,
                      brier=0.04, honest_probability=0.2, honest_source="test"),
        decompose_one(question_id="b", forecast_id="fb", outcome=1, stated_probability=0.5,
                      brier=0.25, honest_probability=None, honest_source="기록 없음"),
    ]
    s = summarize(rows)
    assert s["n_rows"] == 2 and s["n_decomposed"] == 1 and s["n_undecomposable"] == 1
    assert s["undecomposable_reasons"] == ["기록 없음"]
    assert s["mean_brier"] == pytest.approx(0.145)          # 전량
    assert s["mean_brier_decomposed"] == pytest.approx(0.04)  # 분해 가능분만
    assert s["identity_holds"] is True


def test_module_never_writes_to_the_ledger() -> None:
    """분해는 읽어서 계산한다 — 원장에 파생열을 붙이면 append-only 규약과 스키마가 충돌한다."""
    source = (ROOT / "src/ai_fc/loss_decomp.py").read_text(encoding="utf-8")
    # 파일 쓰기 호출만 본다. list.append 는 파이썬 내장이라 여기서 걸면 오탐이다.
    for forbidden in ("write_text(", "to_csv", "writer(", "DictWriter", '"w"', "'w'", "'a'", '"a"'):
        assert forbidden not in source, f"분해가 {forbidden} 로 파일을 쓰면 안 된다"
    hashed_before = (ROOT / "calibration/ledger.csv").read_bytes()
    from ai_fc.loss_decomp import decompose_ledger
    decompose_ledger(ROOT)
    assert (ROOT / "calibration/ledger.csv").read_bytes() == hashed_before


# ── 실제 원장 ────────────────────────────────────────────────────────

def test_ledger_decomposition_holds_the_identity() -> None:
    from ai_fc.loss_decomp import decompose_ledger, summarize
    rows = decompose_ledger(ROOT)
    assert rows, "원장이 비어 있다"
    assert summarize(rows)["identity_holds"] is True
    assert all(r.check_identity() for r in rows)


def test_current_sample_has_no_registration_time_honest_probability() -> None:
    """지금 해소된 10행은 전부 분해 불가다 — 커버리지는 앞으로 쌓인다.

    이 사실 자체가 T04 의 결과다. 분해가 '작동한다'와 '지금 쓸 수 있다'는 다른 진술이고
    후자는 아직 거짓이다.
    """
    from ai_fc.loss_decomp import decompose_ledger, summarize
    rows = decompose_ledger(ROOT)
    s = summarize(rows)
    if s["n_rows"] != 10:
        pytest.skip(f"원장이 갱신됨 (primary {s['n_rows']}행)")
    assert s["n_decomposed"] == 0
    assert s["n_undecomposable"] == 10


def test_counterfactual_reproduces_the_reserved_nfp_loss() -> None:
    """예약된 2연패의 크기를 먼저 말해둔다 — 게이트 판정을 예단하지 않는다."""
    from ai_fc.loss_decomp import counterfactual_row_mean
    both_no = counterfactual_row_mean(ROOT, [(0.66, 0), (0.66, 0)])
    if both_no["before_rows"] != 10:
        pytest.skip("원장 갱신")
    assert both_no["before_mean"] == pytest.approx(0.15986, abs=5e-5)
    assert both_no["after_mean"] == pytest.approx(0.20582, abs=5e-5)
    both_yes = counterfactual_row_mean(ROOT, [(0.66, 1), (0.66, 1)])
    assert both_yes["after_mean"] == pytest.approx(0.15248, abs=5e-5)


# ── NFP 계열 가드 ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def registry() -> dict:
    return yaml.safe_load((ROOT / "questions/registry.yaml").read_text(encoding="utf-8"))


def _q(registry: dict, qid: str) -> dict:
    return next(q for q in registry["questions"] if q["id"] == qid)


def test_nfp_postmortem_is_measurement_only(registry) -> None:
    """사후 계측이 재분류로 번지면 그것이 표본 선택이다."""
    for qid in ("nfp-aug2026-below100k", "nfp-oct2026-below100k", "nfp-nov2026-below100k"):
        q = _q(registry, qid)
        pm = q.get("postmortem")
        assert isinstance(pm, dict), f"{qid} 에 postmortem 이 없다"
        assert "재분류" in pm["scope"] and "없음" in pm["scope"]
        assert pm["contract_band"].startswith("reject"), f"{qid} 은 z < 0.7 이어야 한다"
        assert pm["dead_zone_hit"] is True
        assert pm["expected_brier_floor"] > pm["per_question_cap"]
        # 계측이 상태를 바꾸지 않았는지
        assert "research_status" not in pm
        assert q["status"] in ("active", "resolved")


def test_nfp_r2_does_not_erase_r1(registry) -> None:
    for qid in ("nfp-oct2026-below100k", "nfp-nov2026-below100k"):
        note = _q(registry, qid)["postmortem"]["r2_note"]
        assert "사라지지 않는다" in note and "희석" in note


def test_l3_is_not_applied_retroactively(registry) -> None:
    """L3 는 2026-09-10 이후 신규 등록분 전용이다 — 2026-07-20 등록분에 쓰면 소급이다."""
    contract = yaml.safe_load((ROOT / "questions/portfolio_prereg_v1.yaml").read_text(encoding="utf-8"))
    assert "소급" in contract["L3_defer_r1_if_no_consensus"]["scope"]
    for qid in ("nfp-oct2026-below100k", "nfp-nov2026-below100k"):
        note = _q(registry, qid)["postmortem"]["l3_scope_note"]
        assert "L3" in note and "소급하지 않는다" in note
        assert "cadence" in note


def test_the_new_nfp_question_moved_the_threshold_not_the_subject(registry) -> None:
    """같은 σ 를 그대로 두고 임계만 옮겨 바닥을 내렸다 — 이것이 유일하게 작동한 지렛대다."""
    old = _q(registry, "nfp-aug2026-below100k")["postmortem"]
    new = _q(registry, "nfp-dec2026-below-neg75k")["prereg"]
    assert "95" in str(old["z_method"]) and "95,000명" == new["sigma"]
    assert new["z"] > 1.0 > old["z_at_registration"]
    assert new["expected_brier_floor"] < old["expected_brier_floor"]


def test_no_nfp_question_was_voided_or_reclassified(registry) -> None:
    nfp = [q for q in registry["questions"] if q["id"].startswith("nfp-")]
    assert len(nfp) == 6
    assert not [q for q in nfp if q.get("status") == "void"], "NFP 질문이 void 되면 안 된다"
    assert {q["id"] for q in nfp if q.get("status") == "resolved"} == {
        "nfp-jul2026-below100k", "nfp-aug2026-below100k"}
