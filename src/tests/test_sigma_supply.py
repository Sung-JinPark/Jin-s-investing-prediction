"""T03 — σ 공급과 V13 base rate 배선을 고정한다.

수치 트랙이 게이트에 기여할 수 있는 유일한 합법 경로는 **산포 공급**이다. 확률 결합은
8-8 이 금지한다. 그 경계가 코드에서 흐려지지 않도록, 여기서 세 가지를 못박는다:
σ 는 질문이 묻는 **같은 양**에서만 나온다 · V8 의 방향 필드는 읽지 않는다 ·
미검증 셀은 배선되지 않는다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: 정규화 저장소는 날짜가 박힌 정적 스냅샷(2026-08-06)이라 거기서 나온 재현값은 고정해도
#: 된다. V8 산출(`multivariate_v8_latest.json`)은 다르다 — 섀도 워크플로가 다시 쓰므로
#: 거기서 나온 값은 **규칙으로** 단언한다.
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
    """σ 를 **규칙**으로 단언한다 — 값을 박지 않는다.

    이전에는 `== approx(0.08117)` 이었다. 그 숫자는 V8 섀도 산출
    (`multivariate_v8_latest.json`)에서 나오는데, 그 파일은 timeseries-v8-shadow
    워크플로가 정기적으로 다시 쓴다. 모듈 자신의 caveat 가 이미 "σ 가 모델과 함께
    움직인다"고 말하고 있었는데 시험은 움직이지 않는다고 가정했다 — 실력과 무관하게
    깨지는 단언이다. 실제로 2026-09-15 섀도 갱신에서 0.08117 → 0.07513 으로 움직여
    main 을 빨갛게 만들었다.

    고정할 값어치가 있는 것은 숫자가 아니라 **어느 지평의 분위수 간격을 어떻게
    환산하는가**다. 그건 아티팩트가 갱신돼도 변하지 않는다.
    """
    import json
    from ai_fc.sigma_supply import IQR_TO_SIGMA, V8_RELATIVE, v8_sigma
    raw = json.loads((ROOT / V8_RELATIVE).read_text(encoding="utf-8"))
    if not raw.get("horizons"):
        pytest.skip("V8 operational HOLD artifact intentionally omits forecast horizons")
    node = raw["horizons"]["63"]     # 87 에 가장 가까운 V8 산출 지평
    expected = ((float(node["p75"]) - float(node["p25"])) / IQR_TO_SIGMA)         * math.sqrt(H87 / 63)
    quote = v8_sigma(ROOT, horizon_business_days=H87)
    assert quote.value == pytest.approx(expected, rel=1e-12)
    assert quote.horizon_business_days == H87
    # 단위가 틀리면(퍼센트 vs 로그수익률) 규칙 단언은 통과하고 값만 100배 어긋난다.
    assert 0.0 < quote.value < 1.0
    assert f"horizons.63" in quote.source and "IQR" in quote.source
    assert any("지평 환산" in c for c in quote.caveats)
    assert any("섀도" in c for c in quote.caveats)


def test_both_paths_agree_within_an_order_on_nasdaq(store) -> None:
    """양이 같은 두 경로가 크게 어긋나면 그 자체가 경보다."""
    import json
    from ai_fc.sigma_supply import TERMINAL_LOG_RETURN, adopt, reference_class_sigma, v8_sigma
    from ai_fc.sigma_supply import V8_RELATIVE
    raw = json.loads((ROOT / V8_RELATIVE).read_text(encoding="utf-8"))
    if not raw.get("horizons"):
        pytest.skip("V8 operational HOLD artifact intentionally omits forecast horizons")
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

#: 계약 CELL_ORDER 와 같은 아홉 셀 — 합성 스코어보드의 항목 순서.
_V13_CELLS = ("vix25_h5", "vix25_h21", "vix25_h63", "vix30_h5", "vix30_h21", "vix30_h63",
              "rv_h5", "rv_h21", "rv_h63")
_V13_CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v13_vol.yaml")
_V13_RESOLUTIONS_RELATIVE = Path("data/timeseries_v13/ledgers/vol_live_resolutions.jsonl")


def _board(blocked: dict[str, list[str]], *, cells: tuple[str, ...] = _V13_CELLS) -> dict:
    """`live_scoreboard.projection` 모양의 합성 스코어보드 — `blocked` 에 든 셀만 claim_blocked."""
    return {"cells": [{"cell": c, "matured": 0, "claim_blocked": c in blocked,
                       "claim_block_reasons": list(blocked.get(c, []))} for c in cells],
            "claim_restriction": {"min_events": 20, "min_episodes": 5}}


def _patch_board(monkeypatch: pytest.MonkeyPatch, board: dict) -> None:
    from ai_fc.timeseries_v13 import live_scoreboard
    monkeypatch.setattr(live_scoreboard, "projection", lambda root, **kw: board)


def _v13_root(tmp_path: Path) -> Path:
    """실제 V13 계약을 그대로 복사한 임시 저장소 — 원장·레지스트리·산출은 테스트가 채운다."""
    dst = tmp_path / _V13_CONTRACT_RELATIVE
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes((ROOT / _V13_CONTRACT_RELATIVE).read_bytes())
    return tmp_path


def _resolution_rows(cell: str, pattern: list[float], *, base: float = 0.42) -> list[dict]:
    """라벨 패턴 순서대로 고유 원점을 찍은 해상 행 — resolved_session 은 origin 과 같아 순서가 보존된다."""
    rows = []
    for d, label in enumerate(pattern):
        origin = f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}"
        p = 0.8 if label == 1.0 else 0.1
        rows.append({"schema_version": 1, "resolution_id": f"v13vol-{origin}-test-{cell}",
                     "run_id": f"v13vol-{origin}-test", "cell": cell, "origin": origin,
                     "horizon_sessions": 5, "resolved_session": origin, "probability": p, "label": label,
                     "brier_model": round((p - label) ** 2, 8), "brier_climatology": round((base - label) ** 2, 8),
                     "climatology_base_rate": base, "coefficients_sha256": "c" * 64,
                     "finalist_id": "V13VOL_champion_aec80c65038b", "holdout_status_at_forecast": "partial",
                     "knowledge_cutoff": "2026-10-01T00:00:00+00:00"})
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_latest(root: Path, cells: dict[str, dict]) -> None:
    """셀 산출 JSON — 이 파일이 없으면 `wiring_targets` 는 자격 검사에 닿기 전에 빈 목록을 낸다."""
    from ai_fc.vol_base_rate_wiring import LATEST_RELATIVE
    latest = root / LATEST_RELATIVE
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"as_of": "2026-10-22", "cells": cells}), encoding="utf-8")


def test_wiring_is_fail_closed_with_zero_targets() -> None:
    """자격 셀은 있으나 대응 질문이 없다(또는 라이브 라벨로 차단) — 아무것도 표시하지 않는다."""
    from ai_fc.vol_base_rate_wiring import contract_eligible_cells, eligible_cells, wiring_status, wiring_targets
    assert set(contract_eligible_cells(ROOT)) == {"rv_h5", "rv_h21"}, "계약의 배선 자격 셀이 바뀌었다"
    assert wiring_targets(ROOT) == []
    status = wiring_status(ROOT)
    assert status["scoreboard_error"] is None, "실제 저장소의 라이브 스코어보드는 읽혀야 한다"
    # 라이브 라벨은 집계 시점의 누적값이라 날마다 바뀐다 — 두 셀의 행방은 항등식으로만 고정한다
    assert set(status["eligible_cells"]) | set(status["blocked_by_claim_restriction"]) == {"rv_h5", "rv_h21"}
    assert set(status["eligible_cells"]).isdisjoint(status["blocked_by_claim_restriction"])
    assert tuple(status["eligible_cells"]) == eligible_cells(ROOT)
    assert status["targets"] == 0 and status["fail_closed"] is True
    if status["eligible_cells"]:
        assert "대응 등록 질문이 없다" in status["reason"]
    else:
        assert "판정불가(제한)" in status["reason"]


def test_unverified_cell_cannot_be_wired() -> None:
    """홀드아웃 실패 셀(vix25_h63)·국면 미달 셀(vix25_h21)은 지도에 넣어도 거부된다."""
    from ai_fc.vol_base_rate_wiring import VolWiringError, wiring_targets
    for cell in ("vix25_h63", "vix25_h21", "vix30_h21", "rv_h63"):
        with pytest.raises(VolWiringError) as exc:
            wiring_targets(ROOT, cell_question_map={cell: "vix-25-90d"})
        assert "배선 자격이 없다" in str(exc.value)


def test_wiring_refuses_a_question_that_is_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """레지스트리 검사는 자격 검사 뒤에 온다 — 2026-10-22 현재 전 셀이 라이브 차단이라 라벨을 걷어내야 닿는다."""
    from ai_fc.vol_base_rate_wiring import VolWiringError, wiring_targets
    _patch_board(monkeypatch, _board({}))
    with pytest.raises(VolWiringError) as exc:
        wiring_targets(ROOT, cell_question_map={"rv_h5": "no-such-question"})
    assert "레지스트리에 없다" in str(exc.value)


def test_claim_blocked_cell_loses_wiring_eligibility_and_an_unblocked_one_keeps_it(tmp_path: Path) -> None:
    """V13-D13 `live_claim_restriction` scope 4항 — 계약 자격이 있어도 판정불가(제한) 셀은 배선 자격이 없다.

    합성 해상 원장으로 실제 `live_scoreboard.projection` 을 통과시킨다: rv_h5 는 사건 0·국면 1 로 차단,
    rv_h21 은 사건 30·국면 6/6 으로 라벨이 없다.
    """
    from ai_fc.vol_base_rate_wiring import (VolWiringError, contract_eligible_cells, eligibility,
                                            eligible_cells, wiring_status, wiring_targets)
    root = _v13_root(tmp_path)
    assert set(contract_eligible_cells(root)) == {"rv_h5", "rv_h21"}
    _write_jsonl(root / _V13_RESOLUTIONS_RELATIVE,
                 _resolution_rows("rv_h5", [0.0] * 25) + _resolution_rows("rv_h21", ([1.0] * 5 + [0.0] * 5) * 6))
    _write_latest(root, {"rv_h5": {"clim_base_rate": 0.3, "theta": 0.1694, "h": 5, "target": "rv_exceedance"},
                         "rv_h21": {"clim_base_rate": 0.4, "theta": 0.1694, "h": 21, "target": "rv_exceedance",
                                    "p": 0.9}})

    assert eligible_cells(root) == ("rv_h21",)
    info = eligibility(root)
    assert info["contract_eligible_cells"] == ["rv_h21", "rv_h5"]
    assert info["blocked_by_claim_restriction"] == ["rv_h5"]
    assert info["claim_block_reasons"] == {"rv_h5": ["events<20", "episodes<5"]}
    assert info["scoreboard_error"] is None

    # 차단 셀을 지도에 넣으면 거부되고, 스코어보드 사유가 메시지에 그대로 실린다
    with pytest.raises(VolWiringError) as exc:
        wiring_targets(root, cell_question_map={"rv_h5": "rv-test-q"})
    assert "배선 자격이 없다" in str(exc.value)
    assert "판정불가(제한): events<20, episodes<5" in str(exc.value)

    # 라벨 없는 셀은 끝까지 배선된다 — 나가는 것은 기후 기저율뿐, 모델 p 는 실리지 않는다
    (root / "questions").mkdir()
    (root / "questions/registry.yaml").write_text("version: 1\nquestions:\n- id: rv-test-q\n", encoding="utf-8")
    targets = wiring_targets(root, cell_question_map={"rv_h21": "rv-test-q"})
    assert [t.cell for t in targets] == ["rv_h21"]
    assert targets[0].climatological_base_rate == 0.4 and targets[0].horizon_business_days == 21

    status = wiring_status(root)
    assert status["eligible_cells"] == ["rv_h21"] and status["blocked_by_claim_restriction"] == ["rv_h5"]
    assert status["claim_block_reasons"]["rv_h5"] == ["events<20", "episodes<5"]
    assert "대응 등록 질문이 없다" in status["reason"], "CELL_QUESTION_MAP 이 비어 있으니 자격 셀이 있어도 0건"


def test_unreadable_scoreboard_blocks_every_cell_with_a_reason(tmp_path: Path) -> None:
    """라벨을 모르면 자격도 없다 — 스코어보드 판독 실패는 전 셀 차단(페일클로즈)이고 사유가 남는다."""
    from ai_fc.vol_base_rate_wiring import VolWiringError, eligible_cells, wiring_status, wiring_targets
    root = _v13_root(tmp_path)
    ledger = root / _V13_RESOLUTIONS_RELATIVE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{this is not json\n", encoding="utf-8")
    _write_latest(root, {"rv_h21": {"clim_base_rate": 0.4, "theta": 0.1694, "h": 21, "target": "rv_exceedance"}})

    assert eligible_cells(root) == ()
    status = wiring_status(root)
    assert status["contract_eligible_cells"] == ["rv_h21", "rv_h5"], "계약 자격은 스코어보드와 무관하게 읽힌다"
    assert status["eligible_cells"] == []
    assert status["blocked_by_claim_restriction"] == ["rv_h21", "rv_h5"]
    assert status["scoreboard_error"] and "JSONDecodeError" in status["scoreboard_error"]
    for cell in ("rv_h21", "rv_h5"):
        assert status["claim_block_reasons"][cell][0].startswith("scoreboard_unreadable: JSONDecodeError")
    assert status["fail_closed"] is True and "스코어보드를 읽지 못해" in status["reason"]
    with pytest.raises(VolWiringError) as exc:
        wiring_targets(root, cell_question_map={"rv_h21": "rv-test-q"})
    assert "scoreboard_unreadable" in str(exc.value)


def test_malformed_or_partial_scoreboard_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """항목에 claim_blocked 불리언이 없으면 해석 실패(전 셀 차단), 셀 항목이 빠지면 그 셀만 라벨 불명으로 차단."""
    from ai_fc.vol_base_rate_wiring import eligibility, eligible_cells

    _patch_board(monkeypatch, _board({}))
    assert set(eligible_cells(ROOT)) == {"rv_h5", "rv_h21"}, "라벨이 전혀 없으면 계약 자격이 그대로 자격이다"

    _patch_board(monkeypatch, {"cells": [{"cell": c} for c in _V13_CELLS]})
    info = eligibility(ROOT)
    assert info["eligible_cells"] == [] and info["blocked_by_claim_restriction"] == ["rv_h21", "rv_h5"]
    assert "claim_blocked" in (info["scoreboard_error"] or "")

    _patch_board(monkeypatch, _board({}, cells=tuple(c for c in _V13_CELLS if c != "rv_h21")))
    info = eligibility(ROOT)
    assert info["eligible_cells"] == ["rv_h5"] and info["scoreboard_error"] is None
    assert info["claim_block_reasons"] == {"rv_h21": ["scoreboard_missing_cell"]}


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
