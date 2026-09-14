"""기록된 S1(상승) 경로 빈티지를 그 뒤 실제 종가와 대조한다.

라이브 포워드 전용이다. 선 하나는 그날 `data/scenarios/archive/<asof>.json` 에
기록돼 커밋된 값 그대로이며, 지금 모형을 과거로 되돌려 그리지 않는다
(CLAUDE.md 5원칙 ⑤ 백테스트 금지).

실제 종가도 외부 조회 없이 같은 아카이브에서 가져온다 — 각 파일의 `anchor` 는
그 `asof` 날짜에 확정 종가로 기록된 값이라, 빈티지 집합이 곧 실제 종가 계열이다.
따라서 이 대조는 커밋된 repo 만으로 재현되며 네트워크에 의존하지 않는다.

산출은 참고 의견이다. S1 은 중앙 예측이 아니라 '상승·ATH 돌파' **조건부** 경로라
구조상 실제보다 위로 치우친다 — 오차의 부호를 실력으로 읽으면 안 된다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean, median
from typing import Any

from .scenario import ARCHIVE_RELATIVE_DIR

SCENARIO_KEY = "S1"
# 대조 지평. 빈티지는 최장 252거래일(2027-08)까지 뻗지만, 이 화면의 용도는 '예측과 실제가
# 겹치는 구간'을 보는 것이다. 연말까지 실으면 겹침이 가로폭의 20% 밑으로 눌리고 세로 축도
# 미래 경로가 다 잡아먹어 실제 선이 납작해진다. 마지막 실제 종가에서 이만큼만 더 보여준다 —
# 겹침이 화면 절반쯤을 차지하면서 경로가 향하는 방향도 남는다.
LEAD_DAYS = 42


def _dates_from_week_labels(weeks: list[Any], asof: str) -> list[str] | None:
    """schema_version 1 아카이브의 'M/D' 주차 라벨을 ISO 날짜로 되돌린다.

    v1 에는 `week_dates` 가 없고 `weeks` 라벨만 있다. 라벨은 asof 연도에서 시작해
    월이 단조 증가하므로, 월이 줄어드는 지점을 연도 롤오버로 읽는다.
    """
    try:
        year = int(asof[:4])
    except (TypeError, ValueError):
        return None
    out: list[str] = []
    previous: int | None = None
    for label in weeks:
        try:
            month_text, day_text = str(label).split("/")
            month, day = int(month_text), int(day_text)
            if previous is not None and month < previous:
                year += 1
            previous = month
            out.append(date(year, month, day).isoformat())
        except (ValueError, TypeError):
            return None
    return out


def _week_dates(payload: dict[str, Any], asof: str) -> list[str] | None:
    dates = payload.get("week_dates")
    if isinstance(dates, list) and dates:
        return [str(day) for day in dates]
    weeks = payload.get("weeks")
    if isinstance(weeks, list) and weeks:
        return _dates_from_week_labels(weeks, asof)
    return None


def _daily_series(payload: dict[str, Any]) -> tuple[list[str], list[Any]] | None:
    """252 거래일 **일별** S1 경로.

    주간 52점은 같은 모형의 성긴 표본이라 점과 점 사이가 직선으로 이어진다. 아카이브는
    처음부터 `quantile_table` 에 거래일 252개와 시나리오별 조건부 중앙값을 함께 담아
    왔는데(34건 중 32건), 화면은 주간만 쓰고 그 해상도를 버리고 있었다.

    일별 축은 asof **다음** 거래일부터 시작한다. 그날의 확정 종가(anchor)를 앞에 붙여야
    선이 그날 값에서 출발한다 — 없는 값을 만드는 것이 아니라 이미 기록된 값을 잇는 것이다.
    """
    table = payload.get("quantile_table") or {}
    days = table.get("trading_days")
    values = (table.get("per_scenario_p50") or {}).get(SCENARIO_KEY)
    anchor, asof = payload.get("anchor"), payload.get("asof")
    if not isinstance(days, list) or not isinstance(values, list):
        return None
    if not days or len(days) != len(values) or anchor is None or not asof:
        return None
    return [str(asof), *(str(day) for day in days)], [anchor, *values]


def _display_values(payload: dict[str, Any], dates_length: int) -> tuple[list, str]:
    """주간 격자에서 **그날 화면에 그려졌던** 경로 (일별이 없을 때의 대안).

    굵은 주황 선은 원시 GBM 중앙값이 아니라 과거 조정 모양을 입힌 구조 경로다
    (dashboard.js 의 flowDisplayPath 와 같은 규칙).

    schema v1 아카이브(2026-07-30·07-31)에는 구조 경로도 일별도 없다 — 그때는 굴곡을
    입히기 전이라 원시 값이 곧 그려진 선이었다. 그래서 폴백은 누락이 아니라 사실이다.
    """
    structural = (((payload.get("structural_forecast") or {}).get("paths") or {})
                  .get(SCENARIO_KEY) or {}).get("values")
    if isinstance(structural, list) and len(structural) == dates_length:
        return structural, "structural"
    return ((payload.get("paths") or {}).get(SCENARIO_KEY) or {}).get("values"), "gbm_median"


def _vintage(payload: dict[str, Any]) -> dict[str, Any] | None:
    asof = payload.get("asof")
    path = ((payload.get("paths") or {}).get(SCENARIO_KEY)) or {}
    anchor = payload.get("anchor")
    if not asof or anchor is None:
        return None
    # 구조 경로(주간 52점)가 최우선이다. 일별 252점이 더 촘촘하지만 그것은 9,000 경로의
    # 조건부 **중앙값**이라 구조상 거의 단조 상승한다 — 실측 1년 최대 낙폭 0.07%, 그리는
    # 창에서는 29점 중 하락 0점. 어떤 시장도 그렇게 움직이지 않으므로 가격 경로로 내보이면
    # 비현실적이다. 구조 경로는 같은 기간 최대 낙폭 12.15%(창 안 4.04%)로 모양이 있다.
    # 일별은 구조 경로가 없는 아카이브(2026-08-03 등)의 차선책으로만 쓴다.
    dates = _week_dates(payload, str(asof))
    values, path_source = _display_values(payload, len(dates or []))
    if path_source != "structural":
        daily = _daily_series(payload)
        if daily is not None:
            dates, values = daily
            path_source = "daily_p50"
    if not isinstance(values, list):
        return None
    # 길이가 어긋나면 날짜 정렬을 신뢰할 수 없다 — 조용히 어긋난 선을 그리느니 버린다.
    if dates is None or len(dates) != len(values):
        return None
    try:
        series = [[day, float(value)] for day, value in zip(dates, values)]
        return {
            "asof": str(asof),
            "prob": path.get("prob"),
            "label": path.get("label"),
            "anchor": float(anchor),
            "values": series,
            "path_source": path_source,
        }
    except (TypeError, ValueError):
        return None


def _past_line(rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    """오늘 왼쪽(이미 지나간 구간)에 그릴 **한 줄짜리** S1 경로.

    한 빈티지만 끝까지 끌면 굴곡이 없는 시절의 기록(2026-07-30·07-31)이 오늘까지
    매끈한 직선으로 남는다. 굴곡 기록이 생긴 날부터는 그쪽으로 바통을 넘긴다 —
    각 구간은 **그때 화면에 실제로 그려졌던 선**이고, 지금 만든 값은 하나도 없다.

    이음점에 남는 단차는 지우지 않는다. 그것이 앞 구간 기록이 그 시점까지 얼마나
    빗나가 있었는지다(2026-08-06 기준 1,045p) — 맞춰 붙이면 그 사실이 사라진다.
    """
    if not rows or not today:
        return {"segments": []}
    starts = [rows[0]]
    # 더 나은 기록이 처음 생긴 날 바통을 넘긴다. 순위는 **모양의 현실성**이 먼저다 —
    # 구조 경로(주간 52점, 실측 최대 낙폭 12.15%) > 일별 중앙값(252점이지만 낙폭 0.07%로
    # 사실상 단조 상승) > 원시 주간. 점이 많다고 더 나은 것이 아니다.
    #
    # 티어 안에서 가장 이른 것을 고른다. 멤버십으로만 찾으면 낮은 티어가 먼저 나올 때
    # 그쪽이 잡혀, 모양 있는 기록을 두고 단조 상승선으로 넘어간다.
    handover = None
    if rows[0]["path_source"] not in ("structural", "daily_p50"):
        for tier in ("structural", "daily_p50"):
            handover = next((row for row in rows if row["path_source"] == tier), None)
            if handover is not None:
                break
    if handover is not None and handover["asof"] != rows[0]["asof"]:
        starts.append(handover)

    segments = []
    for index, row in enumerate(starts):
        last = index + 1 == len(starts)
        end = today if last else starts[index + 1]["asof"]
        points = []
        for day, value in row["values"]:
            if day < row["asof"]:
                continue
            if not last and day > end:
                # 앞 구간이 다음 구간 시작을 넘어가면 두 선이 겹쳐 갈래처럼 보인다.
                break
            points.append([day, value])
            if last and day >= end:
                # 마지막 구간만 end(오늘)를 **넘어서는 첫 점까지** 포함한다. 격자가 휴일
                # 보정으로 오늘을 건너뛸 수 있어(8/06 빈티지는 9/03 → 9/11), 오늘에서
                # 정확히 끊으면 현재 경로와 사이에 빈 구간이 생긴다.
                break
        # 점이 하나뿐인 앞 구간은 선이 되지 않는다 — 그릴 수 없으니 버린다.
        if len(points) > 1:
            segments.append({"asof": row["asof"], "path_source": row["path_source"],
                             "values": points})
    labels = {"daily_p50": "일별 기록", "structural": "굴곡 기록", "gbm_median": "주간 기록"}
    return {
        "segments": segments,
        "handover_from": handover["asof"] if handover is not None else None,
        "handover_label": labels.get(handover["path_source"]) if handover is not None else None,
    }


def load_scenario_track(root: Path, *, cut: str | None = None) -> dict[str, Any]:
    """아카이브 전량에서 S1 빈티지와 실제 종가 계열을 만든다."""
    archive_dir = root / ARCHIVE_RELATIVE_DIR
    by_day: dict[str, dict[str, Any]] = {}
    if archive_dir.exists():
        for file in sorted(archive_dir.glob("*.json")):
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            row = _vintage(payload)
            if row is not None:
                by_day.setdefault(row["asof"], row)
                if payload.get("ath") is not None:
                    row["ath"] = payload["ath"]

    vintages = [by_day[day] for day in sorted(by_day)]
    if len(vintages) < 2:
        return {"status": "unavailable", "reason": "S1 빈티지가 2건 미만"}

    actual = [[row["asof"], row["anchor"]] for row in vintages]
    if cut is None:
        last_actual = date.fromisoformat(actual[-1][0])
        cut = (last_actual + timedelta(days=LEAD_DAYS)).isoformat()
    closes = dict(actual)

    out_vintages = []
    errors: list[float] = []
    for row in vintages:
        series = [[day, value] for day, value in row["values"] if day <= cut]
        if not series:
            continue
        # 예측일 이후의 주차점 중 실제 종가가 있는 전부를 채점한다 — 마지막 한 점만
        # 쓰면 같은 선의 앞구간 오차가 통계에서 사라진다.
        matches = [{
            "date": day, "predicted": value, "actual": closes[day],
            "error_pct": round((value - closes[day]) / closes[day] * 100, 2),
        } for day, value in series if day > row["asof"] and day in closes]
        errors.extend(abs(match["error_pct"]) for match in matches)
        out_vintages.append({
            "asof": row["asof"], "prob": row["prob"], "label": row["label"],
            "path_source": row["path_source"],
            "anchor": round(row["anchor"], 2),
            "values": [[day, round(value)] for day, value in series],
            "match_count": len(matches),
            "realized": matches[-1] if matches else None,
        })

    ath = next((row["ath"] for row in reversed(vintages) if row.get("ath") is not None), None)
    past_line = _past_line(out_vintages, actual[-1][0] if actual else "")
    return {
        "status": "ok",
        "index": "^IXIC",
        "scenario_key": SCENARIO_KEY,
        "label": vintages[-1].get("label") or SCENARIO_KEY,
        "source_path": ARCHIVE_RELATIVE_DIR.as_posix(),
        "cut": cut,
        "ath": ath,
        "actual": [[day, round(value, 2)] for day, value in actual],
        "past_line": past_line,
        "vintages": out_vintages,
        "stats": {
            "vintage_count": len(out_vintages),
            "scored_point_count": len(errors),
            "scored_vintage_count": sum(1 for row in out_vintages if row["realized"]),
            "mean_abs_error_pct": round(fmean(errors), 2) if errors else None,
            "median_abs_error_pct": round(median(errors), 2) if errors else None,
            "first_asof": out_vintages[0]["asof"] if out_vintages else None,
            "last_asof": out_vintages[-1]["asof"] if out_vintages else None,
        },
    }
