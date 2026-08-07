"""오버레이 엔진 — 시간 정렬·지수화·M2 정규화·MDD (v3 방법론 §1.2, §7.1, §9)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DOTCOM_ANCHOR = "1996-01"  # M+0
AI_ANCHOR = "2023-01"      # M+0
DOTCOM_PEAK_M = 50         # 2000-03


def month_offset(anchor: str, label: str) -> int:
    ay, am = int(anchor[:4]), int(anchor[5:7])
    ly, lm = int(label[:4]), int(label[5:7])
    return (ly - ay) * 12 + (lm - am)


def normalize(labels: list[str], closes: list[float], anchor: str) -> dict[int, float]:
    """anchor 월 = 100으로 지수화. {M+k: 지수값}"""
    base = None
    for lb, c in zip(labels, closes):
        if lb == anchor:
            base = c
            break
    if base is None:
        raise ValueError(f"anchor {anchor} 미포함")
    return {month_offset(anchor, lb): c / base * 100.0
            for lb, c in zip(labels, closes) if month_offset(anchor, lb) >= 0}


def m2_normalize(index: dict[int, float], labels_by_m: dict[int, str],
                 m2: dict[str, float], anchor: str) -> dict[int, float]:
    """지수 ÷ (M2/M2_anchor). M2 미발표 월은 마지막 값 유지(carry-forward)."""
    base_m2 = m2.get(anchor)
    if base_m2 is None:
        raise ValueError(f"M2에 anchor {anchor} 없음")
    out, last = {}, base_m2
    for m in sorted(index):
        val = m2.get(labels_by_m.get(m, ""), None)
        if val is not None:
            last = val
        out[m] = index[m] / (last / base_m2)
    return out


@dataclass
class Drawdown:
    mdd: float          # 음수 (예: -0.2432)
    peak_label: str
    trough_label: str


def max_drawdown(labels: list[str], closes: list[float]) -> Drawdown:
    arr = np.asarray(closes, dtype=float)
    peaks = np.maximum.accumulate(arr)
    dd = arr / peaks - 1.0
    i = int(np.argmin(dd))
    j = int(np.argmax(arr[: i + 1]))
    return Drawdown(float(dd[i]), labels[j], labels[i])
