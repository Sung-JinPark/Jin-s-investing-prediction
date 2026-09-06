#!/usr/bin/env python
"""tools/v12_probe_counts.py — 본문 인용 수치 대사용 카운트 (읽기 전용, stdout 만)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    data = json.loads((ROOT / "docs/review/lowcost_options.json").read_text(encoding="utf-8"))
    a = data["A_v10_combination_grid"]
    singles = [s for s in a["singles"] if not s["identical_to_e0"]]
    bad = [s["label"] for s in singles if s.get("gfc_delta_share_interpretable") is False]
    print(f"단독 실험(Δ≠0) {len(singles)}개 중 견인비중 해석불가 {len(bad)}개: {bad}")

    adm = a["admissible_grid"]
    over1 = [c for c in adm if c["relative_improvement"] > 0.01]
    print(f"적격 조합 {len(adm)}개 · 상대개선>+1% {len(over1)}개 · "
          f"그중 CI90 하한>0 {sum(1 for c in over1 if c['ci90_lower_positive'])}개")
    print("  상대개선 범위(>1%):",
          f"{min(c['relative_improvement'] for c in over1):.5f} ~ {max(c['relative_improvement'] for c in over1):.5f}")
    print("  GFC 견인 범위(>1%):",
          f"{min(c['gfc_delta_share'] for c in over1):.4f} ~ {max(c['gfc_delta_share'] for c in over1):.4f}")
    print("  상위5% 제거 후 평균 최소(>1%):",
          f"{min(c['top5pct']['mean_after_removal'] for c in over1):.3e}")
    print("  적격 12조합 중 제거 후 CI90 하한>0 개수:",
          sum(1 for c in adm if c["top5pct"].get("ci90_lower_positive_after_removal")))
    print("  적격 12조합 중 후반창 CI90 하한>0:",
          [("+".join(m.replace("V10_", "") for m in c["members"]), round(c["relative_improvement"], 5))
           for c in adm if c.get("post2010_ci90_lower_positive")])
    for c in adm:
        if c["members"] == ["V10_W3_gamma_m010", "V10_W4a_isotonic"]:
            print("  W3_m010+W4a 제거 후 평균:", f"{c['top5pct']['mean_after_removal']:.3e}",
                  "CI90:", [f"{x:.3e}" for x in c["top5pct"]["ci90_after_removal"]])

    c3 = data["C_track_combination"]
    print("V11 recenter 성분 평균:", f"{c3['profiles']['v11_recenter']['mean_delta']:.6e}",
          "rel:", f"{c3['profiles']['v11_recenter']['relative_improvement']:.5f}")
    print("champion post2010_n:", c3["profiles"]["v10_champion"]["post2010_n"],
          "gfc_origin_share:", c3["profiles"]["v10_champion"]["gfc_origin_share"])

    b = data["B_v11_low_momentum_conditional"]
    lm = b["low_mom_tertile"]
    h63 = [x for x in lm["cells_detail"] if x["horizon"] == 63]
    print(f"low_mom h63 셀 {len(h63)}개 · 전부 악화 = {all(x['improvement_mean'] < 0 for x in h63)}")


if __name__ == "__main__":
    main()
