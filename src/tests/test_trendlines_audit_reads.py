"""Each audit reads every file it checks once; nested audits share that read, the next audit reads again."""

from __future__ import annotations

import collections
import hashlib
import threading
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, critical as K, full_history as F, research as R, storage as S
from ai_fc.trendlines import long_boundaries as B, representative as V
from test_trendlines_verify_memo import audit, chain, latest_file, tamper_raw, template  # noqa: F401  (fixtures)


class Reads(collections.Counter):
    """Files read as bytes, counted from any thread (audits read ahead on worker threads)."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()

    def add(self, path):
        with self.lock:
            self[path] += 1


@pytest.fixture
def reads(monkeypatch):
    counts = Reads()
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: counts.add(self.resolve()) or original(self))
    return counts


def stored(root, *stores):
    # Latest pointers are read as text; every other stored file as bytes.
    return {path.resolve() for store in stores for path in (root / store).rglob("*")
            if path.is_file() and path.name != "latest.json"}


def test_warm_nested_audit_reads_each_file_once_and_the_next_audit_reads_it_again(chain, reads):
    root, stamp = chain
    files = stored(root, R.ROOT, F.ROOT, K.ROOT)
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert all(audit(root, stamp).values())
        reads.clear()
        # Critical runs full, which runs research: three layers, one read of each file.
        assert K.verify(root, now=stamp)["ok"]
        assert files and {reads[path] for path in files} == {1}
        assert K.verify(root, now=stamp)["ok"]
    assert {reads[path] for path in files} == {2}


def test_research_audit_reads_each_original_once(chain, reads):
    root, _stamp = chain
    raw, receipts = stored(root, R.ROOT / "raw"), stored(root, R.ROOT / "receipts")
    # Without a proof the original is read once more, to reparse it.
    assert R.verify(root)["ok"]
    assert raw and {reads[path] for path in raw} == {2} and {reads[path] for path in receipts} == {1}
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert R.verify(root)["ok"]
        reads.clear()
        assert R.verify(root)["ok"]
    assert {reads[path] for path in raw | receipts} == {1}


def test_a_change_after_this_audit_read_a_file_is_seen_by_the_next_audit(chain, monkeypatch):
    root, stamp = chain
    original = R.verify

    def nested_then_tamper(*args, **kwargs):
        report = original(*args, **kwargs)
        tamper_raw(root)
        return report

    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert all(audit(root, stamp).values())
        with monkeypatch.context() as patch:
            patch.setattr(R, "verify", nested_then_tamper)
            # Full compares the digest of the original as its nested research audit read it.
            assert F.verify(root, now=stamp)["ok"]
        assert R._AUDIT.get() is None
        warm = audit(root, stamp)
    assert warm == audit(root, stamp) and not any(warm.values())


def test_the_file_record_exists_only_inside_an_audit(chain, monkeypatch):
    root, stamp = chain
    path = latest_file(root, F.ROOT, "manifest.json")
    inside = []
    original = R._audit_digest
    assert R._audit_digest(path) == (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
    assert R._AUDIT.get() is None
    monkeypatch.setattr(R, "_audit_digest", lambda target: inside.append(R._AUDIT.get() is not None) or original(target))
    assert F.verify(root, now=stamp)["ok"]
    assert inside and all(inside) and R._AUDIT.get() is None


@pytest.mark.parametrize("module", (V, B), ids=("representative", "long"))
def test_asset_scoped_audit_skips_another_assets_chain_unread_with_the_cold_verdict(chain, reads, module):
    root, stamp = chain
    export = latest_file(root, module.ROOT, "detail.json").resolve()
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert all(audit(root, stamp).values())
        export.write_bytes(export.read_bytes() + b" ")
        reads.clear()
        warm_other = module.verify(root, asset_id="sk-hynix", now=stamp)
        assert reads[export] == 0 and not any("/trendlines_research/raw/" in path.as_posix() for path in reads)
        warm_own = module.verify(root, asset_id="bitcoin", now=stamp)
    assert warm_other == module.verify(root, asset_id="sk-hynix", now=stamp) and warm_other["ok"]
    assert warm_own == module.verify(root, asset_id="bitcoin", now=stamp) and not warm_own["ok"]


def test_receipt_from_a_digest_equals_the_receipt_from_the_bytes(chain):
    root, _stamp = chain
    receipt = R._checked(next((root / R.ROOT / "receipts").glob("*.json")))
    raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
    asset = R.asset_definition(root, receipt["asset_id"])
    stated = {"url": receipt["url"], "retrieved_at": receipt["fetched_at"], "sha256": receipt["raw_sha256"],
              "bytes": receipt["byte_count"], "http_status": receipt["http_status"]}
    assert R._receipt(raw, stated, asset, receipt["fetched_at"]) == receipt
    assert R._receipt_of(hashlib.sha256(raw).hexdigest(), len(raw), stated, asset, receipt["fetched_at"]) == receipt
    for sha, length, error in ((receipt["raw_sha256"], 0, "size_or_type"),
                               (receipt["raw_sha256"], R.MAX_RAW_BYTES + 1, "size_or_type"),
                               ("0" * 64, len(raw), "sha_or_length"), (receipt["raw_sha256"], len(raw) + 1, "sha_or_length")):
        with pytest.raises(C.TrendlinesError, match=error):
            R._receipt_of(sha, length, stated, asset, receipt["fetched_at"])


def test_read_ahead_yields_each_file_in_order_with_its_own_digest_and_raises_in_place(tmp_path, monkeypatch):
    paths = [tmp_path / f"{i:02d}.bin" for i in range(12)]
    for i, path in enumerate(paths):
        path.write_bytes(bytes([i]) * (i + 1))
    assert [(path, data, digest) for path, data, digest in R._audit_reads(paths)] == [
        (path, path.read_bytes(), hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths]
    paths[5].unlink()
    seen = []
    with pytest.raises(FileNotFoundError):
        for path, _data, _digest in R._audit_reads(paths):
            seen.append(path)
    assert seen == paths[:5]
    started = []
    original = R._read_hash
    monkeypatch.setattr(R, "_read_hash", lambda path: started.append(path) or original(path))
    for _ in R._audit_reads(paths[:5]):
        break
    # Abandoning the loop leaves no reads running and none beyond the read-ahead window.
    assert started == paths[:len(started)] and len(started) <= R.AUDIT_READ_AHEAD + 1


def test_read_ahead_records_digests_only_inside_an_audit(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"a")
    list(R._audit_reads([path]))
    assert R._AUDIT.get() is None
    with R._audit_files():
        list(R._audit_reads([path]))
        path.write_bytes(b"b")
        assert R._audit_digest(path) == (hashlib.sha256(b"a").hexdigest(), 1)
    assert R._audit_digest(path) == (hashlib.sha256(b"b").hexdigest(), 1)


def test_root_resolver_applies_safe_path_checks_with_one_root_resolution(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    resolve = S.root_resolver(tmp_path)
    assert resolve("data/x.json") == S.safe_path(tmp_path, "data/x.json")
    for relative, error in (("../outside.json", "escapes its root"), ("data/../../outside.json", "escapes its root"),
                            (str(tmp_path / "data/x.json"), "must be relative"), ("", "must be relative"), (None, "must be relative")):
        for check in (resolve, lambda value: S.safe_path(tmp_path, value)):
            with pytest.raises(S.TrendlinesStorageError, match=error):
                check(relative)
    roots = []
    original = Path.resolve

    def counted(self, *args, **kwargs):
        if self == tmp_path:
            roots.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted)
    for name in ("a", "b", "c"):
        assert resolve("data/" + name) == original(tmp_path / "data" / name)
    assert roots == []


def test_one_root_resolution_and_one_registry_read_per_audit(chain, monkeypatch):
    root, stamp = chain
    resolvers, registry_reads = [], []
    original_resolver, original_text = S.root_resolver, Path.read_text
    monkeypatch.setattr(S, "root_resolver", lambda parent: resolvers.append(parent) or original_resolver(parent))
    registry = (root / C.ASSET_REGISTRY_RELATIVE).resolve()
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (registry_reads.append(1) if self.resolve() == registry else None)
                        or original_text(self, *a, **k))
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert all(audit(root, stamp).values())
        resolvers.clear()
        registry_reads.clear()
        assert K.verify(root, now=stamp)["ok"]
        assert len(resolvers) == 1 and len(registry_reads) == 1
        assert K.verify(root, now=stamp)["ok"]
    assert len(resolvers) == 2 and len(registry_reads) == 2


def test_asset_definitions_in_one_audit_are_separate_copies(chain):
    root, _stamp = chain
    outside = R.asset_definition(root, "bitcoin")
    with R._audit_files():
        first = R.asset_definition(root, "bitcoin")
        first["name"] = "mutated by a caller"
        assert R.asset_definition(root, "bitcoin") == outside
