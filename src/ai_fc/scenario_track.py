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


def _display_values(payload: dict[str, Any], dates_length: int) -> tuple[list, str]:
    """그날 **화면에 실제로 그려졌던** 경로.

    굵은 주황 선은 원시 GBM 중앙값이 아니라 과거 조정 모양을 입힌 구조 경로다
    (dashboard.js 의 flowDisplayPath 와 같은 규칙). 원시 값을 쓰면 매끈한 우상향
    직선이 되어, 그날 화면과 다른 그림을 놓고 "얼마나 맞았나"를 묻게 된다.

    schema v1 아카이브(2026-07-30·07-31)에는 구조 경로가 없다 — 그때는 굴곡을 입히기
    전이라 원시 값이 곧 그려진 선이었다. 그래서 폴백은 누락이 아니라 사실이다.
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
    dates = _week_dates(payload, str(asof))
    values, path_source = _display_values(payload, len(dates or []))
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
    curved = next((row for row in rows if row["path_source"] == "structural"), None)
    if curved is not None and curved["asof"] != rows[0]["asof"]:
        starts.append(curved)

    segments = []
    for index, row in enumerate(starts):
        last = index + 1 == len(starts)
        end = today if last else starts[index + 1]["asof"]
        points = []
        for day, value in row["values"]:
            if day < row["asof"]:
                continue
            points.append([day, value])
            if day >= end:
                # 마지막 구간은 end(오늘)를 **넘어서는 첫 점까지** 포함한다. 주차 격자가
                # 휴일 보정으로 오늘을 건너뛸 수 있어(8/06 빈티지는 9/03 → 9/11),
                # 오늘에서 정확히 끊으면 현재 경로와 사이에 빈 구간이 생긴다.
                break
        if len(points) > 1:
            segments.append({"asof": row["asof"], "path_source": row["path_source"],
                             "values": points})
    return {"segments": segments,
            "curvature_from": curved["asof"] if curved is not None else None}


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
