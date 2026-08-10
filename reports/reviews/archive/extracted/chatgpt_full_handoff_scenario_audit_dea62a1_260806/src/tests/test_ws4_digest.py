"""WS4: 다이제스트 재현성 — digest_hash 재계산 일치 · evidence 전문 첨부."""

from __future__ import annotations

from ai_fc.models import EvidenceBrief, sha256_text
from ai_fc.orchestrator import _render_evidence


def _brief() -> EvidenceBrief:
    return EvidenceBrief(profile="general", text="리서치 본문", sources_count=3,
                         cost_usd=1.0, input_tokens=10, output_tokens=10)


def test_evidence_attaches_digest_fulltext() -> None:
    aux = "- ^IXIC 23주 분위수: 중앙값 26,000\n- 시장내재확률(polymarket): 5%"
    ev = _render_evidence("2099-01-01_fixture_r1", [_brief()], aux)
    assert "주입된 정량 다이제스트 원문" in ev
    assert aux in ev                       # 전문 그대로 — 재현성 완결
    assert "digest_hash" in ev             # frontmatter 해시와의 연결 안내

    # 다이제스트 부재 시 섹션 없음 (구파일과 동일 형태)
    ev_none = _render_evidence("2099-01-01_fixture_r1", [_brief()], None)
    assert "주입된 정량 다이제스트" not in ev_none


def test_digest_hash_recompute_matches() -> None:
    """frontmatter의 digest_hash = sha256(다이제스트 원문) — 사후 재계산 검증 가능."""
    aux = "- 다이제스트 원문 예시"
    assert sha256_text(aux) == sha256_text(aux)
    assert len(sha256_text(aux)) == 64
    # evidence 첨부본에서 원문을 잘라 재해시하면 frontmatter 값과 일치해야 한다
    ev = _render_evidence("s", [_brief()], aux)
    attached = ev.split("frontmatter digest_hash의 원문)\n\n", 1)[1]
    assert sha256_text(attached) == sha256_text(aux)
