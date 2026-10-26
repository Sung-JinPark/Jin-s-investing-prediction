"""V13-D12 원점 백필(앞으로만·late_capture) — 되감은 cutoff · 원점 절단 · 멱등 · effective_from 경계 · 개정 · unfillable · verify 규칙.

계약 origin_backfill(2026-10-22): publish_latest 가 패널 마지막 날짜 1개만 기록하므로 refresh 가 하루 늦으면 그 사이
원점은 행이 없다. 백필 행의 p 는 그 원점 관측의 첫 vintage available_at 으로 되감은 정보집합만의 함수여야 한다.
아카이브의 captured_forward 행은 available_at 이 영수증 수집 시각이라 한 refresh 로 들어온 여러 세션이 같은 시각을
갖는다 — 그래서 패널은 원점에서 절단한다(end=origin). 결손은 어떤 계수 sha 로도 행이 없는 원점이다(forward_only).
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

from ai_fc.forecast_refresh import V13_POINTER, _v13_semantics, v13_pointer_changed
from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import features as F
from ai_fc.timeseries_v13 import pipeline as P
from test_timeseries_v13_pipeline import CALENDAR_RELATIVE, ROOT, _repo

# 2026-10-22(목) = 계약 effective_from. 10-23 금 · 10-26 월 · 10-27 화 — 전부 NYSE 거래일.
D0, D1, D2, D3 = "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"
EFFECTIVE_FROM = "2026-10-22"
OLD_SHA = "0" * 64                                     # 재동결 전 계수 sha 흉내(핀과 다르기만 하면 된다)


def _available_at(day: str, hour: int = 1, minute: int = 50) -> str:
    """원천 refresh 시각 흉내 — 관측일 다음날 01:50Z(실제 아카이브의 VIX·NASDAQCOM 수집 시각과 같은 꼴)."""
    return f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T{hour:02d}:{minute:02d}:00+00:00"


def _now(day: str) -> datetime:
    """관측일 다음날 05:00Z 발행 — 그 관측일이 마지막 완료 세션이라 신선도 fresh."""
    return datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time(),
                            tzinfo=timezone.utc) + timedelta(hours=5)


class _Obs:
    """MarketObservationV2 흉내 — 파이프라인이 읽는 속성(series_id·observation_time·available_at·revision_seq) + model_dump."""

    def __init__(self, series_id: str, day: str, value: float, *, available_at: str | None = None,
                 revision_seq: int = 1):
        self.series_id = series_id
        self.observation_time = day
        self.value = value
        self.available_at = available_at or _available_at(day)
        self.revision_seq = revision_seq

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002 — pydantic 시그니처 흉내
        return {"series_id": self.series_id, "observation_time": self.observation_time, "value": self.value,
                "available_at": self.available_at, "revision_seq": self.revision_seq}


def _observations(last_day: str, n: int = 420) -> list[_Obs]:
    calendar = yaml.safe_load((ROOT / CALENDAR_RELATIVE).read_text(encoding="utf-8"))
    from ai_fc.scenario import future_trading_days
    last = date.fromisoformat(last_day)
    days = [d for d in future_trading_days(last - timedelta(days=int(n * 1.6)), n + 200, calendar) if d <= last][-n:]
    assert days[-1] == last, days[-1]
    rng = np.random.default_rng(11)
    vix = 15 + np.abs(np.cumsum(rng.normal(scale=0.4, size=len(days))))
    ndx = 10000 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(days))))
    out: list[_Obs] = []
    for d, v, q in zip(days, vix, ndx):
        out.append(_Obs("VIX", d.isoformat(), float(v))); out.append(_Obs("NASDAQCOM", d.isoformat(), float(q)))
    return out


def _reader(rows: list[_Obs]):
    """read_market_observations 의미 그대로 — available_at <= cutoff 필터 뒤 (series, day) 당 revision_seq 최대 행."""
    def read(_root, *, knowledge_cutoff: str | None = None):
        pool = rows
        if knowledge_cutoff is not None:
            cutoff = datetime.fromisoformat(knowledge_cutoff)
            pool = [r for r in pool if datetime.fromisoformat(r.available_at) <= cutoff]
        latest: dict[tuple[str, str], _Obs] = {}
        for r in pool:
            key = (r.series_id, r.observation_time)
            if key not in latest or r.revision_seq > latest[key].revision_seq:
                latest[key] = r
        return sorted(latest.values(), key=lambda r: (r.series_id, r.observation_time))
    return read


def _install(monkeypatch, rows: list[_Obs], *, facts: list[_Obs] | None = None) -> None:
    """실제 아카이브처럼 observations·facts 는 같은 파일이다. facts 를 따로 주는 것은 원천 불일치 흉내(도달 불가 경로 고정)뿐."""
    monkeypatch.setattr(P, "read_market_observations", _reader(rows))
    monkeypatch.setattr(P, "read_market_facts", lambda _root: list(rows if facts is None else facts))   # dedupe 전 전량


def _upto(rows: list[_Obs], day: str) -> list[_Obs]:
    return [r for r in rows if r.observation_time <= day]


def _replace(rows: list[_Obs], series_id: str, day: str, **changes) -> list[_Obs]:
    """(series, day) 행 하나만 바꾼 사본 — 값은 그대로, available_at 등만 바꿀 때 쓴다."""
    out: list[_Obs] = []
    for o in rows:
        if o.series_id == series_id and o.observation_time == day:
            out.append(_Obs(series_id, day, changes.pop("value", o.value), **changes))
        else:
            out.append(o)
    return out


def _rows(root: Path) -> list[dict]:
    return [json.loads(l) for l in (root / C.LIVE_LEDGER_RELATIVE).read_text(encoding="utf-8").splitlines() if l]


def _write_rows(root: Path, rows: list[dict]) -> None:
    (root / C.LIVE_LEDGER_RELATIVE).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                               encoding="utf-8", newline="\n")


def _pointer(root: Path) -> dict:
    return json.loads((root / C.LATEST_RELATIVE).read_text(encoding="utf-8"))


def _write_pointer(root: Path, pointer: dict) -> None:
    """포인터 변조 흉내 — content_hash 를 다시 맞춰 validate_latest 는 통과시키고 verify 규칙만 시험한다."""
    body = {k: v for k, v in pointer.items() if k != "content_hash"}
    body["content_hash"] = C.canonical_hash(body)
    (root / C.LATEST_RELATIVE).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def _as_sha(row: dict, sha: str) -> dict:
    """원장 행을 다른 계수 sha 아래 행으로 바꾼 사본(run_id·content_hash 재계산) — 재동결 전 행 흉내."""
    body = {k: v for k, v in row.items() if k != "content_hash"}
    body["coefficients_sha256"] = sha
    body["run_id"] = f"v13vol-{row['as_of']}-{sha[:8]}"
    body["content_hash"] = C.canonical_hash(body)
    return body


def _set_effective_from(root: Path, day: str) -> None:
    path = root / C.CONTRACT_RELATIVE
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    contract["origin_backfill"]["effective_from"] = day
    path.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _p_map(row: dict) -> dict[str, float]:
    return {name: cell["p"] for name, cell in row["cells"].items()}


def _timely_row(tmp_path: Path, monkeypatch, archive: list[_Obs], day: str, *, tag: str = "") -> dict:
    """같은 아카이브를 제때(다음날 05:00Z) 발행했을 때의 정상 행 — 백필 행의 대조군."""
    root = _repo(tmp_path / f"timely-{day}{tag}")
    _install(monkeypatch, _upto(archive, day))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(day))["status"] == "live"
    return _rows(root)[-1]


def test_contract_effective_from_is_registered() -> None:
    contract = yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    assert str(contract["origin_backfill"]["effective_from"]) == EFFECTIVE_FROM
    assert contract["origin_backfill"]["pit_grade"] == "late_capture"
    assert contract["origin_backfill"]["direction"] == "forward_only"
    # 문면이 코드와 같은 규칙을 말한다: 원점 절단 · sha 무관 결손 · 개정은 cutoff 기준 · 포인터에는 재유도 가능한 것만
    assert "end=origin" in contract["origin_backfill"]["pit_rule"]
    assert "available_at > backfill_cutoff_used" in contract["origin_backfill"]["pit_rule"]
    assert "어떤 계수 sha 로도 행이 없는 원점" in contract["origin_backfill"]["mechanics"]
    assert "unfillable not reproducible" in contract["origin_backfill"]["verify_rules"][3]


def test_missed_origin_is_backfilled_with_rolled_back_cutoff_and_is_idempotent(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    first = P.publish_latest_timeseries_v13_vol(root, now=_now(D0))
    assert first["status"] == "live" and first["as_of"] == D0
    assert first["backfilled"] == [] and first["unfillable"] == [] and first["late_capture_rows_total"] == 0
    assert _pointer(root)["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    # refresh 가 하루 늦어 D1 발행이 없었고 D2 자료까지 한꺼번에 들어온 뒤의 발행
    _install(monkeypatch, full)
    second = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert second["status"] == "live" and second["as_of"] == D2 and second["ledger_appended"] is True
    assert second["backfilled"] == [D1] and second["unfillable"] == [] and second["late_capture_rows_total"] == 1
    rows = _rows(root)
    assert [r["as_of"] for r in rows] == [D0, D1, D2]
    normal_d0, late, normal_d2 = rows
    assert "pit_grade" not in normal_d0 and "pit_grade" not in normal_d2, "정상 행에는 pit_grade 가 없다"
    assert late["pit_grade"] == "late_capture"
    assert late["backfill_cutoff_used"] == _available_at(D1)
    assert late["late_capture_sessions"] == 1
    assert late["captured_by_run"] == normal_d2["run_id"] == f"v13vol-{D2}-{normal_d2['coefficients_sha256'][:8]}"
    assert late["run_id"] == f"v13vol-{D1}-{late['coefficients_sha256'][:8]}"
    assert late["knowledge_cutoff"] == normal_d2["knowledge_cutoff"]
    assert late["backfill_cutoff_used"] <= late["knowledge_cutoff"]
    pointer = _pointer(root)
    assert late["pointer_content_hash"] == normal_d2["pointer_content_hash"] == pointer["content_hash"]
    assert pointer["as_of"] == D2, "포인터는 여전히 현재 as_of 1개만 가리킨다"
    # 포인터 backfill 블록에는 매 실행 다시 유도되는 것만 — 실행별 산출(written·누적 수)은 반환값에만 있다
    assert pointer["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    body = {k: v for k, v in late.items() if k != "content_hash"}
    assert C.canonical_hash(body) == late["content_hash"]
    # 되감은 cutoff 의 p·inputs == 제때 발행했을 때의 값 (쓰는 시각만 늦고 아는 것은 같다)
    timely = _timely_row(tmp_path, monkeypatch, full, D1)
    assert _p_map(late) == _p_map(timely) and late["inputs"] == timely["inputs"]
    # 멱등: 재실행 → 행 추가 0, backfilled 비어 있음, total 유지
    _install(monkeypatch, full)
    again = P.publish_latest_timeseries_v13_vol(root, now=_now(D2) + timedelta(hours=1))
    assert again["status"] == "live" and again["ledger_appended"] is False and again["backfilled"] == []
    assert again["late_capture_rows_total"] == 1
    assert len(_rows(root)) == 3
    assert _pointer(root)["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]


def test_noop_run_after_a_backfill_leaves_pointer_semantics_unchanged(tmp_path, monkeypatch) -> None:
    """[F24] 백필 다음 실행은 '빈 실행 기록'만으로 포인터가 바뀌면 안 된다 — 라이브 워크플로가 숫자 변화 없는 포인터를 커밋한다."""
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    _install(monkeypatch, full)
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D2))["backfilled"] == [D1]
    after_backfill = _pointer(root)
    assert "written" not in after_backfill["backfill"] and "late_capture_rows_total" not in after_backfill["backfill"]
    # 워크플로가 보는 비교 그대로: HEAD 포인터(백필 실행) vs 다음 실행(시계만 다름)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", V13_POINTER], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "fixture"], check=True)
    noop = P.publish_latest_timeseries_v13_vol(root, now=_now(D2) + timedelta(hours=2))
    assert noop["backfilled"] == [] and noop["ledger_appended"] is False
    after_noop = _pointer(root)
    assert after_noop["knowledge_cutoff"] != after_backfill["knowledge_cutoff"], "시계는 움직였다"
    assert _v13_semantics(after_noop) == _v13_semantics(after_backfill)
    assert v13_pointer_changed(root) is False


def test_batch_captured_origin_is_fillable_by_truncating_the_panel_at_the_origin(tmp_path, monkeypatch) -> None:
    """[F6] 실제 아카이브: captured_forward 행의 available_at 은 영수증 수집 시각이라 늦은 refresh 가 D1·D2 를 한 영수증으로
    잡으면 둘의 시각이 같다. 되감은 cutoff 로 읽은 패널은 D2 까지 들어오지만 원점에서 절단하면 D1 에서 끝난다 — 채울 수 있다.
    피처는 t 이하만 쓰므로 p 는 D1 자료만 제때 가졌을 때와 같다(09-23·10-16 꼴의 영구 결손이 여기서 사라진다).
    """
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    # D1 의 VIX·NASDAQCOM 이 D2 자료와 같은 영수증(같은 available_at)으로 들어왔다
    one_receipt = _replace(_replace(full, "VIX", D1, available_at=_available_at(D2)),
                           "NASDAQCOM", D1, available_at=_available_at(D2))
    _install(monkeypatch, one_receipt)
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1] and result["unfillable"] == []
    late = _rows(root)[1]
    assert late["as_of"] == D1 and late["pit_grade"] == "late_capture"
    assert late["backfill_cutoff_used"] == _available_at(D2), "cutoff 는 영수증 시각 — D2 세션도 그 안에 있다"
    # 되감은 cutoff 의 (절단 전) 패널은 D2 에서 끝난다 — 절단이 없었다면 as_of_drift 로 영구 결손이었다
    untruncated = F.build_panel(_reader(one_receipt)(root, knowledge_cutoff=late["backfill_cutoff_used"]),
                                start=P.HISTORY_START)
    assert str(untruncated["dates"][-1]) == D2
    # p·inputs 는 D1 자료를 제때 가졌을 때와 같다(값은 같고 스탬프만 늦다)
    timely = _timely_row(tmp_path, monkeypatch, full, D1)
    assert _p_map(late) == _p_map(timely) and late["inputs"] == timely["inputs"]
    _install(monkeypatch, one_receipt)
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]
    assert verify["unfillable_disclosed"] == []


def test_origin_missing_from_its_own_cutoff_panel_is_unfillable_and_verify_fails_closed(tmp_path, monkeypatch) -> None:
    """as_of_drift 는 이제 원점 관측 자체가 되감은 cutoff 패널에 없을 때만 남는다. 실제 아카이브는 facts 와 observations 가
    같은 파일이라 이 경로는 원천 불일치(첫 빈티지 색인은 이른 시각, 관측 읽기는 늦은 시각)에서만 열린다 — fail-closed 를 고정한다.

    계약: unfillable 은 포인터 블록에 기록하고 행을 쓰지 않는다. verify 는 기록을 다시 유도해 공시하고, 기록 없이 빠진 원점은 실패.
    """
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    late_vix = _replace(full, "VIX", D1, available_at=_available_at(D2))     # 관측 읽기: D1 VIX 는 D2 시각에야 보인다
    _install(monkeypatch, late_vix, facts=full)                               # 첫 빈티지 색인: D1 VIX 가 D1 시각에 있었다고 말한다
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "live" and result["backfilled"] == []
    assert result["unfillable"] == [{"origin": D1, "reason": "as_of_drift"}]
    assert [r["as_of"] for r in _rows(root)] == [D0, D2]
    pointer = _pointer(root)
    assert pointer["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": [{"origin": D1, "reason": "as_of_drift"}]}
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]
    assert verify["unfillable_disclosed"] == [{"origin": D1, "reason": "as_of_drift"}]
    # 포인터 기록을 지우면(기록 없는 결손) 같은 원장이 완전성 규칙에 걸린다
    pointer["backfill"]["unfillable"] = []
    _write_pointer(root, pointer)
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["errors"] == [f"backfill incomplete: {D1}"]


def test_verify_rejects_a_pointer_unfillable_entry_for_a_fillable_origin(tmp_path, monkeypatch) -> None:
    """[F7] 포인터의 backfill.unfillable 은 자기 주장이다 — verify 가 아카이브에서 다시 유도해 채울 수 있는 원점이면 실패."""
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    _install(monkeypatch, full)
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D2))["backfilled"] == [D1]
    rows = _rows(root)
    assert P.verify_timeseries_v13_vol(root)["ok"] is True
    # D1 행을 지우고 포인터에 'D1 은 채울 수 없었다' 고 적는다 — 아카이브로는 채울 수 있는 원점이다
    _write_rows(root, [r for r in rows if r["as_of"] != D1])
    pointer = _pointer(root)
    pointer["backfill"]["unfillable"] = [{"origin": D1, "reason": "as_of_drift"}]
    _write_pointer(root, pointer)
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is False
    assert verify["errors"] == [f"unfillable not reproducible: {D1}"]
    assert verify["unfillable_disclosed"] == [], "채울 수 있는 원점은 공시 목록에 오르지 않는다"
    # 행을 되돌리면 통과(verify 는 읽기만 한다) — 포인터의 거짓 기록은 행이 있으면 참조되지 않는다
    _write_rows(root, rows)
    assert P.verify_timeseries_v13_vol(root)["ok"] is True


def test_hold_pointer_carries_an_empty_backfill_block(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path, armed=False)
    _install(monkeypatch, _observations(D2))
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "hold" and result["backfilled"] == [] and result["unfillable"] == []
    assert result["late_capture_rows_total"] == 0
    pointer = _pointer(root)
    assert pointer["backfill"] == {"effective_from": EFFECTIVE_FROM, "unfillable": []}
    assert "cells" not in pointer and not (root / C.LIVE_LEDGER_RELATIVE).exists()


def test_origins_before_effective_from_are_never_backfilled(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    _set_effective_from(root, D1)                       # D0 는 경계 앞 · D1·D2 는 경계 안 · D3 가 현재 as_of
    _install(monkeypatch, _observations(D3))
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D3))
    assert result["status"] == "live" and result["as_of"] == D3
    assert result["backfilled"] == [D1, D2] and result["unfillable"] == [] and result["late_capture_rows_total"] == 2
    rows = _rows(root)
    assert [r["as_of"] for r in rows] == [D1, D2, D3]
    assert D0 not in {r["as_of"] for r in rows}, "effective_from 앞 원점은 소급하지 않는다"
    assert [r["late_capture_sessions"] for r in rows[:2]] == [2, 1]
    assert {r["captured_by_run"] for r in rows[:2]} == {rows[2]["run_id"]}
    assert _pointer(root)["backfill"] == {"effective_from": D1, "unfillable": []}
    verify = P.verify_timeseries_v13_vol(root)         # 완전성도 effective_from 부터만 본다
    assert verify["ok"] is True, verify["errors"]


def test_origin_with_a_row_under_an_old_sha_is_not_a_gap(tmp_path, monkeypatch) -> None:
    """[F8] 결손은 '어떤 계수 sha 로도 행이 없는 원점' — 재동결 뒤 옛 sha 정상 행이 있는 원점은 새 sha 로 다시 채점하지 않는다
    (forward_only). verify 완전성도 sha 무관으로 세고, 같은 (원점, sha) 가 둘일 때만 중복 오류다(2026-09-04 재동결 꼴은 정상).
    """
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    d0_pinned = _rows(root)[0]
    d0_old = _as_sha(d0_pinned, OLD_SHA)                 # D0 는 재동결 전 계수로 제때 발행된 원점
    _write_rows(root, [d0_old])
    _install(monkeypatch, full)
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1] and result["unfillable"] == []
    rows = _rows(root)
    assert [(r["as_of"], r["coefficients_sha256"] == OLD_SHA, r.get("pit_grade")) for r in rows] == \
        [(D0, True, None), (D1, False, "late_capture"), (D2, False, None)]
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]
    # 멱등: 재실행해도 D0 는 여전히 결손이 아니다
    again = P.publish_latest_timeseries_v13_vol(root, now=_now(D2) + timedelta(hours=1))
    assert again["backfilled"] == [] and len(_rows(root)) == 3
    # 재동결 꼴 — 같은 원점에 sha 가 다른 행 하나씩은 정상
    _write_rows(root, [d0_old, d0_pinned, rows[1], rows[2]])
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]
    # 같은 (원점, sha) 행이 둘이면 중복 오류
    d0_old_dup = dict(d0_old); d0_old_dup["run_id"] = "v13vol-dup"
    d0_old_dup = {k: v for k, v in d0_old_dup.items() if k != "content_hash"}
    d0_old_dup["content_hash"] = C.canonical_hash(d0_old_dup)
    _write_rows(root, [d0_old, d0_old_dup, rows[1], rows[2]])
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is False
    assert f"ledger has 2 rows for origin {D0}/coefficients {OLD_SHA[:8]} (expected 1)" in verify["errors"]


def test_nasdaqcom_revision_after_first_capture_does_not_change_backfilled_p(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    # D1 NASDAQCOM 개정: 첫 수집(D1 다음날 01:50Z) 뒤 10-25T12:00Z 에 +3% 값(revision_seq=2)이 들어온다
    original = next(o for o in full if o.series_id == "NASDAQCOM" and o.observation_time == D1)
    revised = _Obs("NASDAQCOM", D1, original.value * 1.03, available_at="2026-10-25T12:00:00+00:00", revision_seq=2)
    _install(monkeypatch, full + [revised])
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1]
    late = _rows(root)[1]
    assert late["pit_grade"] == "late_capture" and late["backfill_cutoff_used"] == _available_at(D1), \
        "cutoff 는 첫 vintage 의 available_at — 개정의 available_at 이 아니다"
    # 되감은 정보집합 == 제때 발행(개정 전)의 정보집합
    timely = _timely_row(tmp_path, monkeypatch, full, D1)
    assert _p_map(late) == _p_map(timely) and late["inputs"] == timely["inputs"]
    # 개정을 포함한 패널이었다면 RV 입력·p 가 달라진다 — 되감기가 실제로 개정을 배제했음을 보인다
    revised_panel = F.build_panel(_reader(full + [revised])(root, knowledge_cutoff=late["knowledge_cutoff"]),
                                  start=P.HISTORY_START, end=D1)
    assert str(revised_panel["dates"][-1]) == D1
    frozen = json.loads((root / C.COEFFICIENTS_RELATIVE).read_text(encoding="utf-8"))
    revised_cells, revised_inputs = P.compute_cells(frozen, revised_panel)
    assert revised_inputs["rv21_ann"] != late["inputs"]["rv21_ann"]
    assert revised_cells["rv_h5"]["p"] != late["cells"]["rv_h5"]["p"]
    # verify 도 개정이 있는 아카이브에서 되감은 cutoff 로 재계산해 통과한다
    _install(monkeypatch, full + [revised])
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]


def test_nasdaqcom_revision_arriving_before_the_vix_first_capture_is_inside_the_cutoff(tmp_path, monkeypatch) -> None:
    """[F13] cutoff 는 계열별 첫 빈티지의 **최댓값**이다. 같은 밤 NASDAQCOM 개정이 VIX 첫 수집보다 먼저 도착하면 그 개정은
    cutoff 안에 있고 max-revision dedupe 로 선택된다 — 제때 발행이 그 cutoff 에서 보았을 것과 같다. 개정이 '자동 제외'되는
    것이 아니라 available_at > cutoff 인 개정만 제외된다는 것을 p 로 고정한다.
    """
    root = _repo(tmp_path)
    full = _observations(D2)
    original = next(o for o in full if o.series_id == "NASDAQCOM" and o.observation_time == D1)
    # D1 NASDAQCOM: 첫 빈티지 01:00Z → 개정(+3%) 01:30Z → VIX 첫 수집 01:50Z(기본값). cutoff_used = 01:50Z
    archive = _replace(full, "NASDAQCOM", D1, available_at=_available_at(D1, 1, 0))
    revised = _Obs("NASDAQCOM", D1, original.value * 1.03, available_at=_available_at(D1, 1, 30), revision_seq=2)
    archive = archive + [revised]
    _install(monkeypatch, _upto(archive, D0))
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D0))["status"] == "live"
    _install(monkeypatch, archive)
    result = P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    assert result["status"] == "live" and result["backfilled"] == [D1]
    late = _rows(root)[1]
    assert late["backfill_cutoff_used"] == _available_at(D1), "VIX 첫 수집(01:50Z)이 최댓값 — 개정(01:30Z)은 그 안이다"
    # 기대값: 같은 아카이브를 제때 발행했을 때(개정 포함)와 같고, 개정 없는 아카이브의 제때 발행과는 다르다
    timely_with_revision = _timely_row(tmp_path, monkeypatch, archive, D1, tag="-rev")
    timely_without_revision = _timely_row(tmp_path, monkeypatch, full, D1, tag="-norev")
    assert _p_map(late) == _p_map(timely_with_revision) and late["inputs"] == timely_with_revision["inputs"]
    assert late["inputs"]["rv21_ann"] != timely_without_revision["inputs"]["rv21_ann"]
    assert late["cells"]["rv_h5"]["p"] != timely_without_revision["cells"]["rv_h5"]["p"]
    _install(monkeypatch, archive)
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is True, verify["errors"]


def test_verify_backfill_rules_detect_missing_and_tampered_late_capture_rows(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    full = _observations(D2)
    _install(monkeypatch, _upto(full, D0))
    P.publish_latest_timeseries_v13_vol(root, now=_now(D0))
    _install(monkeypatch, full)
    assert P.publish_latest_timeseries_v13_vol(root, now=_now(D2))["backfilled"] == [D1]
    rows = _rows(root)
    assert P.verify_timeseries_v13_vol(root)["ok"] is True
    late_id = rows[1]["run_id"]
    # 완전성: late_capture 행을 지우면 D1 원점이 빈다
    _write_rows(root, [r for r in rows if r.get("pit_grade") != "late_capture"])
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is False and f"backfill incomplete: {D1}" in verify["errors"]
    # 재계산: late_capture 셀 p 변조 → 되감은 cutoff 재계산 불일치 (+ 행 해시 깨짐)
    tampered = json.loads(json.dumps(rows))
    tampered[1]["cells"]["rv_h5"]["p"] = 0.999
    _write_rows(root, tampered)
    verify = P.verify_timeseries_v13_vol(root)
    assert verify["ok"] is False
    assert f"late_capture cell rv_h5 recompute mismatch: {late_id}" in verify["errors"]
    assert any("hash mismatch" in e for e in verify["errors"])
    # 규칙 3: cutoff 가 발행 시각 뒤 · 세션 수 0 · effective_from 앞 원점 — 전부 개별 오류
    bad = json.loads(json.dumps(rows))
    bad[1]["late_capture_sessions"] = 0
    bad[1]["backfill_cutoff_used"] = "2026-10-28T00:00:00+00:00"
    bad[1]["as_of"] = "2026-10-21"
    _write_rows(root, bad)
    errors = P.verify_timeseries_v13_vol(root)["errors"]
    assert f"late_capture cutoff after publication: {late_id}" in errors
    assert f"late_capture sessions < 1: {late_id}" in errors
    assert f"late_capture before effective_from: {late_id}" in errors
    assert f"backfill incomplete: {D1}" in errors
    # 원장을 원상 복구하면 다시 통과한다 (verify 는 읽기만 한다)
    _write_rows(root, rows)
    assert P.verify_timeseries_v13_vol(root)["ok"] is True


def test_publish_does_not_mutate_normal_row_schema(tmp_path, monkeypatch) -> None:
    """정상 행의 키 집합은 백필 도입 전과 같다 — 기존 원장 행 해시와 호환."""
    root = _repo(tmp_path)
    _install(monkeypatch, _observations(D2))
    P.publish_latest_timeseries_v13_vol(root, now=_now(D2))
    row = _rows(root)[-1]
    assert set(row) == {"schema_version", "run_id", "as_of", "knowledge_cutoff", "model_id", "finalist_id",
                        "coefficients_sha256", "inputs", "cells", "pointer_content_hash", "holdout_status",
                        "content_hash"}
