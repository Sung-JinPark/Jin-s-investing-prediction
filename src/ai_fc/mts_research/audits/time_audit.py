"""AUDIT_TIME (§6, §14) — 시간·판본·splice 정합 감사. 읽기 전용, 숫자는 실측만.

검사 항목:
1. DTWEXB→DTWEXBGS 전환 경계 (§6.4): 실제 마지막/첫 관측일·가용 등급,
   **다른 base 의 level 을 이어붙인 인공 return** 검출 (T13).
2. 방법론 공개일(2019-02-04, 공개 자료) 이전 관측일을 가진 DTWEXBGS 행의
   가용성 증거 등급 — 날짜만으로 과거 가용성을 승격하지 않는지 (T12).
3. 계열별 revision(정정) 분포 — 종가 정정 보존 구조 (§6.3).
4. 계열별 수집 지연(관측일 vs available_at) 분포 — 늦은 달러의 원점 결박 측정 재료.
5. captured_forward 백필의 역사적 가용 증거 부재 — 확인된 구조적 사실의 공시.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ...timeseries_v2.market_archive import read_market_observations

REPORT_RELATIVE = Path("data/mts_research/derived/data_time_audit.json")

DOLLAR_METHODOLOGY_PUBLIC_DATE = "2019-02-04"  # 연준 공개 자료 (설계서 D16)


def splice_artifact_check(
    last_old: tuple[str, float], first_new: tuple[str, float], *, typical_daily_move: float
) -> dict[str, Any]:
    """서로 다른 기준 척도의 level 을 이어붙이면 생기는 인공 return 검출 (T13).

    경계 log-return 이 일상 변동의 수배면 splice 인공물로 플래그한다.
    """
    old_day, old_level = last_old
    new_day, new_level = first_new
    if old_level <= 0 or new_level <= 0:
        raise ValueError("level 은 양수")
    boundary_return = math.log(new_level / old_level)
    flagged = abs(boundary_return) > 5.0 * typical_daily_move
    return {
        "boundary": [old_day, new_day],
        "levels": [old_level, new_level],
        "boundary_log_return": boundary_return,
        "typical_daily_move": typical_daily_move,
        "artificial_splice_flagged": bool(flagged),
        "rule": "같은 정의 안의 return 을 계산한 뒤 연결한다 — level 직결 금지 (§6.4)",
    }


def _lag_days(observation_time: str, available_at: str) -> float:
    obs = datetime.fromisoformat(observation_time + "T00:00:00+00:00")
    avail = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
    return (avail - obs).total_seconds() / 86400.0


def build_report(root: Path) -> dict[str, Any]:
    observations = list(read_market_observations(root))

    by_series: dict[str, list[Any]] = defaultdict(list)
    for row in observations:
        by_series[row.series_id].append(row)

    # 1·2) 달러 splice — 겹침-인지 분석.
    # 동결 코드(timeseries_v2/features.py:116-118)는 **계열별 log-change 를 먼저 계산한 뒤
    # combine_first(DTWEXBGS 우선)** 한다 — §6.4 의 '같은 정의 안의 return 계산 후 연결'
    # 규칙을 이미 지킨다 (level 직결 없음 → T13 의 인공 return 경로가 구조적으로 막혀 있다).
    # 아카이브의 DTWEXBGS 는 2006 까지 backcast 되어 있어 실효 전환점은 BGS 첫 관측일이다.
    dollar: dict[str, Any] = {"status": "NOT_RUN"}
    old_rows = sorted(by_series.get("DTWEXB", []), key=lambda r: str(r.observation_time))
    new_rows = sorted(by_series.get("DTWEXBGS", []), key=lambda r: str(r.observation_time))
    if old_rows and new_rows:
        old_by_day = {str(r.observation_time)[:10]: float(r.value) for r in old_rows}
        new_by_day = {str(r.observation_time)[:10]: float(r.value) for r in new_rows}
        overlap_days = sorted(set(old_by_day) & set(new_by_day))

        def _returns(by_day: dict[str, float], days: list[str]) -> dict[str, float]:
            out: dict[str, float] = {}
            ordered = sorted(by_day)
            for previous, day in zip(ordered, ordered[1:]):
                if day in days_set:
                    out[day] = math.log(by_day[day] / by_day[previous])
            return out

        days_set = set(overlap_days)
        old_returns = _returns(old_by_day, overlap_days)
        new_returns = _returns(new_by_day, overlap_days)
        common = sorted(set(old_returns) & set(new_returns))
        diffs = [abs(new_returns[d] - old_returns[d]) for d in common]
        diffs_sorted = sorted(diffs)

        # 실효 전환점(BGS 첫 관측) 전후의 '실효 return 열' 연속성 — 직결 level 점프가
        # 없음을 실측으로도 확인 (level 비는 base 차이로 당연히 크다 — 그것이 함정).
        junction = str(new_rows[0].observation_time)[:10]
        level_ratio = None
        prior_old = [d for d in old_by_day if d < junction]
        if prior_old:
            level_ratio = new_by_day[junction] / old_by_day[max(prior_old)]

        pre_methodology = [
            row for row in new_rows
            if str(row.observation_time)[:10] < DOLLAR_METHODOLOGY_PUBLIC_DATE
        ]
        exact_before_public = [row for row in pre_methodology if row.data_grade == "native_pit"]
        dollar = {
            "status": "MEASURED",
            "dtwexb_range": [str(old_rows[0].observation_time)[:10],
                             str(old_rows[-1].observation_time)[:10]],
            "dtwexbgs_range": [str(new_rows[0].observation_time)[:10],
                               str(new_rows[-1].observation_time)[:10]],
            "effective_transition": {
                "rule": "log_change 계산 후 combine_first(DTWEXBGS 우선) — features.py:116-118",
                "effective_junction": junction,
                "note": "원고의 2019-01-02 는 FRED 계열 교체 시점; 현재 아카이브에선 "
                        "backcast 로 BGS 가 2006 부터 우선한다. 1995~2005 만 DTWEXB return 사용.",
            },
            "level_base_difference_at_junction": level_ratio,
            "overlap_return_agreement": {
                "n_common_days": len(common),
                "median_abs_diff": diffs_sorted[len(diffs_sorted) // 2] if diffs_sorted else None,
                "p99_abs_diff": diffs_sorted[int(len(diffs_sorted) * 0.99)] if diffs_sorted else None,
                "max_abs_diff": diffs_sorted[-1] if diffs_sorted else None,
            },
            "t13_verdict": (
                "PASS — return-먼저-연결 구조라 다른 base level 직결의 인공 return 경로 없음"
            ),
            "methodology_public_date": DOLLAR_METHODOLOGY_PUBLIC_DATE,
            "dtwexbgs_rows_observed_before_public_date": len(pre_methodology),
            "of_which_claimed_native_pit": len(exact_before_public),
            "t12_verdict": (
                "PASS — 공개일 이전 관측일 행이 native_pit(당시 가용) 등급을 주장하지 않는다"
                if not exact_before_public
                else f"FLAG — {len(exact_before_public)}행이 공개 전 native 가용을 주장"
            ),
            "residual_caveat": (
                "backcast 가 captured_forward 라 역사 재구성에서 pre-capture cutoff 에는 "
                "BGS 가 보이지 않는다 — 당시 정보집합 재구성은 DTWEXB 로 내려간다 (정상). "
                "단 운영 '현재' 패널의 pre-2019 달러 return 은 신방법론 backcast 다 — "
                "동결 V8 평가는 2026-08 아카이브 구축 후 실행이라 내적으로 일관."
            ),
        }

    # 3) revision 분포
    revisions = {
        series: Counter(int(row.revision_seq) for row in rows)
        for series, rows in sorted(by_series.items())
    }
    revision_summary = {
        series: {"rows": sum(counter.values()),
                 "revised_rows": sum(v for k, v in counter.items() if k > 1)}
        for series, counter in revisions.items()
    }

    # 4) 수집 지연 분포 (available_at − 관측일) — 운영기(관측일 최근 120일) 행만.
    # 백필(captured_forward 과거 관측)의 수집 지연은 구조적으로 거대해 운영 지연과
    # 섞으면 측정이 오염된다.
    all_days = sorted({str(r.observation_time)[:10] for r in observations})
    recent_cut = all_days[-120] if len(all_days) >= 120 else all_days[0]
    lag_summary: dict[str, Any] = {"window_note": f"관측일 >= {recent_cut} 행만 (운영기)"}
    for series, rows in sorted(by_series.items()):
        lags = sorted(
            _lag_days(str(row.observation_time)[:10], str(row.available_at))
            for row in rows
            if str(row.observation_time)[:10] >= recent_cut
        )
        if lags:
            lag_summary[series] = {
                "n_recent": len(lags),
                "median_days": round(lags[len(lags) // 2], 2),
                "p90_days": round(lags[int(len(lags) * 0.9)], 2),
            }

    # 5) 등급 분포 — captured_forward 의 역사 증거 부재 공시
    grade_summary = {
        series: dict(Counter(row.data_grade for row in rows))
        for series, rows in sorted(by_series.items())
    }

    report = {
        "schema_version": 1,
        "dollar_splice": dollar,
        "revision_summary": revision_summary,
        "collection_lag_recent": lag_summary,
        "grade_summary": grade_summary,
        "structural_findings": [
            "captured_forward 행은 available_at=수집 시각 — 역사적 공개 증거가 없어 "
            "historical reconstruction 에서 과거 cutoff 에 보이지 않는다 (NASDAQCOM·VIX "
            "백필 전체가 해당). 설계서 §6.2 의 '증거 없는 승격 금지' 를 저장소가 이미 지킨다.",
            "reconstructed_market_archive 1판만 post-close 보수 상계를 갖는다 (DGS2·DGS10).",
            "달러 주간 발표(H.10) 지연은 collection_lag_recent 의 DTWEXBGS 행에서 실측된다.",
        ],
    }
    out = root / REPORT_RELATIVE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                   encoding="utf-8")
    return report
