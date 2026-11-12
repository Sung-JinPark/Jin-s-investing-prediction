"""닷컴 정점 대비 부문별 프로필 — 합치지 않는다, 닫힐 때 닫힌다, 계약 지문에 묶인다 (네트워크·원장 없음)."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ai_fc import dotcom_overheat_profile as prof
from ai_fc import dotcom_overheat_v6 as v6
from ai_fc.overheat_watchdog import check_profile
from test_dotcom_overheat_v6 import contract, inp  # noqa: F401  (fixtures — 합성 원장과 그 위의 동결 블록)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc)
PROFILE_CONTRACT = yaml.safe_load((ROOT / prof.CONTRACT_RELATIVE).read_text(encoding="utf-8"))
FORBIDDEN_KEYS = {"index", "index_raw", "mean", "average", "weight", "weights", "band", "rank", "tone"}


def _root(tmp_path: Path, source: dict, *, pin: dict | None = None) -> Path:
    """합성 원천 계약과, 그 편입 지문을 적은 프로필 계약을 임시 저장소에 둔다."""
    path = tmp_path / v6.CONTRACT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(source, allow_unicode=True, sort_keys=False), encoding="utf-8")
    profile = copy.deepcopy(PROFILE_CONTRACT)
    profile["source_admission_sha256"] = prof.admission_digest(pin or source)
    (tmp_path / prof.CONTRACT_RELATIVE).write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in _keys(value)}
    return set()


def test_profile_scores_each_admitted_indicator_and_never_combines(tmp_path: Path, inp, contract) -> None:  # noqa: F811
    root = _root(tmp_path, contract)
    out = prof.build_profile(root, now=NOW, inp=inp)
    assert out["status"] == "ok" and out["composite"] is None
    assert out["probability_space"] == "reference_only" and out["trading_signal"] is False
    assert not (_keys(out) & FORBIDDEN_KEYS)  # 합·평균·가중·범위·순위·색 등급이 없다
    frozen = contract["frozen"]
    assert [f["id"] for f in out["families"]] == list(contract["families"])
    last = len(inp.sessions) - 1
    for family in out["families"]:
        ids = frozen["members"][family["id"]]
        assert [row["id"] for row in family["indicators"]] == ids
        assert family["status"] == ("ok" if ids else "unmeasured")  # 빈 부문은 0 이 아니라 '없음'
        for row in family["indicators"]:
            anchor = {f: float(frozen["anchors"][row["id"]][f]) for f in ("zero", "peak")}
            item = v6.indicator_value(inp, row["id"], last, v6.Spec(contract, lags=False))
            expected = v6.score(item["value"], anchor)
            assert row["score"] == int(round(expected)) and row["score_raw"] == round(expected, 1)
            assert row["beyond_peak"] == (expected >= 100) and row["below_normal"] == (expected < 0)
            if row["frequency"] in prof.DAILY:
                assert row["high_12m"]["value"] >= row["score"] and "change_4w" in row and "previous" not in row
            else:  # 다음 발표까지 그대로 — 기간과 직전 기간의 점수를 보인다(발표 한 번의 계단을 숨기지 않는다)
                assert "change_4w" not in row and "high_12m" not in row
                assert row["previous"]["period"] < row["period"] and isinstance(row["previous"]["score"], int)
            kind = v6._meta(contract, row["id"])["kind"]
            assert row["zero_is"] == ("return_zero" if kind == "return" else "median_1995_2019")
            assert ("median_1995_2019" in row) == (kind == "return")  # 0 이 평상이 아닌 지표에는 장기 중앙값을 싣는다
    assert out["scored"] == sum(len(ids) for ids in frozen["members"].values())
    assert out["source_admission_sha256"] == prof.admission_digest(contract)
    assert out["max_age_days"] == contract["staleness_limits_days"]["daily"]


def test_profile_closes_on_stale_ledger_drifted_anchor_and_changed_admission(tmp_path: Path, inp, contract,  # noqa: F811
                                                                              monkeypatch) -> None:
    root = _root(tmp_path, contract)
    late = prof.build_profile(root, now=NOW + timedelta(days=30), inp=inp)
    assert late["status"] == "hold" and "NASDAQ ledger" in late["reason"] and "families" not in late

    admitted = sum(contract["frozen"]["members"].values(), [])
    monkeypatch.setattr(v6, "anchor_drift", lambda _inp, _contract: [admitted[0]])
    partial = prof.build_profile(root, now=NOW, inp=inp)
    rows = {row["id"]: row for family in partial["families"] for row in family["indicators"]}
    assert partial["status"] == "ok" and rows[admitted[0]]["status"] == "hold" and "score" not in rows[admitted[0]]
    assert partial["scored"] == len(admitted) - 1
    monkeypatch.setattr(v6, "anchor_drift", lambda _inp, _contract: list(admitted))
    assert prof.build_profile(root, now=NOW, inp=inp)["status"] == "hold"

    moved = copy.deepcopy(contract)  # 원천 계약의 동결 블록이 바뀌면 프로필 계약의 지문과 어긋난다
    moved["frozen"]["anchors"][admitted[0]]["peak"] *= 1.2
    other = tmp_path / "other"
    other.mkdir()
    out = prof.build_profile(_root(other, moved, pin=contract), now=NOW, inp=inp)
    assert out["status"] == "unavailable" and out["composite"] is None


def test_materialized_profile_is_only_served_while_it_is_current(tmp_path: Path, inp, contract, monkeypatch) -> None:  # noqa: F811
    root = _root(tmp_path, contract)
    assert prof.load_profile(root)["reason"] == "profile not generated"
    monkeypatch.setattr(v6, "load_inputs", lambda _root: inp)
    written = prof.materialize(root, now=NOW)
    assert written["status"] == "ok"
    as_of = date.fromisoformat(written["as_of"])
    assert json.loads((root / prof.PROFILE_RELATIVE).read_text(encoding="utf-8")) == written
    assert prof.load_profile(root, today=as_of + timedelta(days=2)) == written
    old = prof.load_profile(root, today=as_of + timedelta(days=40))
    assert old["status"] == "hold" and "families" not in old and old["composite"] is None

    changed = copy.deepcopy(contract)
    changed["frozen"]["anchors"][next(iter(sum(contract["frozen"]["members"].values(), [])))]["zero"] = -9.0
    (root / v6.CONTRACT_RELATIVE).write_text(yaml.safe_dump(changed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert prof.load_profile(root, today=as_of)["reason"] == "profile belongs to another contract state"

    # 계약 쪽 지문을 새 동결에 맞춰 고쳐도, 옛 기준값으로 만든 산출물은 실리지 않는다(산출물에도 지문이 적혀 있다).
    _root(tmp_path, changed)
    assert prof.load_profile(root, today=as_of)["reason"] == "profile belongs to another contract state"
    for broken in ("null", "[]", "{", ""):
        (root / prof.PROFILE_RELATIVE).write_text(broken, encoding="utf-8")
        assert prof.load_profile(root, today=as_of)["status"] == "unavailable"


def test_a_failed_computation_writes_a_closed_profile_instead_of_raising(tmp_path: Path, contract, monkeypatch) -> None:  # noqa: F811
    """표시용 계산이 공식 원장 커밋(같은 워크플로의 다음 단계)을 막으면 안 된다."""
    root = _root(tmp_path, contract)

    def boom(_root: Path):
        raise v6.OverheatV6Error("ledger is missing v6 input series: GDP")

    monkeypatch.setattr(v6, "load_inputs", boom)
    out = prof.materialize(root, now=NOW)
    assert out["status"] == "unavailable" and "OverheatV6Error" in out["reason"] and out["composite"] is None
    assert json.loads((root / prof.PROFILE_RELATIVE).read_text(encoding="utf-8")) == out
    assert prof.load_profile(root)["status"] == "unavailable"
    (root / prof.CONTRACT_RELATIVE).write_text("", encoding="utf-8")  # 계약이 비어도 예외 없이 닫힌다
    assert prof.materialize(root, now=NOW)["status"] == "unavailable"
    assert prof.load_profile(root)["status"] == "unavailable"


def test_watchdog_reports_a_missing_stale_or_combined_profile() -> None:
    ok_row = {"id": "x", "label": "지표", "status": "ok", "score": 10}
    profile = {"status": "ok", "composite": None, "as_of": "2026-11-09", "generated_at": "2026-11-10T00:30:00+00:00",
               "families": [{"id": "speed", "indicators": [ok_row]}]}

    def statuses(found: list[dict]) -> list[tuple[str, str]]:
        return [(row["subject"], row["status"]) for row in found]

    assert statuses(check_profile(None, None, now=NOW)) == [("프로필", "fail")]
    assert statuses(check_profile(profile, None, now=NOW)) == [("프로필", "ok")]
    assert statuses(check_profile(profile, None, now=NOW + timedelta(days=9))) == [("프로필", "fail")]
    assert ("프로필", "fail") in statuses(check_profile({**profile, "composite": 53.4}, None, now=NOW))
    assert statuses(check_profile({"status": "hold", "reason": "x", "composite": None}, None, now=NOW)) == [
        ("프로필", "warn")]
    held = {**profile, "families": [{"id": "speed", "indicators": [ok_row, {"label": "멈춘 지표", "status": "hold"}]}]}
    assert statuses(check_profile(held, None, now=NOW)) == [("프로필", "warn")]
    live_ok = {"dotcom_overheat_profile": profile}
    assert statuses(check_profile(profile, live_ok, now=NOW)) == [("프로필", "ok"), ("사이트 프로필", "ok")]
    assert statuses(check_profile(profile, {}, now=NOW))[-1] == ("사이트 프로필", "warn")
    deploying = {"dotcom_overheat_profile": {**profile, "as_of": "2026-11-06",
                                             "generated_at": "2026-11-09T22:40:00+00:00"}}
    assert statuses(check_profile(profile, deploying, now=NOW))[-1] == ("사이트 프로필", "ok")  # 배포 대기 중
    behind = {"dotcom_overheat_profile": {**profile, "as_of": "2026-11-05",
                                          "generated_at": "2026-11-08T00:30:00+00:00"}}
    assert statuses(check_profile(profile, behind, now=NOW))[-1] == ("사이트 프로필", "warn")
    combined = {"dotcom_overheat_profile": {**profile, "composite": 50}}
    assert statuses(check_profile(profile, combined, now=NOW))[-1] == ("사이트 프로필", "fail")


def test_repository_profile_is_bound_to_the_frozen_admission_and_wired_without_a_composite() -> None:
    source = v6.load_contract(ROOT)
    assert PROFILE_CONTRACT["source_contract"] == source["contract_id"]
    assert PROFILE_CONTRACT["source_admission_sha256"] == prof.admission_digest(source)
    assert PROFILE_CONTRACT["rules"]["no_composite"] is True and PROFILE_CONTRACT["decided_by"] == "user"
    assert PROFILE_CONTRACT["probability_space"] == "reference_only" and PROFILE_CONTRACT["trading_signal"] is False
    assert PROFILE_CONTRACT["display"]["headline_stays"] == "dotcom_overheat_index_v5"
    assert sum(len(ids) for ids in source["frozen"]["members"].values()) == 5
    assert source["frozen"]["verdict"] == "failed"  # 지수는 여전히 닫혀 있다 — 프로필은 지수가 아니다
    assert v6.load_latest(ROOT)["status"] == "unavailable"

    committed = json.loads((ROOT / prof.PROFILE_RELATIVE).read_text(encoding="utf-8"))
    assert committed["composite"] is None and committed["status"] in {"ok", "hold"}
    assert not (_keys(committed) & FORBIDDEN_KEYS)

    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    block = script[script.index("function overheatProfileBlock"):script.index("function statisticsOverheatPanel")]
    assert "합산 지수 아님" in block and "대표값 내역 아님" in block and "미측정" in block
    assert "다른 척도" in block and "overheatTone" not in block and "max_age_days" in block
    assert "reduce(" not in block and "<svg" not in block  # 화면에서도 합치지 않고, 글자는 HTML 로만
    panel = script[script.index("function statisticsOverheatPanel"):script.index("function predictionSectionNav")]
    call = "overheatProfileBlock(DATA.dotcom_overheat_profile)"
    assert panel.count(call) == 1 and panel.index(call) > panel.index('class="oh-grid"')  # v5 분해 뒤, 카드 맨 아래
    assert panel.index(call) < panel.index("</section>") < panel.index("data-oh-jump]")
    board = (ROOT / "src/ai_fc/dashboard.py").read_text(encoding="utf-8")
    assert '"dotcom_overheat_profile": dotcom_overheat_profile' in board
