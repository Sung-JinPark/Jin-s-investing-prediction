"""ML 참조 채점 원장(ML_M4_REFERENCE_SCORING) — 합성 run·합성 아카이브(monkeypatch)만.

라이브 전진 채점 모듈의 계약: 성숙 전 거부(아카이브 거래일 인덱스), 멱등(append_unique),
pre_registration 플래그·요약 제외, Brier 분수 단위, content_hash, SOXX 미채점 기록,
행 키 충돌 금지. 백테스트가 아니다 — 모든 값은 가공이다.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc import files as F
from ai_fc.ml import reference_scoring as RS
from ai_fc.ml.history import append_run
from ai_fc.timeseries_v8.contracts import canonical_hash

ROOT = Path(__file__).resolve().parents[2]
REGISTERED = date(2026, 10, 21)   # 계약 registered — 변경 시 계약도 같이 바뀐다

REGISTRY = textwrap.dedent("""\
    version: 1
    questions:
      - id: fx-terminal
        title: "픽스처 종점"
        question: "픽스처 종점?"
        deadline: 2026-12-31
        resolution: "YES = 종가 > 100"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        status: active
        created: 2026-07-01
      - id: fx-rolling
        title: "픽스처 롤링"
        question: "픽스처 롤링?"
        deadline: rolling-90d
        resolution: "YES = 터치"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        status: active
        created: 2026-07-01
""")


class _Obs:
    def __init__(self, series_id: str, day: str, value: float):
        self.series_id, self.observation_time, self.value = series_id, day, value


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _archive(last: date, value: float = 110.0, vix: float = 20.0) -> list[_Obs]:
    """start 부터 last 까지 평일 세션 — NASDAQCOM 은 value, VIX 는 vix 로 고정."""
    days = [d for d in _weekdays(date(2026, 6, 1), 400) if d <= last]
    out: list[_Obs] = []
    for d in days:
        out.append(_Obs("NASDAQCOM", d.isoformat(), value))
        out.append(_Obs("VIX", d.isoformat(), vix))
    return out


def _run(run_ts: str, *, prob_ens: float = 0.6, prob_gbm: float = 0.5, h: int = 4,
         tail: float | None = None) -> dict:
    fc_rows = [
        {"question_id": "fx-terminal", "model": "ensemble", "kind": "terminal",
         "prob": prob_ens, "threshold": 100.0, "horizon_weeks": h, "detail": {}},
        {"question_id": "fx-terminal", "model": "gbm", "kind": "terminal",
         "prob": prob_gbm, "threshold": 100.0, "horizon_weeks": h, "detail": {}},
        {"question_id": "fx-rolling", "model": "ensemble", "kind": "path_touch",
         "prob": 0.3, "threshold": 25.0, "horizon_weeks": h, "detail": {}},
    ]
    if tail is not None:
        fc_rows.append({"question_id": "fx-terminal", "model": "c2", "kind": "terminal",
                        "prob": 0.55, "threshold": 100.0, "horizon_weeks": h, "detail": {},
                        "prob_tail_c2": tail})
    return {
        "run_ts": run_ts, "kind": "ml", "forecasts": fc_rows, "sentiment": [],
        "series_bands": {
            "q_ixic": {"symbol": "^IXIC", "horizon_weeks": h, "last_value": 100.0,
                       "terminal": {"q10": 90.0, "q25": 95.0, "q50": 100.0, "q75": 105.0, "q90": 120.0},
                       "median_pct": 0.0, "gbm": {"mu_w": 0.0, "sigma_w": 0.02}},
            "q_vix": {"symbol": "^VIX", "horizon_weeks": h, "last_value": 18.0,
                      "terminal": {"q10": 14.0, "q25": 16.0, "q50": 18.0, "q75": 21.0, "q90": 26.0},
                      "median_pct": 0.0, "gbm": {"mu_w": 0.0, "sigma_w": 0.1}},
            "q_soxx": {"symbol": "SOXX", "horizon_weeks": h, "last_value": 500.0,
                       "terminal": {"q10": 400.0, "q25": 450.0, "q50": 500.0, "q75": 550.0, "q90": 600.0},
                       "median_pct": 0.0, "gbm": {"mu_w": 0.0, "sigma_w": 0.05}},
        },
        "sentiment_overall": None,
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "questions").mkdir(parents=True)
    (root / "questions" / "registry.yaml").write_text(REGISTRY, encoding="utf-8")
    (root / "calibration").mkdir()
    (root / "calibration" / "ledger.csv").write_text(",".join(F.LEDGER_HEADER) + "\n", encoding="utf-8")
    (root / "data" / "contracts").mkdir(parents=True)
    shutil.copy(ROOT / RS.CONTRACT_RELATIVE, root / RS.CONTRACT_RELATIVE)
    return root


def _ledger_row(root: Path, qid: str, forecast_date: str, outcome: int, resolved: str) -> None:
    F.append_ledger_row(root / "calibration" / "ledger.csv", {
        "resolved_date": resolved, "question_id": qid,
        "forecast_id": f"{forecast_date}_{qid}_r1", "forecast_date": forecast_date,
        "probability": 50, "outcome": outcome, "brier": 0.25, "domain": "fixture", "notes": "가공",
    })


def _now(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 0, tzinfo=timezone.utc)


def _ledger(root: Path) -> list[dict]:
    p = root / RS.LEDGER_RELATIVE
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l] if p.is_file() else []


# ── 성숙 전 거부 ───────────────────────────────────────────────────

def test_immature_rows_are_not_scored(repo: Path, monkeypatch) -> None:
    run_ts = "2026-11-02T10:00:00"           # 월요일 → 주 금요일 11-06 + 4주 = 목표 12-04
    append_run(repo, _run(run_ts, h=4))
    monkeypatch.setattr(RS, "read_market_observations",
                        lambda root, knowledge_cutoff=None: _archive(date(2026, 12, 3)))
    res = RS.resolve_reference(repo, now=_now(date(2026, 12, 3)))
    assert res["appended"] == 0 and res["rows"] == []
    reasons = {p["reason"] for p in res["pending"]}
    assert "immature" in reasons                     # 아카이브가 목표 세션에 못 닿음 — 달력이 아니라 인덱스
    assert "no_ledger_resolution" in reasons         # 질문 결과 없음 — 원장 외 추정 금지
    assert not (repo / RS.LEDGER_RELATIVE).exists()


# ── 성숙 뒤 채점·단위·해시·멱등 ───────────────────────────────────

def test_matured_rows_scored_idempotent_and_hashed(repo: Path, monkeypatch) -> None:
    run_ts = "2026-11-02T10:00:00"
    append_run(repo, _run(run_ts, h=4, tail=0.7))
    _ledger_row(repo, "fx-terminal", "2026-11-03", 1, "2026-12-31")
    monkeypatch.setattr(RS, "read_market_observations",
                        lambda root, knowledge_cutoff=None: _archive(date(2026, 12, 4), value=110.0, vix=20.0))
    res = RS.resolve_reference(repo, now=_now(date(2026, 12, 5)))
    rows = _ledger(repo)
    assert res["appended"] == len(rows) > 0

    q = {r["model"]: r for r in rows if r["kind"] == "question_prob" and r["question_id"] == "fx-terminal"}
    assert set(q) == {"ensemble", "gbm", "c2"}
    assert q["ensemble"]["prob"] == 0.6 and q["ensemble"]["realized"] == 1
    assert q["ensemble"]["brier"] == pytest.approx((0.6 - 1) ** 2)        # 분수 단위 — 퍼센트 아님
    assert q["ensemble"]["baseline_prob"] == 0.5 and q["ensemble"]["baseline_brier"] == pytest.approx(0.25)
    assert q["c2"]["prob_tail_c2"] == 0.7 and q["c2"]["brier_tail_c2"] == pytest.approx(0.09)
    assert q["ensemble"]["pre_registration"] is False                        # run_ts ≥ 등록일
    assert q["ensemble"]["outcome_source"] == "ledger:2026-11-03_fx-terminal_r1"

    # rolling 질문은 원장에 맞는 창이 없어 보류 — 결과를 지어내지 않는다
    assert not any(r.get("question_id") == "fx-rolling" for r in rows)
    assert any(p["reason"] == "no_ledger_resolution" and p["question_id"] == "fx-rolling"
               for p in res["pending"])

    s = {r["series"]: r for r in rows if r["kind"] == "series_band"}
    ixic = s["q_ixic"]
    assert ixic["archive_series"] == "NASDAQCOM" and ixic["status"] == "scored"
    assert ixic["target_session"] == "2026-12-04" and ixic["realized_session"] == "2026-12-04"
    assert ixic["realized"] == 110.0 and ixic["coverage_p10_p90"] == 1
    # pinball: q50=100, y=110, τ=0.5 → 5.0 ; q90=120 → (0.9−1)(110−120)=1.0 ; q10=90 → 0.1·20=2.0
    assert ixic["pinball"]["q50"] == pytest.approx(5.0)
    assert ixic["pinball"]["q90"] == pytest.approx(1.0)
    assert ixic["pinball"]["q10"] == pytest.approx(2.0)
    assert ixic["crps_5q"] == pytest.approx(2 * ixic["pinball_mean"])
    assert ixic["pinball_mean_rel"] == pytest.approx(ixic["pinball_mean"] / 100.0)
    assert ixic["baseline_gbm"]["model"] == "gbm" and "crps_5q" in ixic["baseline_gbm"]
    assert s["q_vix"]["archive_series"] == "VIX" and s["q_vix"]["realized"] == 20.0
    assert s["q_soxx"]["status"] == RS.UNRESOLVABLE and s["q_soxx"]["realized"] is None
    assert "pinball" not in s["q_soxx"]

    # content_hash = canonical_hash(본문 − content_hash) · 금지 키 없음
    for r in rows:
        body = {k: v for k, v in r.items() if k != "content_hash"}
        assert r["content_hash"] == canonical_hash(body)
        assert not any(k in r for k in RS.FORBIDDEN_ROW_KEYS)

    # 멱등 — 재실행은 0행 append, 파일 불변
    before = (repo / RS.LEDGER_RELATIVE).read_bytes()
    res2 = RS.resolve_reference(repo, now=_now(date(2026, 12, 6)))
    assert res2["appended"] == 0 and res2["rows"] == []
    assert (repo / RS.LEDGER_RELATIVE).read_bytes() == before
    assert b"\r\n" not in before                                             # newline="\n"


# ── pre_registration 플래그·요약 제외 ─────────────────────────────

def test_pre_registration_flag_and_summary_exclusion(repo: Path, monkeypatch) -> None:
    append_run(repo, _run("2026-07-20T13:47:46", h=4, prob_ens=0.9))   # 등록 전 run
    append_run(repo, _run("2026-11-02T10:00:00", h=4, prob_ens=0.6))   # 등록 후 run
    _ledger_row(repo, "fx-terminal", "2026-11-03", 1, "2026-12-31")
    monkeypatch.setattr(RS, "read_market_observations",
                        lambda root, knowledge_cutoff=None: _archive(date(2026, 12, 4)))
    RS.resolve_reference(repo, now=_now(date(2026, 12, 5)))
    rows = _ledger(repo)
    pre = [r for r in rows if r["pre_registration"]]
    post = [r for r in rows if not r["pre_registration"]]
    assert pre and post
    assert all(r["run_ts"].startswith("2026-07-20") for r in pre)

    s = RS.summarize(repo)
    assert s["excluded_pre_registration"] == len(pre)
    assert s["question"]["ensemble"]["n"] == 1                      # 등록 후 1행만
    assert s["question"]["ensemble"]["brier_mean"] == pytest.approx(0.16)   # 0.9 행(0.01)은 제외
    assert s["series"]["q_ixic"]["n"] == 1
    assert s["unresolvable"] == 1                                    # SOXX(등록 후) 1행
    text = RS.render_status(s)
    assert "표본 부족" in text and "기록·표시만" in text


# ── 롤링 창 매칭·룩어헤드 ─────────────────────────────────────────

def test_rolling_window_match_and_lookahead_guard(repo: Path) -> None:
    _ledger_row(repo, "fx-rolling", "2026-11-04", 1, "2026-12-01")   # run ±3일 — 같은 창
    _ledger_row(repo, "fx-terminal", "2026-10-01", 0, "2026-10-20")  # run 보다 먼저 해소된 결과
    ledger = F.parse_ledger(repo / "calibration" / "ledger.csv")
    kinds = RS._registry_kinds(repo)
    found, reason = RS.match_outcome("fx-rolling", date(2026, 11, 2), ledger, kinds["fx-rolling"])
    assert reason == "ok" and found["outcome"] == 1
    found, reason = RS.match_outcome("fx-rolling", date(2026, 11, 20), ledger, kinds["fx-rolling"])
    assert found is None and reason == "no_matching_rolling_window"
    found, reason = RS.match_outcome("fx-terminal", date(2026, 11, 2), ledger, kinds["fx-terminal"])
    assert found is None and reason == "run_after_resolution"          # 결과 뒤 산출 행은 만들지 않는다


# ── 결정론 지표 ───────────────────────────────────────────────────

def test_gbm_baseline_quantiles_are_monotone_and_centered() -> None:
    q = RS.gbm_quantiles(100.0, 0.0, 0.02, 4)
    assert q["q50"] == pytest.approx(100.0)
    assert q["q10"] < q["q25"] < q["q50"] < q["q75"] < q["q90"]
    # σ_h = 0.02·√4 = 0.04 → q90 = 100·exp(1.2816·0.04)
    assert q["q90"] == pytest.approx(100.0 * 2.718281828 ** (1.2815515655 * 0.04), rel=1e-6)


def test_target_session_is_friday_anchored() -> None:
    assert RS.target_session(date(2026, 7, 20), 13) == date(2026, 10, 23)   # 월 → 그 주 금 07-24 + 91
    assert RS.target_session(date(2026, 7, 25), 1) == date(2026, 7, 31)     # 토 → 같은 주 금 07-24 + 7


# ── C3 매핑 커버리지 — 기한 정렬 지평·스텝 (러너 순수 함수, 네트워크·모델 없음) ─────

def test_series_horizons_reach_mapped_deadlines() -> None:
    from ai_fc.ml import runner as R
    from ai_fc.ml.mapping import QUESTION_MAPS, QuestionMap

    asof = date(2026, 10, 21)
    default = max(4, min(60, (date(2026, 12, 31) - asof).days // 7))   # 연말 기본 = 10
    hz = R._series_horizons(asof, default)
    # 연말 너머 기한(2027-01-15)이 q_ixic 지평 안에 들어온다 — 이전엔 연말에서 잘렸다
    assert hz["q_ixic"] == R._week_step(asof, date(2027, 1, 15)) + 1 == 12
    assert hz["q_soxx"] == default                                     # 연말 종점만 — 그대로
    assert hz["q_vix"] == R.VIX_ROLLING_WEEKS                          # rolling-90d ≈ 13주, 상한 13
    for qm in QUESTION_MAPS:
        end = qm.end_date
        if end is not None:
            assert R._week_step(asof, date.fromisoformat(end)) <= hz[qm.series_key] - 1

    # 종점 스텝: 12-31 종점은 지평 12 안에서 10번째(인덱스 9) 주 — 1/15 스텝으로 밀리지 않는다
    f3 = next(m for m in QUESTION_MAPS if m.question_id == "nasdaq-eoy-above-jul9-2026")
    assert R._terminal_step(asof, f3, hz["q_ixic"]) == 9
    comp = next(m for m in QUESTION_MAPS if m.question_id == "nasdaq-comp-30000-close-2027-01-15")
    assert R._terminal_step(asof, comp, hz["q_ixic"]) == 11
    # 기한만 있는 경로 질문(F1)은 기한 주까지만 센다 — 지평 확장이 터치 확률을 부풀리지 않는다
    f1 = next(m for m in QUESTION_MAPS if m.question_id == "nasdaq-ath-eoy-2026")
    assert R._path_steps(asof, f1, hz["q_ixic"]) == (0, 9)
    # 명시 window 질문은 기존 _window_steps 규약 그대로 (test_mc_barrier 가 고정)
    f2 = next(m for m in QUESTION_MAPS if m.question_id == "nasdaq-corr10-augoct-2026")
    assert R._path_steps(asof, f2, hz["q_ixic"]) == R._window_steps(asof, f2.window, hz["q_ixic"])
    # 기한·창 없는 rolling 질문은 지평 전체
    assert R._path_steps(asof, QuestionMap("x", "x", "q_vix", 25.0, "above_path"), 13) is None


def test_week_step_is_monday_anchored() -> None:
    from ai_fc.ml import runner as R

    asof = date(2026, 10, 21)                      # 수요일, 주 월요일 10-19
    assert R._week_step(asof, date(2026, 10, 30)) == 0    # 다음 주(10-26) 금요일 → 스텝 0
    assert R._week_step(asof, date(2026, 10, 31)) == 0    # 토요일도 같은 주
    assert R._week_step(asof, date(2026, 12, 31)) == 9
    assert R._week_step(asof, date(2026, 10, 23)) == -1   # 같은 주 — 호출자가 0 으로 클램프


# ── C5 Chronos-2 꼬리 분위수 병기 (모델 로드 없음 — 보간 로직만) ─────────────────

def _qf(vals: dict[str, float], tail: dict[str, float] | None = None):
    from ai_fc.ml.chronos_fc import QuantileForecast

    return QuantileForecast(
        symbol="T", context_len=10, horizon=3,
        quantiles={k: [v] * 3 for k, v in vals.items()}, last_value=100.0,
        tail_quantiles={k: [v] * 3 for k, v in tail.items()} if tail else None)


def test_prob_tail_c2_is_side_by_side_not_replacement() -> None:
    from ai_fc.ml.chronos_fc import LEVELS, LEVELS_C2

    assert LEVELS == [0.1, 0.25, 0.5, 0.75, 0.9]                       # Bolt 공용 레벨 무변경
    assert LEVELS_C2 == [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    five = {"q10": 80.0, "q25": 90.0, "q50": 100.0, "q75": 110.0, "q90": 120.0}
    tail = {"q01": 60.0, "q05": 70.0, **five, "q95": 130.0, "q99": 150.0}
    fc = _qf(five, tail)
    assert fc.prob_above(125.0) == 0.07                                # 기존 캡 유지
    assert fc.prob_above(75.0) == 0.93
    assert fc.prob_above_tail(125.0) == pytest.approx(0.075)           # q90~q95 보간
    assert fc.prob_above_tail(160.0) == 0.01 and fc.prob_above_tail(50.0) == 0.99   # 꼬리 캡
    assert fc.prob_above_tail(100.0) == pytest.approx(fc.prob_above(100.0))        # 공통 구간 일치
    assert fc.prob_above(100.0, step=0) == pytest.approx(0.5)          # 스텝 인자 (C3)
    assert _qf(five).prob_above_tail(100.0) is None                    # Bolt·결합: 꼬리 없음 → None


def test_runner_records_prob_tail_c2_only_for_c2_terminal() -> None:
    from ai_fc.ml import runner as R
    from ai_fc.ml.mapping import QuestionMap

    five = {"q10": 80.0, "q25": 90.0, "q50": 100.0, "q75": 110.0, "q90": 120.0}
    tail = {"q01": 60.0, "q05": 70.0, **five, "q95": 130.0, "q99": 150.0}
    bolt, c2 = _qf(five), _qf(five, tail)
    asof = date(2026, 10, 21)
    qm = QuestionMap("fx", "fx", "q_ixic", 125.0, "above_terminal")
    models, detail = R._model_probs(qm, {"bolt": bolt, "c2": c2}, bolt, {}, asof)
    assert models == {"bolt": 0.07, "c2": 0.07}                        # prob 은 그대로(캡)
    assert detail["prob_tail_c2"] == pytest.approx(0.075)              # 병기 필드만
    below = QuestionMap("fx2", "fx2", "q_ixic", 125.0, "below_terminal")
    _, d2 = R._model_probs(below, {"c2": c2}, bolt, {}, asof)
    assert d2["prob_tail_c2"] == pytest.approx(0.925)
    _, d3 = R._model_probs(qm, {"bolt": bolt}, bolt, {}, asof)
    assert "prob_tail_c2" not in d3                                    # c2 없으면 필드 없음
