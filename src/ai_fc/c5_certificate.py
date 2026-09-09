"""C5 캘리브레이션 프로그램 — 게이트 현황과 부수 증명서 (설계도 §8).

정본 관계 (중요):
- **게이트 판정의 정본은 SQLite 뷰 `v_gate_status`** (`db/schema.sql:433`)다.
  이 모듈은 같은 산술을 원천 파일(`calibration/ledger.csv` + 오버라이드)에서 재계산해
  **거울**을 제공한다. DB 가 있으면 교차검증하고, 불일치는 숨기지 않고 보고한다.
- 부수 증명서(BSS·Murphy·ESS·부트스트랩·경로 분해)는 전부 **표시 계층**이며
  게이트 판정에 다리를 놓지 않는다 (설계도 §8.1).

규율:
- **읽기 전용.** 이 모듈은 어떤 파일도 쓰지 않는다.
- **페일클로즈.** 파일·필드 부재는 '알 수 없음'이 아니라 미종료로 보고한다.
- 회수 못 한 값(anchor 등)은 추정으로 채우지 않고 표본에서 제외하고 그 사실을 센다.
"""

from __future__ import annotations

import csv
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

BRIER_THRESHOLD_P3 = 0.18
QUESTIONS_THRESHOLD_P3 = 50
BRIER_THRESHOLD_P2 = 0.20
QUESTIONS_THRESHOLD_P2 = 30

# 예측 산문 헤딩에서 outside view anchor 를 회수한다 (orchestrator.py 가 생성하는 형태).
# 기존 불변 파일을 고치지 않고 읽기만 한다 (설계도 §8.4).
_ANCHOR_RE = re.compile(r"anchor[:\s]*([0-9]{1,2})\s*%", re.I)
_FM_RE = {
    "forecast_id": re.compile(r"^forecast_id:\s*(\S+)", re.M),
    "question_id": re.compile(r"^question_id:\s*(\S+)", re.M),
    "probability": re.compile(r"^probability:\s*([0-9.]+)", re.M),
    "model": re.compile(r"^model:\s*(.+)$", re.M),
    "research_status": re.compile(r"^research_status:\s*(\S+)", re.M),
    "anchor_pct": re.compile(r"^anchor_pct:\s*([0-9]{1,2})", re.M),
}
_ROUND_RE = re.compile(r"_r(\d+)\.md$")


# ────────────────────────────────────────────────────────────────────
# 원천 읽기
# ────────────────────────────────────────────────────────────────────

@dataclass
class ForecastRecord:
    forecast_id: str
    question_id: str
    probability: float          # 0~1
    round: int
    path: Path
    anchor: Optional[float] = None   # 0~1, 회수 실패 시 None
    model: str = ""
    research_status: str = "ok"

    @property
    def pq(self) -> float:
        """완전 캘리브레이션 하의 기대 Brier = p(1-p) (설계도 §3 D2)."""
        return self.probability * (1.0 - self.probability)

    @property
    def path_kind(self) -> str:
        """생산 경로 — 비용 계측 공백을 정직하게 표기하기 위한 분류 (설계도 §7.3)."""
        m = self.model.lower()
        if "claude code" in m:
            return "claude_code (unmetered)"
        if m:
            return "cli/api"
        return "unknown"


def read_forecasts(root: Path) -> list[ForecastRecord]:
    out: list[ForecastRecord] = []
    base = root / "forecasts"
    if not base.exists():
        return out
    for path in sorted(base.glob("*/*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        head = text[:4000]
        prob = _FM_RE["probability"].search(head)
        qid = _FM_RE["question_id"].search(head)
        if not (prob and qid):
            continue                      # 초기 포맷 — 추정하지 않고 건너뛴다
        fid = _FM_RE["forecast_id"].search(head)
        rnd = _ROUND_RE.search(path.name)
        model = _FM_RE["model"].search(head)
        rs = _FM_RE["research_status"].search(head)
        # anchor: frontmatter 우선(전방 규약), 없으면 산문 헤딩에서 회수(소급, 읽기 전용)
        anchor_fm = _FM_RE["anchor_pct"].search(head)
        anchor_prose = _ANCHOR_RE.search(text)
        anchor = None
        if anchor_fm:
            anchor = int(anchor_fm.group(1)) / 100.0
        elif anchor_prose:
            anchor = int(anchor_prose.group(1)) / 100.0
        out.append(ForecastRecord(
            forecast_id=fid.group(1) if fid else path.stem,
            question_id=qid.group(1),
            probability=float(prob.group(1)) / 100.0,
            round=int(rnd.group(1)) if rnd else 1,
            path=path,
            anchor=anchor,
            model=(model.group(1).strip() if model else ""),
            research_status=(rs.group(1) if rs else "ok"),
        ))
    return out


def read_overrides(root: Path) -> dict[str, str]:
    path = root / "calibration" / "research_status_overrides.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["forecast_id"]: r["status"] for r in csv.DictReader(fh)}


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / "calibration" / "ledger.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_registry(root: Path) -> list[dict[str, Any]]:
    path = root / "questions" / "registry.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("questions", []) if isinstance(data, dict) else list(data)


# ────────────────────────────────────────────────────────────────────
# 게이트 (정본 거울)
# ────────────────────────────────────────────────────────────────────

def gate_status(root: Path) -> dict[str, Any]:
    """`v_gate_status` 와 같은 산술을 원천 파일에서 재계산한다.

    primary = research_status(오버라이드 우선) != 'failed'.
    문항 수는 COUNT(DISTINCT question_id), Brier 는 **행 평균** — 이 비대칭이 설계도 §1.2 A1.
    """
    rows = read_ledger(root)
    overrides = read_overrides(root)
    fc_status = {f.forecast_id: f.research_status for f in read_forecasts(root)}

    primary = [
        r for r in rows
        if overrides.get(r["forecast_id"], fc_status.get(r["forecast_id"], "ok")) != "failed"
    ]
    n_rows = len(primary)
    briers = [float(r["brier"]) for r in primary]
    questions = {r["question_id"] for r in primary}
    brier = sum(briers) / n_rows if n_rows else None
    return {
        "n_rows_all": len(rows),
        "n_rows_primary": n_rows,
        "n_excluded": len(rows) - n_rows,
        "n_questions": len(questions),
        "brier": brier,
        "gate_p2": len(questions) >= QUESTIONS_THRESHOLD_P2
        and brier is not None and brier < BRIER_THRESHOLD_P2,
        "gate_p3": len(questions) >= QUESTIONS_THRESHOLD_P3
        and brier is not None and brier < BRIER_THRESHOLD_P3,
        "questions": sorted(questions),
        "rows": primary,
    }


def gate_crosscheck(root: Path, gate: dict[str, Any]) -> Optional[str]:
    """DB 가 빌드돼 있으면 정본 뷰와 대사한다. 불일치는 숨기지 않는다."""
    db = root / "db" / "index.db"          # config.DB_PATH 와 같은 경로 (gitignore, 재구축 가능)
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM v_gate_status").fetchone()
        conn.close()
    except sqlite3.Error as exc:
        return f"DB 대사 실패 ({exc})"
    if row is None:
        return "DB 대사 실패 (v_gate_status 빈 결과)"
    diffs = []
    if int(row["n_questions"]) != gate["n_questions"]:
        diffs.append(f"문항 {row['n_questions']} vs {gate['n_questions']}")
    if row["brier"] is not None and gate["brier"] is not None:
        if abs(float(row["brier"]) - gate["brier"]) > 1e-6:
            diffs.append(f"Brier {float(row['brier']):.4f} vs {gate['brier']:.4f}")
    return "불일치: " + " · ".join(diffs) if diffs else "정본 뷰와 일치"


# ────────────────────────────────────────────────────────────────────
# D2 · 예리도
# ────────────────────────────────────────────────────────────────────

def sharpness(root: Path) -> dict[str, Any]:
    """포트폴리오 예리도. 게이트 Brier 는 행 평균이므로 행 기준이 정본 지표."""
    forecasts = read_forecasts(root)
    if not forecasts:
        return {"rows": None}
    rows_pq = [f.pq for f in forecasts]
    latest: dict[str, ForecastRecord] = {}
    per_q: dict[str, list[ForecastRecord]] = defaultdict(list)
    for f in forecasts:
        per_q[f.question_id].append(f)
    for qid, items in per_q.items():
        latest[qid] = max(items, key=lambda x: x.round)

    multi = {q: v for q, v in per_q.items() if len(v) > 1}
    first_pq = [min(v, key=lambda x: x.round).pq for v in multi.values()]
    last_pq = [max(v, key=lambda x: x.round).pq for v in multi.values()]
    sharpened = sum(1 for v in multi.values()
                    if max(v, key=lambda x: x.round).pq < min(v, key=lambda x: x.round).pq)

    n = len(rows_pq)
    return {
        "rows": {"n": n, "mean_pq": sum(rows_pq) / n,
                 "deficit": BRIER_THRESHOLD_P3 * n - sum(rows_pq)},
        "latest_round": {"n": len(latest),
                         "mean_pq": sum(f.pq for f in latest.values()) / len(latest)},
        "reforecast": ({"n": len(multi),
                        "first": sum(first_pq) / len(first_pq),
                        "latest": sum(last_pq) / len(last_pq),
                        "delta": (sum(last_pq) - sum(first_pq)) / len(first_pq),
                        "sharpened": sharpened}
                       if multi else None),
    }


def required_new_rows(deficit: float, target_pq: float) -> Optional[int]:
    """결손을 메우는 데 필요한 신규 채점 행 수 (설계도 §3 D2 수식).

    k·(0.18 − c) > −deficit.  c >= 0.18 이면 어떤 k 로도 불가 → None.
    """
    if deficit >= 0:
        return 0
    if target_pq >= BRIER_THRESHOLD_P3:
        return None
    return math.ceil((-deficit) / (BRIER_THRESHOLD_P3 - target_pq))


# ────────────────────────────────────────────────────────────────────
# 부수 증명서
# ────────────────────────────────────────────────────────────────────

def bss_vs_anchor(root: Path, gate: dict[str, Any]) -> dict[str, Any]:
    """사전등록 outside view anchor 대비 Brier Skill Score.

    질문을 쉽게 고르면 anchor 도 같이 예리해지므로 **패딩에 면역**이다 (설계도 §4.2).
    anchor 회수 실패 행은 추정으로 채우지 않고 제외한다.
    """
    anchors = {f.forecast_id: f.anchor for f in read_forecasts(root)}
    paired: list[tuple[float, float, int]] = []   # (brier_model, brier_anchor, outcome)
    missing = 0
    for r in gate["rows"]:
        anchor = anchors.get(r["forecast_id"])
        if anchor is None:
            missing += 1
            continue
        outcome = int(r["outcome"])
        paired.append((float(r["brier"]), (anchor - outcome) ** 2, outcome))
    if not paired:
        return {"n": 0, "missing": missing, "bss": None,
                "brier_model": None, "brier_anchor": None}
    bm = sum(x[0] for x in paired) / len(paired)
    ba = sum(x[1] for x in paired) / len(paired)
    return {"n": len(paired), "missing": missing,
            "brier_model": bm, "brier_anchor": ba,
            "bss": (1 - bm / ba) if ba > 0 else None}


def murphy(gate: dict[str, Any], n_bins: int = 10) -> Optional[dict[str, float]]:
    """Brier = Reliability − Resolution + Uncertainty.

    UNC 급락은 확정형 패딩의 신호, RES 저하는 예리도 부재의 신호 (설계도 §8.2).
    """
    rows = gate["rows"]
    if not rows:
        return None
    pairs = [(float(r["probability"]) / 100.0, int(r["outcome"])) for r in rows]
    n = len(pairs)
    obar = sum(o for _, o in pairs) / n
    bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, o in pairs:
        bins[min(int(p * n_bins), n_bins - 1)].append((p, o))
    rel = sum(len(b) * (sum(p for p, _ in b) / len(b) - sum(o for _, o in b) / len(b)) ** 2
              for b in bins.values()) / n
    res = sum(len(b) * (sum(o for _, o in b) / len(b) - obar) ** 2
              for b in bins.values()) / n
    return {"n": n, "brier": sum((p - o) ** 2 for p, o in pairs) / n,
            "reliability": rel, "resolution": res, "uncertainty": obar * (1 - obar)}


def driver_clusters(root: Path) -> dict[str, list[str]]:
    """질문 → 주 드라이버 클러스터. 무태그는 보수적으로 '(none)' 한 덩어리로 묶는다."""
    clusters: dict[str, list[str]] = defaultdict(list)
    for q in read_registry(root):
        if q.get("status") == "void":
            continue
        drivers = q.get("drivers") or []
        clusters[drivers[0] if drivers else "(none)"].append(q["id"])
    return dict(clusters)


def effective_sample_size(clusters: dict[str, list[str]],
                         subset: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """ESS 하한 = n² / Σnₖ² (클러스터 내 **완전 상관** 가정).

    하한으로만 보고한다 — 실제 상관은 1보다 작으므로 진짜 ESS 는 [하한, 명목] 구간.
    """
    keep = set(subset) if subset is not None else None
    sizes = []
    for members in clusters.values():
        k = len([m for m in members if keep is None or m in keep])
        if k:
            sizes.append(k)
    n = sum(sizes)
    if not n:
        return {"nominal": 0, "ess_lower": 0.0, "largest_share": None}
    return {"nominal": n,
            "ess_lower": n * n / sum(s * s for s in sizes),
            "largest_share": max(sizes) / n}


def clustered_bootstrap(gate: dict[str, Any], clusters: dict[str, list[str]],
                        *, n_boot: int = 10_000, seed: int = 42,
                        confidence: float = 0.90) -> Optional[dict[str, Any]]:
    """클러스터 단위 리샘플링 부트스트랩. 행 단위 리샘플링은 D3(독립성)을 은폐한다."""
    rows = gate["rows"]
    if not rows:
        return None
    import numpy as np

    q_to_cluster = {qid: name for name, members in clusters.items() for qid in members}
    grouped: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        grouped[q_to_cluster.get(r["question_id"], "(unregistered)")].append(float(r["brier"]))
    groups = list(grouped.values())
    if len(groups) < 2:
        return {"n_clusters": len(groups), "mean": gate["brier"],
                "ci_lo": None, "ci_hi": None,
                "note": "클러스터 2개 미만 — 구간 추정 불가"}
    rng = np.random.default_rng(seed)
    idx = np.arange(len(groups))
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.choice(idx, size=len(groups), replace=True)
        vals = [v for j in pick for v in groups[j]]
        means[i] = sum(vals) / len(vals)
    alpha = (1 - confidence) / 2
    return {"n_clusters": len(groups), "mean": gate["brier"],
            "ci_lo": float(np.quantile(means, alpha)),
            "ci_hi": float(np.quantile(means, 1 - alpha)), "note": None}


def production_paths(root: Path) -> dict[str, int]:
    """생산 경로별 예측 수. Claude Code 경로는 cost_log 에 안 잡힌다 (설계도 §7.3)."""
    return dict(Counter(f.path_kind for f in read_forecasts(root)))


# ────────────────────────────────────────────────────────────────────
# 큐 (Q1 SLA)
# ────────────────────────────────────────────────────────────────────

RESOLUTION_SLA_DAYS = 3


def queues(root: Path, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    registry = read_registry(root)
    resolved_q = {r["question_id"] for r in read_ledger(root)}
    forecast_q = {f.question_id for f in read_forecasts(root)}

    overdue, never_forecast = [], []
    for q in registry:
        if q.get("status") != "active":
            continue
        if q["id"] not in forecast_q:
            never_forecast.append(q["id"])
        deadline = q.get("deadline")
        if not isinstance(deadline, (str, date)) or q["id"] in resolved_q:
            continue
        try:
            dl = deadline if isinstance(deadline, date) else datetime.strptime(
                str(deadline), "%Y-%m-%d").date()
        except ValueError:
            continue                       # rolling-90d 등 — 날짜형이 아니면 건너뛴다
        if dl < today:
            overdue.append({"id": q["id"], "deadline": str(dl),
                            "days": (today - dl).days,
                            "sla_breach": (today - dl).days > RESOLUTION_SLA_DAYS})
    overdue.sort(key=lambda x: -x["days"])
    return {"resolve_overdue": overdue, "never_forecast": sorted(never_forecast)}


# ────────────────────────────────────────────────────────────────────
# 사전등록 대사
# ────────────────────────────────────────────────────────────────────

def prereg(root: Path) -> Optional[dict[str, Any]]:
    path = root / "questions" / "portfolio_prereg_v1.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def diversification_check(root: Path) -> dict[str, Any]:
    """사전등록 분산 규칙 위반 점검. 위반은 숨기지 않고 센다."""
    pre = prereg(root)
    rules = (pre or {}).get("diversification", {})
    clusters = driver_clusters(root)
    ess = effective_sample_size(clusters)
    registry = [q for q in read_registry(root) if q.get("status") == "active"]
    deadline_counts = Counter(str(q.get("deadline")) for q in registry)
    domains = {q.get("domain") for q in registry if q.get("domain")}

    violations = []
    cap = rules.get("max_driver_share")
    if cap and ess["largest_share"] and ess["largest_share"] > cap:
        violations.append(
            f"단일 드라이버 점유 {ess['largest_share']:.0%} > 상한 {cap:.0%}")
    same = rules.get("max_same_deadline")
    if same:
        for dl, cnt in deadline_counts.items():
            if dl not in ("None", "rolling-90d") and cnt > same:
                violations.append(f"마감일 {dl} 에 {cnt}문항 > 상한 {same}")
    min_dom = rules.get("min_domains")
    if min_dom and len(domains) < min_dom:
        violations.append(f"도메인 {len(domains)} < 하한 {min_dom}")
    return {"violations": violations, "clusters": clusters, "ess": ess,
            "domains": sorted(d for d in domains if d)}


# ────────────────────────────────────────────────────────────────────
# 단계 판정 (설계도 §10.3)
# ────────────────────────────────────────────────────────────────────

@dataclass
class Stage:
    name: str
    done: bool
    detail: str


def stages(root: Path, gate: dict[str, Any], q: dict[str, Any]) -> list[Stage]:
    pre = prereg(root)
    tool = (root / "tools" / "c5_status.py").exists()
    cert = (root / "src" / "ai_fc" / "c5_certificate.py").exists()
    approved = bool(pre and pre.get("approval_text"))
    n_new = len([x for x in read_registry(root)
                 if str(x.get("created", "")) >= "2026-09-09"])
    workflows = root / ".github" / "workflows"
    auto = (workflows / "c5-resolve-draft.yml").exists()
    return [
        Stage("Q0 판정 기계", tool and cert,
              f"c5_status={'O' if tool else 'X'} · certificate={'O' if cert else 'X'}"),
        Stage("Q1 밀린 해소", not q["resolve_overdue"],
              f"해소 대기 {len(q['resolve_overdue'])}건"),
        Stage("Q2 사전등록", approved,
              "승인 원문 기록됨" if approved else "미승인"),
        Stage("Q3 질문 공급", n_new >= 20, f"신규 등록 {n_new}/20"),
        Stage("Q4 자동화", auto, "c5-resolve-draft.yml " + ("존재" if auto else "부재")),
        Stage("Q5 축적", gate["n_questions"] >= 45, f"문항 {gate['n_questions']}/45"),
        Stage("Q6 게이트 대면", bool(gate["gate_p3"]),
              f"문항 {gate['n_questions']}/50 · Brier "
              + (f"{gate['brier']:.4f}" if gate["brier"] is not None else "n/a")),
    ]


# ────────────────────────────────────────────────────────────────────
# ML 층위 관측 (ML 설계도 §8) — 전부 관측 전용, 어떤 것도 공식 확률을 바꾸지 않는다
# ────────────────────────────────────────────────────────────────────

# 사전등록 격자 (ML 설계도 §6). **결과를 보고 확장하지 않는다.**
EXTREMIZATION_GRID = (1.0, 1.2, 1.5, math.sqrt(3), 2.0)
EXTREMIZATION_MIN_SAMPLE = 30


def _extremize(p: float, alpha: float) -> float:
    """σ(α·logit(p)). 결정론 변환 — 기록된 확률에만 적용한다 (LLM 재실행 아님)."""
    p = min(max(p, 0.01), 0.99)
    return 1.0 / (1.0 + math.exp(-math.log(p / (1 - p)) * alpha))


def extremization_observation(gate: dict[str, Any]) -> Optional[dict[str, Any]]:
    """M1 — 사전등록 α 격자의 가상 Brier. 표본 미달이면 판정하지 않는다."""
    rows = gate["rows"]
    if not rows:
        return None
    pairs = [(float(r["probability"]) / 100.0, int(r["outcome"])) for r in rows]
    base = sum((p - o) ** 2 for p, o in pairs) / len(pairs)
    grid = [{"alpha": a,
             "brier": sum((_extremize(p, a) - o) ** 2 for p, o in pairs) / len(pairs)}
            for a in EXTREMIZATION_GRID]
    for item in grid:
        item["delta"] = item["brier"] - base
    best = min(grid, key=lambda x: x["brier"])
    return {"n": len(pairs), "base": base, "grid": grid, "best_alpha": best["alpha"],
            "sufficient": len(pairs) >= EXTREMIZATION_MIN_SAMPLE,
            "min_sample": EXTREMIZATION_MIN_SAMPLE}


def decile_fill(gate: dict[str, Any], n_bins: int = 10) -> dict[int, int]:
    """M5 — 십분위 빈 채움. isotonic 보정(해소 100+)이 언제 가능해지는지의 선행 지표."""
    counts = {i: 0 for i in range(n_bins)}
    for r in gate["rows"]:
        p = float(r["probability"]) / 100.0
        counts[min(int(p * n_bins), n_bins - 1)] += 1
    return counts


def pairwise_benchmark_count(root: Path) -> dict[str, int]:
    """M6 — LLM/ML/시장 쌍대 표본. 학습 결합(해소 200+)의 선행 조건."""
    path = root / "calibration" / "benchmark_ledger.csv"
    if not path.exists():
        return {"rows": 0, "with_ml": 0, "with_market": 0, "all_three": 0}
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    def has(row: dict[str, Any], key: str) -> bool:
        return bool((row.get(key) or "").strip())

    return {"rows": len(rows),
            "with_ml": sum(1 for r in rows if has(r, "ml_prob")),
            "with_market": sum(1 for r in rows if has(r, "market_prob")),
            "all_three": sum(1 for r in rows if has(r, "ml_prob") and has(r, "market_prob"))}


def shadow_coverage(root: Path) -> dict[str, int]:
    """관측 채널 커버리지 — shadow_extremized 를 실제로 기록한 예측 비율."""
    total = written = 0
    for path in sorted((root / "forecasts").glob("*/*.md")) if (root / "forecasts").exists() else []:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        if "probability:" not in head:
            continue
        total += 1
        if "shadow_extremized:" in head:
            written += 1
    return {"total": total, "written": written}


def report(root: Path, today: Optional[date] = None) -> dict[str, Any]:
    """전체 상태를 한 번에 파생한다 (도구·대시보드 공용)."""
    gate = gate_status(root)
    clusters = driver_clusters(root)
    q = queues(root, today)
    return {
        "gate": gate,
        "crosscheck": gate_crosscheck(root, gate),
        "sharpness": sharpness(root),
        "bss": bss_vs_anchor(root, gate),
        "murphy": murphy(gate),
        "ess": effective_sample_size(clusters, gate["questions"]),
        "ess_registry": effective_sample_size(clusters),
        "bootstrap": clustered_bootstrap(gate, clusters),
        "paths": production_paths(root),
        "queues": q,
        "diversification": diversification_check(root),
        "stages": stages(root, gate, q),
        "prereg": prereg(root),
        "ml": {
            "extremization": extremization_observation(gate),
            "deciles": decile_fill(gate),
            "pairwise": pairwise_benchmark_count(root),
            "shadow_coverage": shadow_coverage(root),
        },
    }
