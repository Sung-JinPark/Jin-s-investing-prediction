"""tools/v13_guard_mde.py — P0 판정 기계 건전성: 퇴화·에피소드 가드 + 셀별 MDE 실측 (설계창 한정).

왜 필요한가. 외부 검토(2026-09-09)는 "반창별 min(사건,비사건) >= 20" 가드를 제안했는데, 실측하면
9/9 셀이 통과한다(최소 27). 그러나 라벨은 h영업일 전방창으로 만들어 이웃 원점이 겹치므로 사건 수는
유효 표본이 아니다. **연속 국면(run) 수**로 세면 vix30 계열 후반창의 사건 91~151개가 전부 2011년
단일 변동성 국면이다. 이 스크립트는 두 기준을 함께 재고 국면 구간을 명시해, 어떤 셀의 기존 판정이
'한 사건을 여러 번 센 것'인지 드러낸다.

설계창(2007-2014)만 읽는다 — 홀드아웃(2015-2018)·봉인(2019+) 미열람. 새 확률을 만들지 않고
기존 사다리 결과(rung-1/rung-3)의 CI90 폭과 대조만 한다.

    PYTHONUTF8=1 python tools/v13_guard_mde.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_fc.timeseries_v13 import contracts as C  # noqa: E402
from ai_fc.timeseries_v13 import features as F  # noqa: E402
from ai_fc.timeseries_v13 import scoring as S  # noqa: E402
from ai_fc.timeseries_v2.market_archive import read_market_observations  # noqa: E402

SPLIT = "2011-01-01"
MIN_EVENTS = 20        # 외부 검토 제안 — 필요조건이되 충분하지 않다
MIN_EPISODES = 5       # 실측에서 도출한 진짜 구속 조건 (반창×클래스별 독립 국면 수)
OUT = ROOT / "data/timeseries_v13/vol/guard_mde_design.json"


def main() -> int:
    contract = C.load_contract_v13(ROOT)
    frozen_cfg = contract.get("frozen_coefficients") or {}
    C.load_frozen_coefficients(          # 핀 대조만 — 라벨은 계약 표적으로 다시 만든다
        ROOT, expected_sha256=frozen_cfg.get("sha256"),
        expected_content_hash=frozen_cfg.get("content_hash"),
        expected_finalist_id=frozen_cfg.get("finalist_id"))
    panel = F.build_panel(read_market_observations(ROOT),
                          start=C.DESIGN_WINDOW[0], end=C.DESIGN_WINDOW[1])
    dates, vix, rv = panel["dates"], panel["vix"], panel["rv21"]
    early = np.array([str(d) < SPLIT for d in dates])
    late = ~early

    ladder_ewma = json.loads((ROOT / C.LADDER_EWMA_RELATIVE).read_text(encoding="utf-8"))["rungs"]["ewma_logit"]
    ladder_pb = json.loads((ROOT / C.LADDER_PB_RELATIVE).read_text(encoding="utf-8"))["cells"]

    cells: dict[str, dict] = {}
    print(f"{'cell':11s} {'half':6s} {'ev/non':>12s} {'runs ev/non':>12s} {'min_ep':>7s} "
          f"{'MDE':>9s} {'CI90 width':>11s}  verdict")
    for spec in C.cell_specs():
        name = spec["name"]
        if spec["target"] == "vix_touch":
            y = F.labels_vix(vix, spec["K"], spec["h"])
        else:
            y = F.labels_rv(rv, spec["theta"], spec["h"])
        halves = {}
        for half, mask in (("early", early), ("late", late)):
            yy = np.where(mask, y, np.nan)
            report = S.degeneracy_report(yy, min_events=MIN_EVENTS, min_episodes=MIN_EPISODES)
            report["event_spans"] = S.episode_spans(dates, yy, 1.0)[:6]
            direction = "late_to_early" if half == "late" else "early_to_late"
            # rung-1(EWMA) 과 rung-3(PB) 의 같은 방향 CI90 폭 — 국면 희소성과 대조하기 위한 것
            pb_dir = ladder_pb[name]["pb_vs_clim"][direction]
            ew_dir = ladder_ewma[name][direction]
            report["pb_vs_clim"] = {"bss": pb_dir["bss_vs_clim"], "ci90": pb_dir["ci90"],
                                    "ci90_width": pb_dir["ci90"][1] - pb_dir["ci90"][0],
                                    "mde": pb_dir["mde"]}
            report["ewma_vs_clim"] = {"bss": ew_dir["bss_vs_clim"], "ci90": ew_dir["ci90"],
                                      "ci90_width": ew_dir["ci90"][1] - ew_dir["ci90"][0],
                                      "mde": ew_dir["mde"]}
            halves[half] = report
            print(f"{name:11s} {half:6s} {report['events']:5d}/{report['non_events']:<6d} "
                  f"{report['event_runs']:5d}/{report['non_event_runs']:<6d} "
                  f"{report['min_episodes']:7d} {pb_dir['mde']:9.5f} "
                  f"{report['pb_vs_clim']['ci90_width']:11.5f}  {report['verdict']}")
        worst = min(halves.values(), key=lambda r: (r["episodes_ok"], r["min_episodes"]))
        cells[name] = {
            "h": spec["h"], "target": spec["target"],
            **({"K": spec["K"]} if spec["target"] == "vix_touch" else {"theta": spec["theta"]}),
            "halves": halves,
            "counts_ok": all(h["counts_ok"] for h in halves.values()),
            "episodes_ok": all(h["episodes_ok"] for h in halves.values()),
            "verdict": worst["verdict"],
            "champion": (contract["gates"]["champion"]["cells"] or {}).get(name),
        }

    payload = {
        "schema": "v13_guard_mde_design",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": list(C.DESIGN_WINDOW), "split": SPLIT, "n_panel": int(len(dates)),
        "thresholds": {"min_events_per_half_per_class": MIN_EVENTS,
                       "min_episodes_per_half_per_class": MIN_EPISODES},
        "rationale": ("사건 수 가드는 h영업일 전방창의 중첩 때문에 유효 표본을 과대평가한다. "
                      "독립 국면(연속 run) 수가 진짜 구속 조건이다."),
        "sources": {"ladder_ewma": C.LADDER_EWMA_RELATIVE.as_posix(),
                    "ladder_pb": C.LADDER_PB_RELATIVE.as_posix(),
                    "coefficients_sha256": frozen_cfg.get("sha256")},
        "cells": cells,
        "summary": {
            "counts_guard_failures": [k for k, v in cells.items() if not v["counts_ok"]],
            "episode_guard_failures": [k for k, v in cells.items() if not v["episodes_ok"]],
        },
    }
    payload["content_hash"] = C.canonical_hash(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    print(f"\ncounts guard failures  : {payload['summary']['counts_guard_failures'] or 'none'}")
    print(f"episode guard failures : {payload['summary']['episode_guard_failures'] or 'none'}")
    print(f"wrote {OUT.relative_to(ROOT)}  content_hash={payload['content_hash'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
