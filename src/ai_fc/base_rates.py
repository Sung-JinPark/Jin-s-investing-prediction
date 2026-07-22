"""base_rates 다이제스트 — 예측 파이프라인 프롬프트 주입용 (Outside view 보조).

앵커링 방지 (설계 원칙): 질문별 ML 매핑 참조 확률은 **절대 포함하지 않는다**.
포함하면 LLM의 rN 확률이 ML 값에 앵커링되어 divergence 트리거(15%p 괴리 감지)가
자기 자신을 무력화한다. 여기서는 분위수 밴드·감성·GBM 파라미터·시장내재확률 같은
'원재료'만 준다. (시장내재확률은 슈퍼포캐스팅 절차상 정당한 외부 앵커라 예외.)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .db import queries
from .ml.history import iter_history
from .ml.mapping import QUESTION_MAPS


def ml_digest(root: Path, conn: sqlite3.Connection, question_id: str,
              max_chars: int = config.BASE_RATES_DIGEST_MAX_CHARS) -> str | None:
    """질문 1개용 정량 참조 다이제스트 (하위 호환 래퍼 — 메타는 ml_digest_with_meta)."""
    return ml_digest_with_meta(root, conn, question_id, max_chars)[0]


def _latest_fresh_run(root: Path, kind: str) -> dict | None:
    """해당 kind의 최신 run — 신선도(ML_REF_MAX_AGE_DAYS) 통과분만. 없으면 None."""
    latest = None
    for run in iter_history(root):
        if run.get("kind") == kind:
            latest = run  # append 순서 = 시간순 → 마지막이 최신
    if latest is None:
        return None
    try:
        run_ts = datetime.fromisoformat(latest["run_ts"])
    except (KeyError, ValueError):
        return None
    if datetime.now() - run_ts > timedelta(days=config.ML_REF_MAX_AGE_DAYS):
        return None
    return latest


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _format_context(run: dict) -> list[str]:
    """dualdb context run → 원재료 라인. **질문 매핑 확률 없음** (R-4).

    전방수익률·조정 깊이는 시장 전체 과거 base rate이지 질문별 확률이 아니다.
    F1/F3 지평과 겹치므로 준-앵커 주의 라벨을 명시한다.
    """
    lines: list[str] = []
    a = run.get("analog")
    if a and a.get("fwd_return_dist"):
        fr = a["fwd_return_dist"]
        depth = a.get("correction_depth_median")
        depth_s = "" if depth is None else f" · 유사 조정 깊이 중앙값 {_pct(depth)}"
        sel = "·".join(a.get("selected_eras", []))
        lines.append(
            f"- [아날로그] 현 상태 최근접 과거 사이클: {a.get('closest_era')}"
            f"(거리 {a.get('distance')}) · 유사 국면 이후 3/6/12M 수익률 중앙값 "
            f"{_pct(fr.get('m3'))}/{_pct(fr.get('m6'))}/{_pct(fr.get('m12'))} "
            f"(풀 {a.get('n_eras')}시대·선택 {sel}·n={fr.get('n')}){depth_s} "
            f"— **매핑 확률 아님, 과거 base rate 참조(R-4 준-앵커 주의)**")
    ft = run.get("factor_tilt")
    if ft and any(ft.get(k) is not None for k in ("value_z", "momentum_z", "size_z")):
        z = lambda x: "—" if x is None else f"{x:+.2f}"  # noqa: E731
        lines.append(
            f"- [팩터 기울기 {ft.get('vintage', '?')}] 최근 12M z — 가치(HML) "
            f"{z(ft.get('value_z'))}·모멘텀(Mom) {z(ft.get('momentum_z'))}·"
            f"사이즈(SMB) {z(ft.get('size_z'))}")
    rg = run.get("regime")
    if rg:
        parts = []
        if "yield_curve_10y2y" in rg:
            inv = " 역전" if rg.get("yield_curve_inverted") else ""
            parts.append(f"금리커브 10Y-2Y {rg['yield_curve_10y2y']:+.2f}%p{inv}")
        if "hy_spread_pct" in rg:
            parts.append(f"HY 스프레드 {rg['hy_spread_pct']:.2f}% "
                         f"({rg.get('hy_spread_pctile')}%ile·n={rg.get('hy_spread_n')})")
        if "cape_latest" in rg:
            parts.append(f"CAPE {rg['cape_latest']}({rg.get('cape_pctile')}%ile, "
                         f"빈티지 {rg.get('cape_vintage')})")
        if parts:
            lines.append("- [레짐] " + " · ".join(parts))
    return lines


def ml_digest_with_meta(root: Path, conn: sqlite3.Connection, question_id: str,
                        max_chars: int = config.BASE_RATES_DIGEST_MAX_CHARS
                        ) -> tuple[str | None, dict | None]:
    """(다이제스트 원문, 입력 출처 메타) — WS4 재현성 스냅샷용.

    메타는 "그 시점에 무엇을 보고 판단했나"의 좌표: ml·context 실행 시각·시장내재 출처.
    다이제스트 원문 자체는 evidence 파일에 전문 첨부되고 해시가 frontmatter에 남는다.
    ml 블록과 dualdb context 블록은 독립 — 각자 신선도 게이트를 통과할 때만 주입된다.
    """
    ml = _latest_fresh_run(root, "ml")
    ctx = _latest_fresh_run(root, "context")

    lines: list[str] = []
    mi = None
    if ml is not None:
        lines.append(
            f"(오픈웨이트 자동 산출 {ml['run_ts'][:10]} — base rate 참조, 매매 신호 아님)")
        qm = next((m for m in QUESTION_MAPS if m.question_id == question_id), None)
        bands: dict = ml.get("series_bands", {})
        targets = ([(qm.series_key, bands[qm.series_key])]
                   if qm and qm.series_key in bands else list(bands.items()))
        for _, b in targets:
            try:
                t = b["terminal"]
                lines.append(
                    f"- {b['symbol']} {b['horizon_weeks']}주 zero-shot 분위수(모델 중앙값 결합): "
                    f"중앙값 {t['q50']:,.0f} ({b['median_pct']:+.1%}), "
                    f"80% 밴드 [{t['q10']:,.0f}, {t['q90']:,.0f}] · 현재 {b['last_value']:,.0f}")
                g = b.get("gbm")
                if g:
                    lines.append(f"  · GBM(52주) 주간 μ {g['mu_w']:+.4f} · σ {g['sigma_w']:.4f}")
            except (KeyError, TypeError):
                continue
        overall = ml.get("sentiment_overall")
        if overall is not None:
            deltas = [d for s in ml.get("sentiment", [])
                      if (d := queries.sentiment_delta(conn, s["feed"])) is not None]
            d_txt = f" (Δ7d {sum(deltas) / len(deltas):+.3f})" if deltas else ""
            lines.append(f"- 뉴스 감성 종합(FinBERT) {overall:+.3f}{d_txt} — 동행~후행 지표")
        mi = queries.latest_market_implied(conn, question_id, config.MARKET_REF_MAX_AGE_DAYS)
        if mi:
            lines.append(f"- 시장내재확률({mi[1]}, 수집 {mi[2]}): {mi[0]:.0%}"
                         f" — risk-neutral·프록시 가정 주의")

    ctx_lines = _format_context(ctx) if ctx is not None else []
    if ctx_lines:
        if not lines:  # ml 부재 시에도 context 단독 주입 (헤더 부여)
            lines.append("(dualdb 아날로그·팩터·레짐 컨텍스트 — base rate 참조, 매매 신호 아님)")
        lines.extend(ctx_lines)

    if len(lines) <= 1:
        return None, None
    meta = {
        "ml_run_ts": ml["run_ts"] if ml else None,
        "context_run_ts": ctx["run_ts"] if ctx else None,
        "ml_history_file": "data/ml_history/",
        "market": f"{mi[1]}@{mi[2]}" if mi else None,
    }
    return "\n".join(lines)[:max_chars], meta


_VINTAGE_RE = None


def scan_stale_base_rates(root: Path, max_age_days: int) -> list[tuple[str, str]]:
    """수동 base rate 파일의 빈티지 검사 — (파일명, 최신 수집일) 목록 반환.

    AUDIT-260715 D-5: 자동 파이프라인은 수동 base rate를 주입하지 않지만
    P0 스킬 경로(/forecast)가 로드하므로, '수집일:' 표기가 전부 N일 이상
    경과한 파일을 경고 대상으로 표시한다 (경고만 — 차단 아님, 결정 8-4 대기).
    """
    global _VINTAGE_RE
    import re
    if _VINTAGE_RE is None:
        _VINTAGE_RE = re.compile(r"수집일:\s*(\d{4}-\d{2}-\d{2})")
    stale: list[tuple[str, str]] = []
    cutoff = (datetime.now() - timedelta(days=max_age_days)).date().isoformat()
    d = root / "data" / "base_rates"
    if not d.exists():
        return stale
    for path in sorted(d.glob("*.md")):
        if path.name.endswith("_auto.md"):
            continue  # 자동 산출본은 생성일 기반 신선도 게이트가 별도 존재
        dates = _VINTAGE_RE.findall(path.read_text(encoding="utf-8"))
        if dates and max(dates) < cutoff:
            stale.append((path.name, max(dates)))
    return stale
