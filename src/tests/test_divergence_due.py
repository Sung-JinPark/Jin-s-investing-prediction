"""P1.7-S4: divergence due 트리거 테스트 — 합성 미래 질문만 (백테스트 금지)."""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

from ai_fc.db.queries import MlRef
from ai_fc.registry import compute_due, load_registry

NOW = datetime(2099, 6, 15, 9, 0)

REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    updated: 2099-06-01
    questions:
      - id: fixture-coin-ath
        title: "픽스처코인 ATH"
        question: "픽스처코인이 2099-12-31까지 사상 최고가를 경신할 확률은?"
        deadline: 2099-12-31
        resolution: "YES = 가공 거래소 종가 신고가"
        resolution_source: "가공 거래소"
        domain: fixture
        cadence: "주 1회"
        schedule:
          - per_week: 1
        action_link: "테스트"
        status: active
        created: 2099-06-01
""")


def _questions(tmp_path: Path):
    p = tmp_path / "registry.yaml"
    p.write_text(REGISTRY_YAML, encoding="utf-8")
    return load_registry(p)


def _due_kinds(questions, latest_probs, ml_refs):
    last = {"fixture-coin-ath": NOW}  # 재예측 due가 안 뜨게 최근 예측으로 고정
    due = compute_due(questions, last, {}, set(), NOW,
                      latest_probs=latest_probs, ml_refs=ml_refs)
    return [d for d in due if d.kind == "divergence"]


def test_divergence_boundary_15pp(tmp_path: Path) -> None:
    qs = _questions(tmp_path)
    ref = {"fixture-coin-ath": MlRef(prob=0.50, run_ts=NOW)}
    assert _due_kinds(qs, {"fixture-coin-ath": 64}, ref) == []      # 14%p < 15
    hit = _due_kinds(qs, {"fixture-coin-ath": 65}, ref)              # 15%p = 경계 → 발동
    assert len(hit) == 1 and "15%p" in hit[0].reason
    assert _due_kinds(qs, {"fixture-coin-ath": 66}, ref)             # 16%p → 발동
    assert "자동 실행 안 함" in hit[0].reason


def test_divergence_low_confidence_excluded(tmp_path: Path) -> None:
    qs = _questions(tmp_path)
    ref = {"fixture-coin-ath": MlRef(prob=0.20, run_ts=NOW, low_confidence=True)}
    assert _due_kinds(qs, {"fixture-coin-ath": 80}, ref) == []  # 60%p 괴리라도 불일치 게이트


def test_divergence_absent_inputs_no_regression(tmp_path: Path) -> None:
    """옵션 인자 없이 호출하면 기존 4종 kind만 — 하위 호환."""
    qs = _questions(tmp_path)
    due = compute_due(qs, {"fixture-coin-ath": NOW}, {}, set(), NOW)
    assert all(d.kind in ("forecast", "resolve", "manual-review", "stale") for d in due)


def test_divergence_missing_ref_or_prob(tmp_path: Path) -> None:
    qs = _questions(tmp_path)
    assert _due_kinds(qs, {}, {"fixture-coin-ath": MlRef(0.5, NOW)}) == []
    assert _due_kinds(qs, {"fixture-coin-ath": 80}, {}) == []
