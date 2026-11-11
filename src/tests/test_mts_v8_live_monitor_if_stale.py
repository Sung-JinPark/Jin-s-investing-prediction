"""U1 — v8-live-monitor --if-stale: 입력 지문 결정론·민감도, 건너뛰기 결정, 다른 verb 거부.

쓰기는 tmp_path 사본에만. 실저장소는 읽기만 한다. 표시 진단 전용 — 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_fc.mts_research import cli as research_cli
from ai_fc.mts_research import v8_live_monitor as M
from ai_fc.mts_research.artifacts import append_event
from ai_fc.mts_research.monitor_thresholds import PINNED_THRESHOLD_HASH, THRESHOLDS_RELATIVE

ROOT = Path(__file__).resolve().parents[2]


def _context(stage: str = "provisional", resolution: str = "a") -> SimpleNamespace:
    return SimpleNamespace(as_of=date(2026, 11, 9), resolutions=[{"resolution_id": resolution}],
                           xnas_rows=[{"diagnostic_key": f"k-{stage}"}])


def _root(tmp_path: Path, *, sealed: bytes | None) -> Path:
    root = tmp_path / "repo"
    target = root / THRESHOLDS_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / THRESHOLDS_RELATIVE, target)
    if sealed is not None:
        path = root / M.SEALED_LEDGER
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sealed)
    return root


def test_fingerprint_deterministic_and_input_sensitive(tmp_path, monkeypatch):
    for case, sealed in (("with", b'{"x":1}\n'), ("without", None)):
        root = _root(tmp_path / case, sealed=sealed)
        first = M.input_fingerprint(_context(), root)
        assert first == M.input_fingerprint(_context(), root)
        assert first != M.input_fingerprint(_context(stage="confirmed"), root)
        assert first != M.input_fingerprint(_context(resolution="b"), root)
    root = _root(tmp_path / "bytes", sealed=b'{"x":1}\n')
    before = M.input_fingerprint(_context(), root)
    (root / M.SEALED_LEDGER).write_bytes(b'{"x":2}\n')
    assert M.input_fingerprint(_context(), root) != before
    after_sealed = M.input_fingerprint(_context(), root)
    monkeypatch.setattr(M, "_FINGERPRINT_CODE", ("v8_live_monitor.py",))
    assert M.input_fingerprint(_context(), root) != after_sealed


def _skip_root(tmp_path: Path, fingerprint: str) -> Path:
    root = _root(tmp_path, sealed=None)
    append_event(root, M.LEDGER_RELATIVE, {"monitor_id": "v8lm-x-v1", "status": "ok"})
    derived = root / M.DERIVED_RELATIVE
    derived.parent.mkdir(parents=True, exist_ok=True)
    derived.write_text(json.dumps({"input_fingerprint": fingerprint, "status": "ok",
                                   "threshold_hash": PINNED_THRESHOLD_HASH, "monitor_id": "v8lm-x-v1"}),
                       encoding="utf-8")
    return root


def _ns(**overrides) -> argparse.Namespace:
    body = {"append": True, "if_stale": True, "now": "2026-11-11T12:00:00+00:00", "as_of": None}
    body.update(overrides)
    return argparse.Namespace(**body)


def test_if_stale_skips_when_fingerprint_matches(tmp_path, monkeypatch):
    stub = _context()
    monkeypatch.setattr(M, "_load_context", lambda root, *, now, as_of, resolution_ids=None: stub)

    def _never(*args, **kwargs):
        raise AssertionError("run_monitor must not run when inputs are unchanged")

    monkeypatch.setattr(M, "run_monitor", _never)
    root = _skip_root(tmp_path, M.input_fingerprint(stub, tmp_path / "repo"))
    code, payload = M.run_cli(root, _ns())
    assert code == 0 and payload["mode"] == "skipped_up_to_date"
    assert payload["as_of_session"] == "2026-11-09" and payload["display_only"] is True


class _Called(RuntimeError):
    pass


def test_if_stale_recomputes_when_fingerprint_differs(tmp_path, monkeypatch):
    stub = _context()
    monkeypatch.setattr(M, "_load_context", lambda root, *, now, as_of, resolution_ids=None: stub)

    def _called(*args, **kwargs):
        raise _Called()

    monkeypatch.setattr(M, "run_monitor", _called)
    root = _skip_root(tmp_path, "0" * 64)
    with pytest.raises(_Called):
        M.run_cli(root, _ns())
    # derived 행이 원장에 없으면(다른 monitor_id) 같은 지문이어도 재계산
    root2 = _skip_root(tmp_path / "b", M.input_fingerprint(stub, tmp_path / "b" / "repo"))
    derived = root2 / M.DERIVED_RELATIVE
    payload = json.loads(derived.read_text(encoding="utf-8"))
    payload["monitor_id"] = "v8lm-y-v1"
    derived.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(_Called):
        M.run_cli(root2, _ns())
    # --if-stale 없이는 항상 재계산
    with pytest.raises(_Called):
        M.run_cli(_skip_root(tmp_path / "c", M.input_fingerprint(stub, tmp_path / "c" / "repo")),
                  _ns(if_stale=False))


def test_if_stale_rejected_on_other_verbs(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        research_cli.main(["--root", str(tmp_path), "coherence-monitor", "--if-stale"])
    assert excinfo.value.code == 2
