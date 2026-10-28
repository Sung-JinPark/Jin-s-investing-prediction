"""V14 라이브 경로 테스트 공용 픽스처 — 임시 저장소·합성 계약 사본·합성 동결 계수·합성 아카이브.

실계약·실원장·실아카이브는 건드리지 않는다. 계약은 실계약을 읽어 **사본**에 live_pointer·frozen_coefficients 를
덮어쓴다(실계약에 그 키가 아직 없어도 같은 사본이 나온다 — orchestrator 가 나중에 추가한다).
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from ai_fc.timeseries_v14 import contracts as C

ROOT = Path(__file__).resolve().parents[2]
CALENDAR_RELATIVE = Path("data/contracts/nyse_holidays.yaml")
RECEIPT = "v14-approval:V14-D10:2026-10-28:r2"     # 정본 D10 영수증 — r1 은 r2 가 supersedes 로 대체했다
SUPERSEDED_RECEIPT = "v14-approval:V14-D10:2026-10-28:r1"
CHAMPION = ["crv_h5"]
EFFECTIVE_FROM = "2026-10-22"
# 2026-10-22(목) · 10-23(금) · 10-26(월) · 10-27(화) — 전부 NYSE 거래일
D0, D1, D2, D3 = "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"


def roles_for(champion: list[str]) -> dict[str, str]:
    return {c: ("champion" if c in champion else "shadow") for c in C.CELL_ORDER}


def live_pointer_block(champion: list[str], *, effective_from: str | None = EFFECTIVE_FROM) -> dict[str, Any]:
    block: dict[str, Any] = {
        "registered": "2026-10-28", "approval_receipt": RECEIPT, "model": C.MODEL_NAME,
        "champion_cells": list(champion), "shadow_cells": [c for c in C.CELL_ORDER if c not in champion],
        "pointer": C.LATEST_RELATIVE.as_posix(), "ledger": C.LIVE_LEDGER_RELATIVE.as_posix(),
        "resolutions_ledger": C.RESOLUTION_LEDGER_RELATIVE.as_posix(),
        "freshness": {"rule": "nyse_trading_calendar", "max_missing_sessions": 1},
        "live_panel_start": C.LIVE_PANEL_START,
        "display_tier": "t0_internal",
    }
    if effective_from:
        block["origin_backfill"] = {"effective_from": effective_from, "pit_grade": "late_capture"}
    return block


def write_contract(root: Path, *, champion: list[str], sha: str | None, content_hash: str | None,
                   effective_from: str | None = EFFECTIVE_FROM,
                   mutate: Callable[[dict[str, Any]], None] | None = None) -> None:
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    contract["live_pointer"] = live_pointer_block(champion, effective_from=effective_from)
    contract["frozen_coefficients"] = {"path": C.COEFFICIENTS_RELATIVE.as_posix(), "sha256": sha,
                                       "content_hash": content_hash}
    if mutate is not None:
        mutate(contract)
    path = root / C.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def write_receipt(root: Path, receipt: str = RECEIPT, decision: str = "V14-D10") -> None:
    path = root / C.APPROVALS_LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"receipt_id": receipt, "decision_id": decision, "approved_at": "2026-10-28T15:33:03+09:00"}
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_superseded_receipts(root: Path) -> None:
    """실원장 꼴 — D10 r1 행 뒤에 r2 행(supersedes: r1). r1 은 더 이상 효력이 없다."""
    path = root / C.APPROVALS_LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"receipt_id": SUPERSEDED_RECEIPT, "decision_id": "V14-D10", "approved_at": "2026-10-28T15:33:03+09:00"},
            {"receipt_id": RECEIPT, "decision_id": "V14-D10", "approved_at": "2026-10-28T15:33:03+09:00",
             "supersedes": SUPERSEDED_RECEIPT}]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")


def frozen_artifact(roles: dict[str, str], *, tweak: float = 0.0) -> dict[str, Any]:
    cells = {}
    for i, spec in enumerate(C.cell_specs()):
        vix = spec["target"] == "vix_conditional"
        cells[spec["name"]] = {
            "model": C.MODEL_NAME, "target": spec["target"], "h": spec["h"],
            **({"K": spec["K"]} if vix else {"theta": spec["theta"]}),
            "condition": spec["condition"], "feature": spec["feature"], "role": roles[spec["name"]],
            "beta": [-1.5 + tweak, 0.6], "mu": [15.0 if vix else 0.10], "sd": [2.5 if vix else 0.03],
            "n_fit": 500, "events_fit": 60, "clim_base_rate": 0.10 + 0.05 * i,
        }
    body = {"schema_version": 1, "model_id": C.MODEL_ID, "model_version": C.MODEL_VERSION, "model": C.MODEL_NAME,
            "cells": cells, "reconciliation": {"pass": True}}
    body["content_hash"] = C.canonical_hash(body)
    return body


def install_frozen(root: Path, roles: dict[str, str], *, tweak: float = 0.0) -> tuple[str, str]:
    artifact = frozen_artifact(roles, tweak=tweak)
    path = root / C.COEFFICIENTS_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()                         # 임시 저장소의 재동결 흉내 — 실저장소에서는 동결 도구가 덮어쓰기를 거부한다
    path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
    return C.sha256_file(path), artifact["content_hash"]


def make_repo(tmp_path: Path, *, champion: list[str] | None = None, pin: bool = True, receipt: bool = True,
              artifact_roles: dict[str, str] | None = None, effective_from: str | None = EFFECTIVE_FROM,
              name: str = "repo") -> Path:
    champion = list(CHAMPION if champion is None else champion)
    root = tmp_path / name
    (root / "data/contracts").mkdir(parents=True)
    shutil.copy(ROOT / CALENDAR_RELATIVE, root / CALENDAR_RELATIVE)
    sha, content_hash = install_frozen(root, artifact_roles or roles_for(champion))
    write_contract(root, champion=champion, sha=sha if pin else None, content_hash=content_hash if pin else None,
                   effective_from=effective_from)
    if receipt:
        write_receipt(root)
    return root


# ── 합성 아카이브 ────────────────────────────────────────────────────────────
def stamp_after(day: str, hour: int = 1, minute: int = 50) -> str:
    """원천 refresh 시각 흉내 — 관측일 다음날 01:50Z."""
    return f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T{hour:02d}:{minute:02d}:00+00:00"


def now_after(day: str) -> datetime:
    """관측일 다음날 05:00Z 발행 — 그 관측일이 마지막 완료 세션이라 신선도 fresh."""
    return datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=5)


class Obs:
    """MarketObservationV2 흉내 — series_id·observation_time·value·available_at·revision_seq + model_dump."""

    def __init__(self, series_id: str, day: str, value: float, *, available_at: str | None = None,
                 revision_seq: int = 1):
        self.series_id = series_id
        self.observation_time = day
        self.value = value
        self.available_at = available_at or stamp_after(day)
        self.revision_seq = revision_seq

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002 — pydantic 시그니처 흉내
        return {"series_id": self.series_id, "observation_time": self.observation_time, "value": self.value,
                "available_at": self.available_at, "revision_seq": self.revision_seq}


def sessions(last_day: str, n: int) -> list[str]:
    from ai_fc.scenario import future_trading_days
    calendar = yaml.safe_load((ROOT / CALENDAR_RELATIVE).read_text(encoding="utf-8"))
    last = date.fromisoformat(last_day)
    days = [d for d in future_trading_days(last - timedelta(days=int(n * 1.7) + 10), n + 200, calendar) if d <= last][-n:]
    assert days[-1] == last, days[-1]
    return [d.isoformat() for d in days]


def quiet_paths(n: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """평온 경로 — VIX 12.5~17.5 (조건 VIX<20 충족) · NASDAQCOM 일간 0.3% 변동(RV21 ≈ 0.05 ≤ θ)."""
    rng = np.random.default_rng(seed)
    vix = 15.0 + 2.0 * np.sin(np.arange(n) / 9.0) + rng.normal(scale=0.2, size=n)
    returns = rng.normal(scale=0.003, size=n)
    returns[0] = 0.0
    ndx = 10000.0 * np.exp(np.cumsum(returns))
    return vix, ndx


def observations(days: list[str], vix: np.ndarray, ndx: np.ndarray) -> list[Obs]:
    out: list[Obs] = []
    for d, v, q in zip(days, vix, ndx):
        out.append(Obs("VIX", d, float(v))); out.append(Obs("NASDAQCOM", d, float(q)))
    return out


def reader(rows: list[Obs]):
    """read_market_observations 의미 그대로 — available_at <= cutoff 필터 뒤 (series, day) 당 revision_seq 최대 행."""
    def read(_root, *, knowledge_cutoff: str | None = None):
        pool = rows
        if knowledge_cutoff is not None:
            cutoff = datetime.fromisoformat(knowledge_cutoff)
            pool = [r for r in pool if datetime.fromisoformat(r.available_at) <= cutoff]
        latest: dict[tuple[str, str], Obs] = {}
        for r in pool:
            key = (r.series_id, r.observation_time)
            if key not in latest or r.revision_seq > latest[key].revision_seq:
                latest[key] = r
        return sorted(latest.values(), key=lambda r: (r.series_id, r.observation_time))
    return read


def install(monkeypatch, module, rows: list[Obs]) -> None:
    """V14 pipeline 모듈의 아카이브 읽기(관측·첫 vintage 색인)를 합성 행으로 바꾼다 — resolve 도 같은 모듈 함수를 쓴다."""
    monkeypatch.setattr(module, "read_market_observations", reader(rows))
    monkeypatch.setattr(module, "read_market_facts", lambda _root: list(rows))


def upto(rows: list[Obs], day: str) -> list[Obs]:
    return [r for r in rows if r.observation_time <= day]


def replace(rows: list[Obs], series_id: str, day: str, **changes) -> list[Obs]:
    """(series, day) 행 하나만 바꾼 사본 — 값은 그대로 두고 available_at 등만 바꿀 때 쓴다(V13 백필 테스트 _replace 와 같다)."""
    out: list[Obs] = []
    for o in rows:
        if o.series_id == series_id and o.observation_time == day:
            out.append(Obs(series_id, day, changes.pop("value", o.value), **changes))
        else:
            out.append(o)
    return out


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
