"""C5 캘리브레이션 프로그램 상태 — 원장·레지스트리·예측 파일에서 **파생**해 인쇄한다.

    PYTHONUTF8=1 python tools/c5_status.py

규율 (설계도 §10.1 — MTS 의 tools/roadmap_status.py 와 동일 형):
- 읽기 전용. 어떤 파일도 쓰지 않는다.
- 스케줄 금지. 세션 시작 시 사람이 1회 돌린다.
- 페일클로즈: 파일·필드 부재는 '알 수 없음'이 아니라 **미종료**로 보고한다.
- 상태를 손으로 적는 파일을 만들지 않는다 — 낡은 상태 파일은 잘못된 다음 행동을 부른다.

게이트 판정의 정본은 SQLite 뷰 `v_gate_status` 다. 이 도구는 같은 산술을 원천 파일에서
재계산한 **거울**이며, DB 가 빌드돼 있으면 대사 결과를 함께 인쇄한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc import c5_certificate as C5  # noqa: E402


def _fmt(value: float | None, spec: str = ".4f", dash: str = "—") -> str:
    return dash if value is None else format(value, spec)


def main() -> int:
    r = C5.report(ROOT)
    gate, sharp = r["gate"], r["sharpness"]

    print("=" * 72)
    print("C5 캘리브레이션 프로그램 상태 — 설계도 docs/design/c5_calibration_program_blueprint_v1_260909.md")
    print("=" * 72)

    # ── 게이트 ────────────────────────────────────────────────────
    p3 = "통과" if gate["gate_p3"] else "미달"
    p2 = "통과" if gate["gate_p2"] else "미달"
    print(f"\n[게이트]  문항 {gate['n_questions']}/50 · primary Brier {_fmt(gate['brier'])} "
          f"(행 {gate['n_rows_primary']}, 제외 {gate['n_excluded']})")
    print(f"          P2(30/0.20) {p2} · P3(50/0.18) {p3}")
    if r["crosscheck"]:
        print(f"          DB 대사: {r['crosscheck']}")
    else:
        print("          DB 대사: 인덱스 미빌드 (sync --rebuild 로 생성 가능 — 정본은 뷰)")
    if gate["n_rows_primary"] < 30:
        print("          ⚠ 표본 30 미만 — 통계적으로 미성숙. 모든 수치는 참고용.")

    # ── 예리도 (D2) ───────────────────────────────────────────────
    if sharp.get("rows"):
        rows = sharp["rows"]
        verdict = "임계 초과 — 완전 캘리브레이션에서도 미달" if rows["mean_pq"] >= 0.18 else "임계 이하"
        print(f"\n[예리도]  행 평균 p(1-p) = {rows['mean_pq']:.4f} (임계 0.18) → {verdict}")
        print(f"          n={rows['n']}행 · 결손 {rows['deficit']:+.4f}")
        if sharp.get("latest_round"):
            print(f"          최신 회차 기준 {sharp['latest_round']['mean_pq']:.4f} "
                  f"(n={sharp['latest_round']['n']}문항)")
        rf = sharp.get("reforecast")
        if rf:
            print(f"          재예측 예리화: {rf['first']:.4f} → {rf['latest']:.4f} "
                  f"({rf['delta']:+.4f}) · {rf['sharpened']}/{rf['n']}문항 개선")
        for target in (0.10, 0.12, 0.15, 0.17):
            need = C5.required_new_rows(rows["deficit"], target)
            label = "불가(∞)" if need is None else f"{need}행"
            print(f"            신규 평균 p(1-p)={target:.2f} → 필요 {label}")

    # ── 독립성 (D3) ───────────────────────────────────────────────
    ess, essr = r["ess"], r["ess_registry"]
    print(f"\n[독립성]  해소 표본: 명목 {ess['nominal']} · ESS 하한 {ess['ess_lower']:.1f}")
    print(f"          레지스트리 전체: 명목 {essr['nominal']} · ESS 하한 {essr['ess_lower']:.1f}"
          + (f" · 최대 드라이버 점유 {essr['largest_share']:.0%}"
             if essr["largest_share"] else ""))
    clusters = r["diversification"]["clusters"]
    print("          클러스터: " + " · ".join(
        f"{k}={len(v)}" for k, v in sorted(clusters.items(), key=lambda x: -len(x[1]))))
    print("          (ESS 는 클러스터 내 완전 상관 가정의 **하한**이다. 실제는 [하한, 명목] 구간.)")

    # ── 부수 증명서 (§8) ──────────────────────────────────────────
    bss, mu, bs = r["bss"], r["murphy"], r["bootstrap"]
    print(f"\n[증명서]  BSS vs anchor: {_fmt(bss['bss'], '+.4f')} "
          f"(모델 {_fmt(bss['brier_model'])} / anchor {_fmt(bss['brier_anchor'])}, "
          f"n={bss['n']}, anchor 미회수 {bss['missing']})")
    if bss["bss"] is not None and bss["bss"] <= 0:
        print("          ⚠ BSS ≤ 0 — base rate 대비 증분 실력이 측정되지 않았다 (C5-A4 자동 활성화 차단 조건)")
    if mu:
        print(f"          Murphy: REL {mu['reliability']:.4f} · RES {mu['resolution']:.4f} "
              f"· UNC {mu['uncertainty']:.4f}")
    if bs:
        if bs["note"]:
            print(f"          클러스터 부트스트랩: {bs['note']}")
        else:
            print(f"          클러스터 부트스트랩 CI90: "
                  f"[{bs['ci_lo']:.4f}, {bs['ci_hi']:.4f}] · 클러스터 {bs['n_clusters']}개")
    print("          (전부 표시 계층 — 게이트 판정에 다리를 놓지 않는다.)")

    # ── 큐 ────────────────────────────────────────────────────────
    q = r["queues"]
    over = q["resolve_overdue"]
    print(f"\n[큐]      해소 대기 {len(over)}건" + (
        f" (최장 {over[0]['days']}일 경과)" if over else ""))
    for item in over[:8]:
        flag = " ⚠SLA" if item["sla_breach"] else ""
        print(f"            - {item['id']:<34} 기한 {item['deadline']} · {item['days']}일{flag}")
    print(f"          첫 예측 미실행 {len(q['never_forecast'])}건"
          + (": " + ", ".join(q["never_forecast"][:6]) if q["never_forecast"] else ""))

    # ── 경로·예산 ─────────────────────────────────────────────────
    print("\n[경로]    " + " · ".join(f"{k} n={v}" for k, v in sorted(r["paths"].items())))
    print("          (claude_code 경로는 cost_log.csv 에 계측되지 않는다 — 0 이 아니라 '모름')")

    # ── 분산 규칙 위반 ────────────────────────────────────────────
    viol = r["diversification"]["violations"]
    if viol:
        print(f"\n[분산위반] {len(viol)}건")
        for v in viol:
            print(f"            - {v}")
    else:
        print("\n[분산위반] 없음")

    # ── 단계 ──────────────────────────────────────────────────────
    print("\n[단계]")
    current = None
    for st in r["stages"]:
        mark = "완료" if st.done else "미종료"
        print(f"            [{mark}] {st.name:<14} {st.detail}")
        if current is None and not st.done:
            current = st
    if current:
        print(f"\n[다음]    {current.name} — {current.detail}")
    else:
        print("\n[다음]    전 단계 완료")

    # ── ML 층위 관측 (ML 설계도 §8) ────────────────────────────────
    ml = r["ml"]
    ex = ml["extremization"]
    if ex:
        verdict = ("판정 가능" if ex["sufficient"]
                   else f"표본 미달 ({ex['n']}/{ex['min_sample']}) — 판정하지 않는다")
        print(f"\n[ML]      M1 extremization: 기준 {ex['base']:.4f} · {verdict}")
        for item in ex["grid"]:
            mark = " ← 최적" if item["alpha"] == ex["best_alpha"] else ""
            print(f"            α={item['alpha']:.3f} → {item['brier']:.4f} "
                  f"({item['delta']:+.4f}){mark}")
        mu = r["murphy"]
        if mu:
            # 1차 증거는 위 격자(실측)다. REL/RES 는 보조 진단일 뿐 판정 다리가 아니다 —
            # 둘이 어긋나면 격자를 믿고, 어긋났다는 사실 자체를 인쇄한다.
            heuristic_ok = mu["reliability"] <= mu["resolution"]
            grid_ok = ex["best_alpha"] > 1.0
            note = "격자와 일치" if heuristic_ok == grid_ok else "**격자와 불일치 — 격자를 따른다**"
            print(f"            보조 진단: REL {mu['reliability']:.4f} "
                  f"{'<=' if heuristic_ok else '>'} RES {mu['resolution']:.4f} · {note}")
    cov = ml["shadow_coverage"]
    print(f"          관측 채널 커버리지: shadow_extremized {cov['written']}/{cov['total']} 예측")
    dec = ml["deciles"]
    print("          M5 십분위 빈: " + " ".join(
        f"{i*10}s={n}" for i, n in sorted(dec.items())))
    filled = sum(1 for n in dec.values() if n >= 10)
    print(f"            10건 이상 채워진 빈 {filled}/10 · isotonic 게이트(해소 100+)까지 "
          f"{max(0, 100 - r['gate']['n_rows_primary'])}행")
    pw = ml["pairwise"]
    print(f"          M6 쌍대 표본: 벤치마크 {pw['rows']}행 · ML 동반 {pw['with_ml']} · "
          f"시장 동반 {pw['with_market']} · 3자 {pw['all_three']}")

    pre = r["prereg"]
    print("[사전등록] " + ("승인 " + str(pre.get("approved")) + " · " + pre.get("prereg_id", "")
                          if pre else "**부재 — Q2 미종료 (페일클로즈)**"))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
