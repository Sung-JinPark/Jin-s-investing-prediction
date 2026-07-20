"""AUDIT-260715 시정 검증 — Q4(역산 재현)·D-5(빈티지 경보)·Q15(rebuild 가드)·T-3(태그)."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_fc.base_rates import scan_stale_base_rates
from ai_fc.db import ingest
from ai_fc.ml.chronos_fc import QuantileForecast


# ── Q4/T-6: 밴드 역산 재현 — 앵커링 방지의 실효 한계를 수치로 고정 ──

def test_band_reverse_engineering_recovers_hidden_prob() -> None:
    """2026-07-15 실측 밴드 5점만으로 감춘 F3 매핑 확률이 근사 복원됨을 문서화.

    이 테스트는 '방어 성공'이 아니라 **한계의 실측 기록**이다: 임계값이 밴드
    내부에 있으면 선형 보간만으로 매핑 확률과 10%p 이내로 수렴한다 (04 #23 갱신 근거).
    """
    # ml_auto.md 2026-07-15 실측 종점 분위수 (앙상블 결합 밴드)
    bands = {"q10": 23842.0, "q25": 25501.0, "q50": 27101.0, "q75": 28632.0, "q90": 30096.0}
    fc = QuantileForecast(symbol="^IXIC", context_len=186, horizon=24,
                          quantiles={k: [v] for k, v in bands.items()}, last_value=26107.01)
    reconstructed = fc.prob_above(26206.89)   # F3 임계 — 밴드 내부
    hidden_mapped = 0.66                       # 같은 날 기록된 F3 앙상블 매핑 확률
    gap = abs(reconstructed - hidden_mapped)
    assert gap <= 0.10, (
        f"역산 {reconstructed:.2f} vs 매핑 {hidden_mapped:.2f} — 괴리 {gap:.2f}. "
        "10%p를 넘으면 04 #23의 '근사 복원' 서술을 재검토할 것")


# ── D-5/T-2: 수동 base rate 빈티지 경보 ──

def test_vintage_scan_flags_stale_manual_base_rates(tmp_path: Path) -> None:
    d = tmp_path / "data" / "base_rates"
    d.mkdir(parents=True)
    old = (datetime.now() - timedelta(days=30)).date().isoformat()
    fresh = datetime.now().date().isoformat()
    (d / "stale.md").write_text(f"내용 (수집일: {old})", encoding="utf-8")
    (d / "fresh.md").write_text(f"내용 (수집일: {fresh})", encoding="utf-8")
    (d / "mixed.md").write_text(f"a (수집일: {old})\nb (수집일: {fresh})", encoding="utf-8")
    (d / "quant_auto.md").write_text(f"자동 (수집일: {old})", encoding="utf-8")  # 자동본 제외
    (d / "no_dates.md").write_text("수집일 표기 없음", encoding="utf-8")

    stale = scan_stale_base_rates(tmp_path, max_age_days=7)
    names = {n for n, _ in stale}
    assert names == {"stale.md"}  # mixed는 최신 수집일 기준으로 신선


# ── Q15/T-5: rebuild 침묵 재기준화 차단 ──

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 사상 최고가를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공"
        resolution_source: "가공"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        action_link: "테스트"
        status: active
        created: 2099-06-01
""")

FORECAST_MD = textwrap.dedent("""\
    ---
    forecast_id: 2099-06-10_fixture-coin-ath_r1
    question_id: fixture-coin-ath
    timestamp: 2099-06-10 09:00 KST
    phase: P1
    model: fixture-model
    prompt_version: reasoning_core_v1
    probability: 40
    ci80: [25, 55]
    research_status: failed
    ---
    본문
""")

LEDGER = "resolved_date,question_id,forecast_id,forecast_date,probability,outcome,brier,domain,notes\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    fdir = tmp_path / "forecasts" / "2099"
    fdir.mkdir(parents=True)
    (fdir / "2099-06-10_fixture-coin-ath_r1.md").write_text(FORECAST_MD, encoding="utf-8")
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration" / "ledger.csv").write_text(LEDGER, encoding="utf-8")
    return tmp_path


def test_rebuild_precheck_blocks_silent_rebaseline(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    assert ingest.sync(conn, repo).ok

    target = repo / "forecasts" / "2099" / "2099-06-10_fixture-coin-ath_r1.md"
    target.write_text(FORECAST_MD.replace("probability: 40", "probability: 90"),
                      encoding="utf-8")  # 변조 시뮬레이션

    report = ingest.sync(conn, repo, rebuild=True)          # force 없음 → 중단
    assert not report.ok
    assert any("E1" in e for e in report.errors)
    assert any("rebuild 중단" in e for e in report.errors)

    report2 = ingest.sync(conn, repo, rebuild=True, force=True)  # 명시적 force → 경고와 함께 진행
    assert report2.ok
    assert any("force 재기준화" in w for w in report2.warnings)


def test_hash_anchor_written(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    anchor = repo / "forecasts" / ".hashes"
    assert anchor.exists()
    line = anchor.read_text(encoding="utf-8").strip()
    assert "forecasts/2099/2099-06-10_fixture-coin-ath_r1.md" in line


# ── T-3: research_status 골격 (기본 동작 무변화) ──

def test_research_status_parsed_and_views_exist(repo: Path) -> None:
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    row = conn.execute(
        "SELECT research_status FROM forecasts WHERE forecast_id LIKE '%fixture-coin-ath%'"
    ).fetchone()
    assert row["research_status"] == "failed"
    conn.execute("SELECT * FROM v_brier_all").fetchall()
    conn.execute("SELECT * FROM v_brier_primary").fetchall()


def test_primary_excludes_failed_and_override(repo: Path) -> None:
    """8-2(c): failed(frontmatter)와 메타 오버라이드가 primary·게이트에서 제외됨.

    원장은 전량 기록(투명) — v_brier_all n=2, v_brier_primary n=0.
    """
    # 정상 예측 1건 추가 (research_status 없음 → ok 취급)
    fdir = repo / "forecasts" / "2099"
    clean = FORECAST_MD.replace("fixture-coin-ath_r1", "fixture-coin-ath_r2") \
                       .replace("research_status: failed\n", "")
    (fdir / "2099-06-11_fixture-coin-ath_r2.md").write_text(clean, encoding="utf-8")
    # 두 건 모두 원장에 채점 (append-only)
    ledger = repo / "calibration" / "ledger.csv"
    ledger.write_text(LEDGER
        + "2099-06-20,fixture-coin-ath,2099-06-10_fixture-coin-ath_r1,2099-06-10,40,0,0.16,fixture,\n"
        + "2099-06-20,fixture-coin-ath,2099-06-11_fixture-coin-ath_r2,2099-06-11,40,0,0.16,fixture,\n",
        encoding="utf-8")
    # r2(정상)를 메타 오버라이드로 failed 소급 판정 (파일 무수정 경로 검증)
    (repo / "calibration" / "research_status_overrides.csv").write_text(
        "forecast_id,status,reason,decided_at\n"
        "2099-06-11_fixture-coin-ath_r2,failed,테스트 소급 판정,2099-06-21\n",
        encoding="utf-8")

    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)

    n_all = conn.execute("SELECT n FROM v_brier_all WHERE domain='(전체)'").fetchone()["n"]
    n_pri = conn.execute("SELECT n FROM v_brier_primary WHERE domain='(전체)'").fetchone()["n"]
    assert n_all == 2       # 전량 채점 유지 (투명)
    assert n_pri == 0       # r1은 frontmatter failed, r2는 오버라이드 failed — 둘 다 제외
    gate = conn.execute("SELECT n_resolved FROM v_gate_status").fetchone()
    gate_all = conn.execute("SELECT n_resolved FROM v_gate_status_all").fetchone()
    assert gate["n_resolved"] == 0 and gate_all["n_resolved"] == 2  # 게이트는 primary 기준


# ── RE-AUDIT U-2: overrides 원장급 규율 ──

def test_override_e4_post_resolution_gaming_detected(repo: Path) -> None:
    """해소일 이후 생성된 override = 결과 인지 후 소급 제외 — E4로 검출."""
    ledger = repo / "calibration" / "ledger.csv"
    ledger.write_text(LEDGER
        + "2099-06-20,fixture-coin-ath,2099-06-10_fixture-coin-ath_r1,2099-06-10,40,0,0.16,fixture,\n",
        encoding="utf-8")
    (repo / "calibration" / "research_status_overrides.csv").write_text(
        "forecast_id,status,reason,created_at\n"
        "2099-06-10_fixture-coin-ath_r1,failed,사후 소급 시도,2099-06-25\n",  # 해소 후!
        encoding="utf-8")
    conn = ingest.connect(repo / "db" / "index.db")
    report = ingest.sync(conn, repo)
    assert any("E4" in e for e in report.errors)


def test_override_e4_pre_resolution_ok(repo: Path) -> None:
    """해소 전 생성 override는 정상 (r2 케이스 유형)."""
    ledger = repo / "calibration" / "ledger.csv"
    ledger.write_text(LEDGER
        + "2099-06-20,fixture-coin-ath,2099-06-10_fixture-coin-ath_r1,2099-06-10,40,0,0.16,fixture,\n",
        encoding="utf-8")
    (repo / "calibration" / "research_status_overrides.csv").write_text(
        "forecast_id,status,reason,created_at\n"
        "2099-06-10_fixture-coin-ath_r1,failed,해소 전 판정,2099-06-12\n",
        encoding="utf-8")
    conn = ingest.connect(repo / "db" / "index.db")
    report = ingest.sync(conn, repo)
    assert not any("E4" in e for e in report.errors)


def test_override_e5_tamper_detected(repo: Path) -> None:
    """override 행 변조·축소 = E5 (append-only 규율)."""
    ov = repo / "calibration" / "research_status_overrides.csv"
    ov.write_text("forecast_id,status,reason,created_at\n"
                  "2099-06-10_fixture-coin-ath_r1,degraded,최초 판정,2099-06-12\n",
                  encoding="utf-8")
    conn = ingest.connect(repo / "db" / "index.db")
    assert ingest.sync(conn, repo).ok
    ov.write_text("forecast_id,status,reason,created_at\n"
                  "2099-06-10_fixture-coin-ath_r1,failed,몰래 변경,2099-06-12\n",
                  encoding="utf-8")  # 행 변조
    report = ingest.sync(conn, repo)
    assert any("E5" in e for e in report.errors)


def test_lppl_demotion_gate_embedded_in_renderer() -> None:
    """RE-AUDIT U-1: 보정 tc의 비활성화 라벨이 quant 렌더 템플릿에 코드로 내장 —
    문서 시정이 아니라 재실행 침식 불가 게이트인지 소스 계약 검증."""
    import inspect

    from ai_fc.quant import runner
    src = inspect.getsource(runner)
    i_corr = src.find("보정 t_c")
    i_label = src.find("[비활성화 — DECISIONS 8-7]")
    assert i_corr != -1 and i_label != -1
    assert 0 < i_label - i_corr < 500  # 라벨이 보정값 표기에 인접(같은 블록)


# ── ARCHITECTURE 배관 (8-9): 섀도 extremization · K회 중앙값 ──

def test_shadow_extremize_display_only_math() -> None:
    """σ(√3·logit(p)) — 0.5 불변·단조·1~99 클램프. 표시 전용 열의 수학 계약."""
    from ai_fc.orchestrator import _extremize
    assert _extremize(50) == 50                      # hedging 중립점 불변
    assert _extremize(62) > 62 and _extremize(38) < 38  # 0.5에서 멀어지는 방향
    assert _extremize(99) <= 99 and _extremize(1) >= 1  # 클램프
    assert _extremize(70) == 100 - _extremize(30)    # 대칭


def test_krun_median_fixed_rule(monkeypatch) -> None:
    """KRunMedian: K회 결과의 고정 중앙값 + divergence=(max-min)/100. LLM 무호출 모킹."""
    from types import SimpleNamespace

    from ai_fc import aggregator as agg_mod

    probs = iter([40, 55, 48])
    def fake_reasoning(*a, **kw):
        p = next(probs)
        return SimpleNamespace(probability=p, ci80_lo=p - 10, ci80_hi=p + 10), None
    monkeypatch.setattr(agg_mod, "run_reasoning", fake_reasoning)

    out = agg_mod.KRunMedian(3).estimate(None, None, [], None, None, None, None)
    assert out.probability == 48                     # median(40,55,48)
    assert out.runs == [40, 55, 48]
    assert out.divergence == pytest.approx(0.15)
    assert out.result.probability == 48              # 대표 = 중앙값 최근접 실행


def test_domain_skill_dual_basis_view(repo: Path) -> None:
    """v_domain_skill이 primary/all 양쪽 컬럼을 제공하고 질의 가능."""
    conn = ingest.connect(repo / "db" / "index.db")
    ingest.sync(conn, repo)
    rows = conn.execute("SELECT domain, n, n_primary, blocked FROM v_domain_skill").fetchall()
    assert rows is not None  # 스키마 계약 — 컬럼 존재
