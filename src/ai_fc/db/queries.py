"""report/due용 읽기 질의."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class MlRef:
    """오픈웨이트 앙상블 참조 확률 (divergence 트리거 기준값)."""

    prob: float
    run_ts: datetime
    low_confidence: bool = False   # 모델 간 불일치 > 20%p — 트리거에서 제외


def latest_forecasts(conn: sqlite3.Connection) -> dict[str, Optional[datetime]]:
    out: dict[str, Optional[datetime]] = {}
    for row in conn.execute("SELECT question_id, last_ts FROM v_latest_forecast"):
        out[row["question_id"]] = (
            datetime.fromisoformat(row["last_ts"]) if row["last_ts"] else None
        )
    return out


def open_rolling_windows(conn: sqlite3.Connection) -> dict[str, list[tuple[str, date]]]:
    """rolling 질문의 (forecast_id, window_end) 목록."""
    out: dict[str, list[tuple[str, date]]] = {}
    for row in conn.execute(
        "SELECT question_id, forecast_id, window_end FROM forecasts WHERE window_end IS NOT NULL"
    ):
        out.setdefault(row["question_id"], []).append(
            (row["forecast_id"], date.fromisoformat(row["window_end"]))
        )
    return out


def resolved_forecast_ids(conn: sqlite3.Connection) -> set[str]:
    return {row["forecast_id"] for row in conn.execute("SELECT forecast_id FROM resolutions")}


def latest_probabilities(conn: sqlite3.Connection) -> dict[str, int]:
    """qid → 최신 회차 LLM 확률 (divergence 비교용)."""
    out: dict[str, int] = {}
    for row in conn.execute(
        """SELECT f.question_id, f.probability FROM forecasts f
           JOIN (SELECT question_id, MAX(round) AS r FROM forecasts GROUP BY question_id) m
             ON f.question_id = m.question_id AND f.round = m.r"""
    ):
        out[row["question_id"]] = int(row["probability"])
    return out


def latest_ml_refs(conn: sqlite3.Connection, max_age_days: int = 7) -> dict[str, "MlRef"]:
    """qid → 최신 ensemble 참조 확률. 신선도(max_age_days) 초과분은 제외."""
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    out: dict[str, MlRef] = {}
    for row in conn.execute(
        """SELECT question_id, prob, run_ts, detail_json FROM ml_forecasts
           WHERE model = 'ensemble' AND run_ts >= ?
           ORDER BY run_ts ASC""",  # 뒤 행이 최신 — 덮어써서 qid별 최신만 남김
        (cutoff,),
    ):
        detail = json.loads(row["detail_json"] or "{}")
        out[row["question_id"]] = MlRef(
            prob=float(row["prob"]),
            run_ts=datetime.fromisoformat(row["run_ts"]),
            low_confidence=bool(detail.get("low_confidence", False)))
    return out


def latest_market_implied(conn: sqlite3.Connection, question_id: str,
                          max_age_days: int = 3) -> Optional[tuple[float, str, str]]:
    """질문의 최신 시장내재확률 (prob, source, 수집일). 신선도 초과·부재 시 None.

    수집일 병기는 AUDIT-260715 D-5 (빈티지 인지) — 기존 호출부는 [0],[1]만 써서 호환.
    """
    row = conn.execute(
        "SELECT prob, source, run_ts FROM market_implied WHERE question_id = ?"
        " ORDER BY run_ts DESC LIMIT 1", (question_id,)).fetchone()
    if not row:
        return None
    age = datetime.now() - datetime.fromisoformat(row["run_ts"])
    if age > timedelta(days=max_age_days):
        return None
    return float(row["prob"]), str(row["source"]), str(row["run_ts"])[:10]


def sentiment_delta(conn: sqlite3.Connection, feed: str, days: int = 7) -> Optional[float]:
    """피드 감성의 days일 전 대비 변화. 이력 부족 시 None."""
    latest = conn.execute(
        "SELECT score, run_ts FROM ml_sentiment WHERE feed = ? ORDER BY run_ts DESC LIMIT 1",
        (feed,)).fetchone()
    if not latest or latest["score"] is None:
        return None
    cutoff = (datetime.fromisoformat(latest["run_ts"]) - timedelta(days=days)) \
        .isoformat(timespec="seconds")
    past = conn.execute(
        "SELECT score FROM ml_sentiment WHERE feed = ? AND run_ts <= ?"
        " ORDER BY run_ts DESC LIMIT 1", (feed, cutoff)).fetchone()
    if not past or past["score"] is None:
        return None
    return float(latest["score"]) - float(past["score"])


def brier_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM v_brier ORDER BY domain"))


def gate_status(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM v_gate_status").fetchone()


def calibration_curve(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM v_calibration_curve ORDER BY decile"))


def domain_skill(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM v_domain_skill ORDER BY domain"))


# ── WS8 캘리브레이션 과학 (표시 계층 — 게이트 산정식 무접촉) ─────

def murphy_decomposition(conn: sqlite3.Connection, domain: Optional[str] = None,
                         n_bins: int = 10) -> Optional[dict]:
    """Murphy 분해: Brier = Reliability − Resolution + Uncertainty. 표본 0이면 None."""
    where = "WHERE domain = ?" if domain else ""
    args = (domain,) if domain else ()
    rows = list(conn.execute(
        f"SELECT probability / 100.0 AS p, outcome AS o FROM resolutions {where}", args))
    if not rows:
        return None
    n = len(rows)
    obar = sum(r["o"] for r in rows) / n
    unc = obar * (1 - obar)
    bins: dict[int, list] = {}
    for r in rows:
        bins.setdefault(min(int(r["p"] * n_bins), n_bins - 1), []).append(r)
    rel = sum(len(b) * (sum(x["p"] for x in b) / len(b)
                        - sum(x["o"] for x in b) / len(b)) ** 2 for b in bins.values()) / n
    res = sum(len(b) * (sum(x["o"] for x in b) / len(b) - obar) ** 2
              for b in bins.values()) / n
    brier = sum((r["p"] - r["o"]) ** 2 for r in rows) / n
    return {"n": n, "brier": round(brier, 4), "reliability": round(rel, 4),
            "resolution": round(res, 4), "uncertainty": round(unc, 4)}


def rolling_brier(conn: sqlite3.Connection, window: int = 10) -> list[dict]:
    """해소 시간순 rolling Brier (윈도우 10) — 추세 감시용."""
    rows = list(conn.execute(
        "SELECT resolved_date, brier FROM resolutions ORDER BY resolved_date, forecast_id"))
    out = []
    for i in range(len(rows)):
        chunk = rows[max(0, i - window + 1):i + 1]
        out.append({"idx": i + 1, "resolved_date": rows[i]["resolved_date"],
                    "rolling": round(sum(r["brier"] for r in chunk) / len(chunk), 4),
                    "n_window": len(chunk)})
    return out


def n_excluded_from_primary(conn: sqlite3.Connection) -> int:
    """대표 Brier(v_brier_primary)에서 제외된 해소 수 — 상시 병기용 (검토질문 #3)."""
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM resolutions r
           LEFT JOIN forecasts f ON f.forecast_id = r.forecast_id
           LEFT JOIN research_status_override o ON o.forecast_id = r.forecast_id
           WHERE COALESCE(o.status, f.research_status, 'ok') = 'failed'""").fetchone()
    return int(row["n"])


def shadow_brier(conn: sqlite3.Connection) -> Optional[dict]:
    """섀도 extremized의 가상 Brier (기록값 표시 배관 — 공식 아님). 표본 0이면 None."""
    rows = list(conn.execute(
        """SELECT f.shadow_extremized AS s, r.outcome AS o, r.brier AS b
           FROM resolutions r JOIN forecasts f ON f.forecast_id = r.forecast_id
           WHERE f.shadow_extremized IS NOT NULL"""))
    if not rows:
        return None
    n = len(rows)
    shadow = sum((r["s"] / 100.0 - r["o"]) ** 2 for r in rows) / n
    official = sum(r["b"] for r in rows) / n
    return {"n": n, "shadow_brier": round(shadow, 4), "official_brier": round(official, 4)}


def latest_divergence_classes(conn: sqlite3.Connection) -> dict[str, str]:
    """qid → 최신 회차의 divergence_class (WS6 — due 표시에 직전 분류 병기)."""
    out: dict[str, str] = {}
    for row in conn.execute(
        """SELECT f.question_id, f.divergence_class FROM forecasts f
           JOIN (SELECT question_id, MAX(round) AS r FROM forecasts GROUP BY question_id) m
             ON f.question_id = m.question_id AND f.round = m.r
           WHERE f.divergence_class IS NOT NULL"""):
        out[row["question_id"]] = str(row["divergence_class"])
    return out


def month_cost(conn: sqlite3.Connection, year: int, month: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM cost_log WHERE ts LIKE ?",
        (f"{year:04d}-{month:02d}-%",),
    ).fetchone()
    return float(row["c"])


def log_cost(conn: sqlite3.Connection, question_id: str, stage: str, model: str,
             input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    conn.execute(
        "INSERT INTO cost_log (ts, question_id, stage, model, input_tokens, output_tokens, cost_usd)"
        " VALUES (?,?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), question_id, stage, model,
         input_tokens, output_tokens, cost_usd),
    )
    conn.commit()
