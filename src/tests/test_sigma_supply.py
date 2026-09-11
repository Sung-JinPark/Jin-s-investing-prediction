"""T03 — σ 공급과 V13 base rate 배선을 고정한다.

수치 트랙이 게이트에 기여할 수 있는 유일한 합법 경로는 **산포 공급**이다. 확률 결합은
8-8 이 금지한다. 그 경계가 코드에서 흐려지지 않도록, 여기서 세 가지를 못박는다:
σ 는 질문이 묻는 **같은 양**에서만 나온다 · V8 의 방향 필드는 읽지 않는다 ·
미검증 셀은 배선되지 않는다.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: 2026-09-11 기준 재현값. 저장소 스냅샷(2026-08-06)·V8 산출(as_of 2026-09-04)이 바뀌면 달라진다.
H87 = 87


@pytest.fixture(scope="module")
def store():
    from ai_fc.sigma_supply import load_store
    return load_store(ROOT)


# ── 양(quantity) 일치가 선결 조건이다 ────────────────────────────────

def test_adopt_rejects_when_no_path_measures_the_question_quantity() -> None:
    """다른 양을 잰 σ 를 쓰는 것이 SELECTION 거부 8건의 최대 사유였다."""
    from ai_fc.sigma_supply import (SigmaQuote, SigmaSupplyError, TERMINAL_LOG_RETURN,
                                    WINDOW_MAX, adopt)
    quote = SigmaQuote(value=0.08, unit="log_return", quantity=TERMINAL_LOG_RETURN,
                       path="v8_quantiles", source="x", available_at="2026-09-04", method="IQR")
    with pytest.raises(SigmaSupplyError) as exc:
        adopt(WINDOW_MAX, [quote])
    assert "재는 경로가 없다" in str(exc.value)
    assert "지어내지 않는다" in str(exc.value)


def test_adopt_takes_the_larger_sigma_when_both_measure_the_same_quantity() -> None:
    """사용자 확정(2026-09-10): 둘 다면 큰 σ. z 를 낮추는 방향이라 게이밍의 반대편이다."""
    from ai_fc.sigma_supply import SigmaQuote, TERMINAL_LOG_RETURN, adopt

    def q(path: str, value: float) -> SigmaQuote:
        return SigmaQuote(value=value, unit="log_return", quantity=TERMINAL_LOG_RETURN,
                          path=path, source=path, available_at="2026-09-04", method="IQR")

    decision = adopt(TERMINAL_LOG_RETURN, [q("reference_class", 0.0772), q("v8_quantiles", 0.0812)])
    assert decision.adopted.path == "v8_quantiles"
    assert decision.adopted.value == pytest.approx(0.0812)
    assert [c.path for c in decision.cross_checks] == ["reference_class"]
    assert "큰 σ" in decision.rule


def test_probability_is_never_a_sigma_source() -> None:
    from ai_fc.sigma_supply import EVENT_PROBABILITY, SigmaSupplyError, adopt
    with pytest.raises(SigmaSupplyError) as exc:
        adopt(EVENT_PROBABILITY, [])
    assert "8-8" in str(exc.value)


def test_module_never_reads_the_ledger_or_v8_direction_fields() -> None:
    source = (ROOT / "src/ai_fc/sigma_supply.py").read_text(encoding="utf-8")
    for forbidden in ("ledger.csv", "read_ledger", '"probability_up"', "['probability_up']"):
        assert forbidden not in source, f"σ 공급이 {forbidden} 을 읽으면 안 된다"
    # p50 은 문서에서 '읽지 않는다'로만 언급된다 — 실제 접근 표현이 없어야 한다.
    for access in ('node["p50"]', "node['p50']", 'node.get("p50")'):
        assert access not in source, "V8 의 방향 필드에 접근하면 안 된다"


def test_module_never_writes() -> None:
    source = (ROOT / "src/ai_fc/sigma_supply.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "to_csv", "INSERT", "UPDATE"):
        assert forbidden not in source


# ── 실측 재현 — 등록된 질문의 σ 가 이 경로로 다시 나오는가 ───────────

def test_reference_class_reproduces_the_registered_vix40_sigma(store) -> None:
    from ai_fc.sigma_supply import WINDOW_MAX, reference_class_sigma
    quote = reference_class_sigma(
        store, "VIXCLS", WINDOW_MAX, horizon_business_days=H87,
        since="2010-01-01", start_condition=lambda v: 14 <= v <= 18,
        conditioning="출발 VIX 14~18 & 2010년 이후")
    # 등록값 σ=6.553 · 중앙값 25.71
    assert quote.value == pytest.approx(6.553, abs=0.02)
    assert quote.center == pytest.approx(25.71, abs=0.05)
    assert quote.n and quote.n > 1000
    assert "VIXCLS" in quote.source and "IQR" in quote.source


def test_reference_class_reproduces_the_registered_t10y2y_sigma(store) -> None:
    from ai_fc.sigma_supply import WINDOW_MAX, reference_class_sigma
    quote = reference_class_sigma(
        store, "T10Y2Y", WINDOW_MAX, horizon_business_days=H87,
        start_condition=lambda v: 0.20 <= v <= 0.70,
        conditioning="출발 스프레드 0.20~0.70")
    assert quote.value == pytest.approx(0.230, abs=0.01)
    assert quote.center == pytest.approx(0.60, abs=0.02)


def test_v8_sigma_reproduces_the_registered_nasdaq_sigma() -> None:
    from ai_fc.sigma_supply import v8_sigma
    quote = v8_sigma(ROOT, horizon_business_days=H87)
    # 등록값 σ87 = 0.08117 (horizons.63 IQR/1.349 → √(87/63))
    assert quote.value == pytest.approx(0.08117, abs=5e-5)
    assert quote.horizon_business_days == H87
    assert any("지평 환산" in c for c in quote.caveats)
    assert any("섀도" in c for c in quote.caveats)


def test_both_paths_agree_within_an_order_on_nasdaq(store) -> None:
    """양이 같은 두 경로가 크게 어긋나면 그 자체가 경보다."""
    from ai_fc.sigma_supply import TERMINAL_LOG_RETURN, adopt, reference_class_sigma, v8_sigma
    ref = reference_class_sigma(store, "NASDAQCOM", TERMINAL_LOG_RETURN,
                                horizon_business_days=H87, since="2010-01-01",
                                conditioning="2010년 이후")
    v8 = v8_sigma(ROOT, horizon_business_days=H87)
    assert 0.5 < ref.value / v8.value < 2.0, f"두 경로가 2배 이상 어긋난다: {ref.value} vs {v8.value}"
    decision = adopt(TERMINAL_LOG_RETURN, [ref, v8])
    assert decision.adopted.value == max(ref.value, v8.value)


def test_missing_series_is_refused(store) -> None:
    from ai_fc.sigma_supply import SigmaSupplyError, WINDOW_MAX, reference_class_sigma
    with pytest.raises(SigmaSupplyError) as exc:
        reference_class_sigma(store, "NOT_A_SERIES", WINDOW_MAX, horizon_business_days=21)
    assert "저장소에 없다" in str(exc.value)


def test_count_quantity_requires_a_threshold(store) -> None:
    from ai_fc.sigma_supply import SigmaSupplyError, WINDOW_COUNT_ABOVE, reference_class_sigma
    with pytest.raises(SigmaSupplyError):
        reference_class_sigma(store, "VIXCLS", WINDOW_COUNT_ABOVE, horizon_business_days=H87)


def test_sigma_is_not_an_anchor_in_the_wording() -> None:
    """σ 를 건네는 쪽이 임계도 정하면 z 규율은 자기충족이 된다."""
    from ai_fc.sigma_supply import SigmaDecision, SigmaQuote, TERMINAL_LOG_RETURN, supply_lines
    quote = SigmaQuote(value=0.08, unit="log_return", quantity=TERMINAL_LOG_RETURN,
                       path="v8_quantiles", source="x", available_at="2026-09-04", method="IQR")
    decision = SigmaDecision(adopted=quote, rule="단일")
    joined = " ".join(supply_lines(decision))
    assert "임계는 사람이 정한다" in joined
    assert "확률" not in joined.replace("확률은 LLM", ""), "σ 공급 줄에 확률 서술이 섞이면 안 된다"
    assert decision.z(threshold=0.16, center=0.0) == pytest.approx(2.0)


# ── V13 base rate 배선 — 페일클로즈 ──────────────────────────────────

def test_wiring_is_fail_closed_with_zero_targets() -> None:
    """자격 셀은 있으나 대응 질문이 없다 — 아무것도 표시하지 않는다."""
    from ai_fc.vol_base_rate_wiring import eligible_cells, wiring_status, wiring_targets
    assert set(eligible_cells(ROOT)) == {"rv_h5", "rv_h21"}, "계약의 배선 자격 셀이 바뀌었다"
    assert wiring_targets(ROOT) == []
    status = wiring_status(ROOT)
    assert status["targets"] == 0 and status["fail_closed"] is True
    assert "대응 등록 질문이 없다" in status["reason"]


def test_unverified_cell_cannot_be_wired() -> None:
    """홀드아웃 실패 셀(vix25_h63)·국면 미달 셀(vix25_h21)은 지도에 넣어도 거부된다."""
    from ai_fc.vol_base_rate_wiring import VolWiringError, wiring_targets
    for cell in ("vix25_h63", "vix25_h21", "vix30_h21", "rv_h63"):
        with pytest.raises(VolWiringError) as exc:
            wiring_targets(ROOT, cell_question_map={cell: "vix-25-90d"})
        assert "배선 자격이 없다" in str(exc.value)


def test_wiring_refuses_a_question_that_is_not_registered() -> None:
    from ai_fc.vol_base_rate_wiring import VolWiringError, wiring_targets
    with pytest.raises(VolWiringError) as exc:
        wiring_targets(ROOT, cell_question_map={"rv_h5": "no-such-question"})
    assert "레지스트리에 없다" in str(exc.value)


def test_wiring_exports_climatology_never_the_model_probability() -> None:
    """앵커링 금지 — 질문별 매핑 확률은 digest 로 가지 않는다."""
    from ai_fc.vol_base_rate_wiring import FORBIDDEN_CELL_FIELDS, WiringTarget

    target = WiringTarget(cell="rv_h5", question_id="q", climatological_base_rate=0.55243,
                          threshold=0.1694, horizon_business_days=5,
                          target="rv_exceedance", as_of="2026-09-09")
    fields = set(vars(target))
    for forbidden in FORBIDDEN_CELL_FIELDS:
        assert forbidden not in fields, f"배선 산출이 모델 필드 {forbidden} 을 실어 나르면 안 된다"
    lines = " ".join(target.display_lines())
    assert "기후" in lines and "모델 예측이 아니다" in lines
    assert "공식 확률은 LLM rN" in lines


def test_wiring_module_reads_eligibility_from_the_contract_not_a_literal() -> None:
    """자격 목록을 코드에 박으면 계약이 바뀌어도 코드가 안 따라간다."""
    source = (ROOT / "src/ai_fc/vol_base_rate_wiring.py").read_text(encoding="utf-8")
    assert "holdout_pass_cells" in source and "wiring_eligible_cells" in source
    assert '"rv_h5", "rv_h21"' not in source, "자격 셀을 리터럴로 박으면 안 된다"


def test_manual_reference_class_quantity_is_allowed_as_free_text() -> None:
    """등록 12건 중 8건은 base_rates·예측 파일에서 온 수동 참조클래스다 — 축이 자유 문자열이어야 한다."""
    from ai_fc.sigma_supply import MANUAL, SigmaQuote, adopt
    q = SigmaQuote(value=1.463, unit="%p", quantity="earnings_surprise_pct_nvda_total_revenue",
                   path=MANUAL, source="data/base_rates/earnings.md NVDA 9분기",
                   available_at="2026-07-08", method="표본표준편차")
    decision = adopt("earnings_surprise_pct_nvda_total_revenue", [q])
    assert decision.adopted is q and not decision.cross_checks


def test_two_conditionings_of_one_path_are_refused() -> None:
    """'전체기간 σ' 와 '2010+ σ' 는 두 경로가 아니라 한 경로의 두 파라미터다.

    큰 쪽을 고르게 두면 조건화 쇼핑이 된다 — 실제로 나스닥 종점 수익률은
    전체 0.0971 · 2010+ 0.0772 로 26% 벌어지고, 어느 쪽을 고르느냐로 z 가 1.37 ~ 1.73 을 오간다.
    """
    from ai_fc.sigma_supply import SigmaSupplyError, TERMINAL_LOG_RETURN, adopt, load_store, reference_class_sigma
    store = load_store(ROOT)
    whole = reference_class_sigma(store, "NASDAQCOM", TERMINAL_LOG_RETURN,
                                  horizon_business_days=H87, conditioning="전체기간")
    since2010 = reference_class_sigma(store, "NASDAQCOM", TERMINAL_LOG_RETURN,
                                      horizon_business_days=H87, since="2010-01-01",
                                      conditioning="2010년 이후")
    assert whole.value > since2010.value  # 조건화가 σ 를 26% 움직인다
    with pytest.raises(SigmaSupplyError) as exc:
        adopt(TERMINAL_LOG_RETURN, [whole, since2010])
    assert "조건화 쇼핑" in str(exc.value)


def test_empty_quantity_declaration_is_refused() -> None:
    from ai_fc.sigma_supply import SigmaSupplyError, adopt
    with pytest.raises(SigmaSupplyError) as exc:
        adopt("  ", [])
    assert "무슨 양을 묻는지" in str(exc.value)


def test_every_prereg_question_declares_its_sigma_quantity_and_path() -> None:
    """σ 가 무슨 양을 어느 경로로 쟀는지가 없으면 T03 규칙으로 감사할 수 없다."""
    import yaml
    from ai_fc.sigma_supply import EVENT_PROBABILITY

    data = yaml.safe_load((ROOT / "questions/registry.yaml").read_text(encoding="utf-8"))
    prereg = [q for q in data["questions"] if isinstance(q.get("prereg"), dict)]
    assert len(prereg) == 12, f"prereg 블록을 가진 질문이 12건이 아니다: {len(prereg)}"
    for q in prereg:
        pre = q["prereg"]
        for key in ("sigma", "sigma_source", "sigma_quantity", "sigma_path"):
            assert str(pre.get(key) or "").strip(), f"{q['id']} 의 prereg.{key} 가 비어 있다"
        assert pre["sigma_quantity"] != EVENT_PROBABILITY, f"{q['id']} 이 확률을 σ 로 선언했다"
    paths = {q["prereg"]["sigma_path"] for q in prereg}
    assert paths <= {"reference_class", "v8_quantiles", "manual_reference_class"}, paths
    assert "v13_vol_cells" not in paths, "V13 셀은 σ 를 공급하지 않는다"


def test_a_quantity_mismatched_quote_is_reported_not_silently_dropped() -> None:
    """조용히 버리면 '두 경로를 봤다'는 인상만 남고 무엇이 왜 빠졌는지가 사라진다."""
    from ai_fc.sigma_supply import (SigmaQuote, TERMINAL_LOG_RETURN, WINDOW_MAX,
                                    adopt, supply_lines)
    ref = SigmaQuote(value=6.553, unit="index_points", quantity=WINDOW_MAX,
                     path="reference_class", source="x", available_at="2026-08-06", method="IQR")
    v8 = SigmaQuote(value=0.0812, unit="log_return", quantity=TERMINAL_LOG_RETURN,
                    path="v8_quantiles", source="y", available_at="2026-09-04", method="IQR")
    decision = adopt(WINDOW_MAX, [ref, v8])
    assert decision.adopted is ref
    assert [d.path for d in decision.dropped] == ["v8_quantiles"]
    joined = " ".join(supply_lines(decision))
    assert "제외 v8_quantiles" in joined and "양이 다르다" in joined
