"""V15 판정 라벨 xnas_v1 — kernel.

y(o,h) = ln(P_{s_h}/P_o), s_h = XNAS 달력에서 o 다음 h번째 세션, P = NASDAQCOM 최신 개정 종가
(as-of 해소 시각). `ai_fc.mts_research.v8_xnas_labels` 의 `XnasCalendar.build`·
`NasdaqArchive.from_observations`·`pit_mid` 수식을 **복사**했다(V15 kernel 해시 고정 —
`xnas_diagnostic_v1` 과 같은 값임은 테스트 L1). 달력은 `timeseries_v15.calendar` 다.
성숙 조건: P_{s_h} 가 아카이브에 있다(조회일 ≤ as_of). 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ai_fc.timeseries_v8.contracts import canonical_hash

from .calendar import CALENDAR_START, session_table

LABEL_BASIS = "xnas_v1"
MEASURED_TOLERANCE = 1e-12  # 같은 키의 y 가 이보다 크게 바뀌면 supersedes 정정 행


class V15LabelError(ValueError):
    """xnas_v1 라벨 계산 전제 위반 — fail-closed."""


@dataclass(frozen=True)
class XnasCalendar:
    """XNAS 세션 목록(오름차순)과 종가 시각(UTC)."""

    sessions: tuple[date, ...]
    closes_utc: Mapping[date, datetime]
    _index: dict[date, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if list(self.sessions) != sorted(set(self.sessions)):
            raise V15LabelError("XNAS 세션은 중복 없는 오름차순이어야 한다")
        object.__setattr__(self, "_index", {day: i for i, day in enumerate(self.sessions)})

    @classmethod
    def build(cls, start: date, end: date) -> "XnasCalendar":
        table = session_table(start, end)
        sessions = tuple(date.fromisoformat(row.session) for row in table)
        closes = {date.fromisoformat(row.session): row.close_utc for row in table}
        return cls(sessions=sessions, closes_utc=closes)

    def is_session(self, day: date) -> bool:
        return day in self._index

    def offset(self, origin: date, h: int) -> date:
        if h < 1:
            raise V15LabelError("h 는 1 이상")
        if origin not in self._index:
            raise V15LabelError(f"원점이 XNAS 세션이 아니다: {origin.isoformat()}")
        position = self._index[origin] + h
        if position >= len(self.sessions):
            raise V15LabelError("XNAS 달력 창이 목표 세션까지 닿지 않는다")
        return self.sessions[position]

    def close_utc(self, day: date) -> datetime:
        try:
            return self.closes_utc[day]
        except KeyError as exc:
            raise V15LabelError(f"XNAS 세션이 아니다: {day.isoformat()}") from exc


@dataclass(frozen=True)
class NasdaqArchive:
    """NASDAQCOM 최신 개정 종가. as_of 이후 행은 버린다. 조회는 XNAS 세션으로만 한다."""

    closes: Mapping[date, float]
    as_of: date
    provenance: Mapping[date, tuple[str, int, str | None]] = field(default_factory=dict)

    @classmethod
    def from_observations(cls, observations: Sequence[Any], *, as_of: date) -> "NasdaqArchive":
        closes: dict[date, float] = {}
        provenance: dict[date, tuple[str, int, str | None]] = {}
        for row in observations:
            day = date.fromisoformat(str(row.observation_time)[:10])
            if day > as_of:
                continue
            if row.series_id == "NASDAQCOM":
                value = float(row.value)
                if not math.isfinite(value) or value <= 0:
                    raise V15LabelError(f"NASDAQCOM 종가가 양의 유한값이 아니다: {day.isoformat()}")
                closes[day] = value
                provenance[day] = (str(row.observation_id), int(row.revision_seq), row.supersedes)
        return cls(closes=closes, as_of=as_of, provenance=provenance)

    def has(self, day: date) -> bool:
        return day in self.closes

    def close(self, day: date) -> float:
        try:
            return self.closes[day]
        except KeyError as exc:
            raise V15LabelError(f"NASDAQCOM 종가 없음: {day.isoformat()}") from exc

    def input_hash(self, days: Sequence[date]) -> str:
        payload = []
        for day in sorted(set(days)):
            observation_id, revision_seq, _ = self.provenance.get(day, (None, None, None))
            payload.append({"day": day.isoformat(), "observation_id": observation_id,
                            "revision_seq": revision_seq, "value": self.close(day)})
        return canonical_hash({"series": "NASDAQCOM", "inputs": payload})


def pit_mid(grid: np.ndarray, y: float) -> float:
    """원장 규약 PIT = (#{q_i<y} + 0.5·#{q_i=y}) / L."""
    return float((np.sum(grid < y) + 0.5 * np.sum(grid == y)) / grid.size)


def xnas_label(origin: date, h: int, cal: XnasCalendar, archive: NasdaqArchive) -> tuple[date, float] | None:
    """(s_h, y) — 성숙(P_{s_h} 관측)이면 값, 아니면 None. 원점 종가가 없으면 fail-closed."""
    target = cal.offset(origin, h)
    if target > archive.as_of or not archive.has(target):
        return None
    return target, math.log(archive.close(target) / archive.close(origin))


def xnas_label_fn(
    observations: Sequence[Any], *, cap: str, calendar_end: str | None = None,
) -> Callable[[str, int], float | None]:
    """MDE 설계창 라벨 함수 — s_h > cap 이면 예외(설계창 밖 바이트를 열지 않는다)."""
    cap_day = date.fromisoformat(cap)
    end = date.fromisoformat(calendar_end) if calendar_end else cap_day
    cal = XnasCalendar.build(CALENDAR_START, end)
    archive = NasdaqArchive.from_observations(observations, as_of=cap_day)

    def label(as_of: str, h: int) -> float | None:
        origin = date.fromisoformat(str(as_of)[:10])
        if not cal.is_session(origin) or not archive.has(origin):
            return None  # 비XNAS 원점(아카이브 비세션 행) — 라벨 없음, MDE 쌍에서 빠진다
        target = cal.offset(origin, int(h))
        if target > cap_day:
            raise V15LabelError(f"설계창 밖 라벨: {origin.isoformat()} h{h} → {target.isoformat()} > {cap}")
        if not archive.has(target):
            return None
        return math.log(archive.close(target) / archive.close(origin))

    return label
