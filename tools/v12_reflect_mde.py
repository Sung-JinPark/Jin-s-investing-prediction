#!/usr/bin/env python
"""tools/v12_reflect_mde.py — S2-2 쌍대 비교의 부트스트랩 SE·MDE 발췌 (읽기 전용, stdout 만).

S4-2 게이트 산술 입력용. 여기서 새 통계를 만들지 않고 저장된 CI 블록의 se/mde 를 뽑기만 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / "data/timeseries_v12/diagnostics/reflection_baseline.json")
               .read_text(encoding="utf-8"))


def line(tag: str, block: dict) -> None:
    c = block.get("ci90")
    if not c:
        print(f"  {tag:52s} —")
        return
    print(f"  {tag:52s} Δ={block['loss_diff']:+.6f} se={c['bootstrap_se']:.6f} "
          f"mde50={c['mde50']:.6f} CI90=[{c['ci90_lower']:+.6f},{c['ci90_upper']:+.6f}]")


def main() -> None:
    for h in ("21", "63"):
        b = D["per_horizon"][h]
        print(f"== h{h} (base={b['base_rate']:.5f}, 기후 BS={b['brier']['climatology_insample']:.6f})")
        for k, v in b["paired"].items():
            line(k, v)
        for k in ("discrete_monitoring_bgk", "ewma_lambda_v8_selected_per_origin", "drift_mu_hat"):
            line(f"v8_vs_{k}", b["variants"][k]["paired_v8_vs_variant"])
            if "paired_variant_vs_climatology" in b["variants"][k]:
                line(f"{k}_vs_climatology", b["variants"][k]["paired_variant_vs_climatology"])
        clim = b["brier"]["climatology_insample"]
        for tag, block, bs_ref in (
            ("2Φ(λ=.97) 원식", b["paired"]["v8_vs_reflection"], b["brier"]["reflection"]),
            ("BGK 이산보정판", b["variants"]["discrete_monitoring_bgk"]["paired_v8_vs_variant"],
             b["variants"]["discrete_monitoring_bgk"]["brier"]),
        ):
            se = block["ci90"]["bootstrap_se"]
            need = 1.645 * se
            bs_target = bs_ref - need               # 후보 모델이 내려가야 하는 Brier
            print(f"  → {tag} 기준선(BS={bs_ref:.6f}, BSS={1 - bs_ref / clim:+.4f})을 "
                  f"CI90 하한>0 으로 이기려면: 손실차 > 1.645·se ≈ {need:.6f} → "
                  f"후보 BS < {bs_target:.6f} → 기후 대비 BSS ≥ {1 - bs_target / clim:+.4f} "
                  f"(se 를 후보 모델에서도 같다고 본 근사)")
        bgk = b["variants"]["discrete_monitoring_bgk"]["brier"]
        print(f"  → 참고: BGK 기준선 BS={bgk:.6f} (기후 대비 BSS={1 - bgk / clim:+.4f}), "
              f"V8 BS={b['brier']['v8_first_touch']:.6f} "
              f"(BSS={b['skill']['bss_v8_vs_climatology']:+.4f})")


if __name__ == "__main__":
    main()
