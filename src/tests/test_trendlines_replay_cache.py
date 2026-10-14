"""Opt-in process-local proof reuse without skipping immutable evidence checks."""

from __future__ import annotations

import runpy
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, engine as E, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE = runpy.run_path(str(REPOSITORY / "src/tests/test_trendlines_research.py"))


@pytest.fixture
def captured(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, path)
    raw = FIXTURE["public_html"]()
    R.capture_html(tmp_path, "bitcoin", raw, FIXTURE["receipt"](raw), as_of=FIXTURE["FETCHED"])
    return tmp_path


@pytest.fixture
def calls(monkeypatch):
    counts = {"prepare": 0, "numeric": 0, "receipt": 0}
    for module, name, key in ((R, "_prepare", "prepare"), (E, "verify_research_asset_snapshot", "numeric"),
                              (R, "_receipt", "receipt")):
        original = getattr(module, name)

        def count(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, count)
    return counts


def evidence(root):
    pointer = S.read_json(root / R.ROOT / "latest.json")
    reference = pointer["assets"]["bitcoin"]
    archive_path = root / reference["snapshot_path"]
    archive = S.read_json(archive_path)
    receipt_path = root / archive["receipt_path"]
    receipt = S.read_json(receipt_path)
    return pointer, archive_path, archive, receipt_path, receipt


def resign_archive(root, archive_path, archive, pointer):
    body = {key: value for key, value in archive.items() if key not in {"snapshot_id", "content_hash"}}
    archive["snapshot_id"] = "research-snapshot-" + C.canonical_hash(body)
    archive = R._hash(archive)
    relative = R.ROOT / "snapshots" / (archive["snapshot_id"] + ".json")
    S.atomic_json(root / relative, archive)
    # Disposable tamper fixture only: imitate a replacement with newly signed IDs.
    archive_path.unlink()
    pointer["assets"]["bitcoin"] = {"snapshot_id": archive["snapshot_id"], "snapshot_path": relative.as_posix(),
                                   "snapshot_sha256": S.digest(archive)}
    S.atomic_json(root / R.ROOT / "latest.json", R._hash(pointer))


def test_default_verifier_and_load_keep_full_numerical_replay(captured, calls):
    R.VerifiedReplayCache()
    assert R.verify(captured, replay=True)["ok"]
    assert R.load_asset_detail(captured, "bitcoin", now=FIXTURE["FETCHED"])
    assert calls == {"prepare": 2, "numeric": 2, "receipt": 2}


def test_opt_in_reuses_only_successful_math_and_rechecks_every_receipt(captured, calls):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        first = R.verify(captured, replay=True)
        second = R.verify(captured, replay=True)
        assert first == second == {"ok": True, "errors": [], "snapshots": 1, "replay": True}
        assert calls == {"prepare": 1, "numeric": 1, "receipt": 2}
    assert cache.entry_count == 1
    assert R.verify(captured, replay=True)["ok"]
    assert calls == {"prepare": 2, "numeric": 2, "receipt": 3}


def test_metadata_only_checks_cannot_seed_or_read_a_full_replay_proof(captured, calls):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured, replay=False)["ok"]
        assert cache.entry_count == 0
        assert R.verify(captured, replay=True)["ok"]
        assert R.verify(captured, replay=False)["ok"]
    assert calls == {"prepare": 3, "numeric": 3, "receipt": 3}


def test_cache_context_resets_after_worker_failure(captured, calls):
    cache = R.VerifiedReplayCache()
    with pytest.raises(RuntimeError, match="worker failed"):
        with R.use_verified_replay_cache(cache):
            assert R.verify(captured)["ok"]
            raise RuntimeError("worker failed")
    assert R.verify(captured)["ok"]
    assert calls["numeric"] == calls["prepare"] == 2
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
    assert calls["numeric"] == calls["prepare"] == 2


def test_append_new_capture_forces_new_math_but_old_exact_archives_are_reused(captured, calls):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        original_counts = dict(calls)
        raw = FIXTURE["public_html"](gap=True)
        stamp = "2024-04-10T02:00:00+00:00"
        result = R.capture_html(captured, "bitcoin", raw, FIXTURE["receipt"](raw, stamp), as_of=stamp)
        assert result["changed"]
        # One new capture build/replay; its archived proof is not pre-seeded.
        assert calls["prepare"] == original_counts["prepare"] + 1
        assert calls["numeric"] == original_counts["numeric"] + 1
        assert R.verify(captured)["ok"]
        assert calls["prepare"] == original_counts["prepare"] + 2
        assert calls["numeric"] == original_counts["numeric"] + 2
        prior = dict(calls)
        assert R.verify(captured)["ok"]
        assert calls["prepare"] == prior["prepare"] and calls["numeric"] == prior["numeric"]
    assert cache.entry_count == 2


@pytest.mark.parametrize("attack", ["raw", "receipt", "archive", "latest", "revision", "failure"])
def test_warm_cache_does_not_hide_corrupt_originals_or_history(captured, calls, attack):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        pointer, path, archive, receipt_path, receipt = evidence(captured)
        if attack == "raw":
            (captured / receipt["raw_path"]).write_bytes(b"changed original")
        elif attack == "receipt":
            receipt["available_at"] = "2024-04-09T00:00:00+00:00"
            S.atomic_json(receipt_path, R._hash(receipt))
        elif attack == "archive":
            archive["bars"][0]["close"] += 0.25
            S.atomic_json(path, R._hash(archive))
        elif attack == "latest":
            pointer["assets"]["bitcoin"]["snapshot_sha256"] = "0" * 64
            S.atomic_json(captured / R.ROOT / "latest.json", R._hash(pointer))
        elif attack == "revision":
            archive["supersedes_snapshot_id"] = "research-snapshot-" + "0" * 64
            resign_archive(captured, path, archive, pointer)
        else:
            failure = {"schema_version": 1, "contract_id": "trendlines_research_capture_failure_v1",
                       "receipt_id": receipt["receipt_id"], "receipt_path": archive["receipt_path"],
                       "raw_sha256": receipt["raw_sha256"], "reason": "fixture invalid failure", "numeric_input_allowed": True}
            S.atomic_json(captured / R.ROOT / "failures" / (C.canonical_hash(failure) + ".json"), R._hash(failure))
        report = R.verify(captured)
        assert not report["ok"]
        assert R.load_asset_detail(captured, "bitcoin", now=FIXTURE["FETCHED"]) is None
        # A globally failed audit never adds even a mathematically valid new key.
        assert cache.entry_count == 1


def test_resigned_changed_line_prices_force_scalar_replay_and_fail(captured, calls):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        pointer, path, archive, _receipt_path, _receipt = evidence(captured)
        engine = deepcopy(archive["engine_snapshot"])
        line = next(line for axis in engine["analyses"].values() for period in axis.values()
                    for line in period["lines"] if line["current_price"] is not None)
        line["current_price"] += 1
        archive["engine_snapshot"] = E._finish({key: value for key, value in engine.items()
                                               if key not in {"snapshot_id", "content_hash"}})
        resign_archive(captured, path, archive, pointer)
        report = R.verify(captured)
        assert not report["ok"] and "numeric_replay_failed" in report["errors"][0]
        assert calls["prepare"] == 2 and calls["numeric"] == 2
        assert cache.entry_count == 1


@pytest.mark.parametrize("function", ["prepare", "numeric", "outer"])
def test_validator_function_replacement_invalidates_cached_math(captured, calls, monkeypatch, function):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        module, name = {"prepare": (R, "_prepare"), "numeric": (E, "verify_research_asset_snapshot"),
                        "outer": (R, "verify")}[function]
        original = getattr(module, name)

        def replacement(*args, **kwargs):
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, replacement)
        assert R.verify(captured)["ok"]
        assert calls["prepare"] == 2 and calls["numeric"] == 2


def test_engine_version_change_cannot_reuse_an_old_model_proof(captured, calls, monkeypatch):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        monkeypatch.setattr(C, "ENGINE_VERSION", "different-engine-version")
        assert not R.verify(captured)["ok"]
        assert calls["prepare"] == 2 and calls["numeric"] == 2


def test_changed_receipt_bytes_are_not_an_exact_cached_receipt(captured, calls):
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        _pointer, _path, _archive, receipt_path, _receipt = evidence(captured)
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
        # Existing canonical receipt validation is unchanged, but modified file
        # bytes do not qualify for reuse of an exact receipt's numerical proof.
        assert R.verify(captured)["ok"]
        assert calls["prepare"] == 2 and calls["numeric"] == 2


def test_cache_is_bounded_and_context_cannot_be_forged(captured, calls):
    raw = FIXTURE["public_html"](gap=True)
    stamp = "2024-04-10T02:00:00+00:00"
    R.capture_html(captured, "bitcoin", raw, FIXTURE["receipt"](raw, stamp), as_of=stamp)
    cache = R.VerifiedReplayCache(max_entries=1)
    with R.use_verified_replay_cache(cache):
        assert R.verify(captured)["ok"]
        assert cache.entry_count == 1
        before = calls["numeric"]
        assert R.verify(captured)["ok"]
        assert calls["numeric"] == before + 1 and cache.entry_count == 1
    with pytest.raises(C.TrendlinesError, match="instance_required"):
        with R.use_verified_replay_cache({"verified": True}):
            pass
    with pytest.raises(C.TrendlinesError, match="capacity_invalid"):
        R.VerifiedReplayCache(max_entries=True)


def test_failed_audit_cannot_mint_an_initial_math_proof(captured):
    pointer, _path, _archive, _receipt_path, _receipt = evidence(captured)
    pointer["assets"]["bitcoin"]["snapshot_sha256"] = "0" * 64
    S.atomic_json(captured / R.ROOT / "latest.json", R._hash(pointer))
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert not R.verify(captured)["ok"]
    assert cache.entry_count == 0
