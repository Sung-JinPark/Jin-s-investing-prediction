"""A full worker cache keeps the entries its passes use instead of thrashing."""

from __future__ import annotations

import pytest

from ai_fc.trendlines import contracts as C, research as R
from test_trendlines_verify_memo import audit, chain, template  # noqa: F401  (fixtures)

FUNCTIONS = (len,)


def test_default_bound_and_capacity_limits():
    assert R.VerifiedReplayCache().max_entries == 262144
    assert R.VerifiedReplayCache(max_entries=1048576).max_entries == 1048576
    for invalid in (0, 1048577, True, 2.0):
        with pytest.raises(C.TrendlinesError, match="capacity_invalid"):
            R.VerifiedReplayCache(max_entries=invalid)


def test_full_store_keeps_a_proof_that_alternating_passes_still_use():
    # Two assets' proofs, one slot, each asset audited every other pass: LRU
    # evicted each proof just before its next use and never hit.
    cache = R.VerifiedReplayCache(max_entries=1)
    hits = []
    for audit_number in range(6):
        key = ("proof", audit_number % 2)
        hit = cache._contains(key, FUNCTIONS)
        hits.append(hit)
        cache._remember({} if hit else {key: FUNCTIONS})
    assert hits == [False, False, True, False, True, False]
    assert cache.entry_count == 1


def test_full_store_replaces_only_an_entry_idle_for_the_horizon(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_CACHE_IDLE_AUDITS", 3)
    cache = R.VerifiedReplayCache(max_entries=2)
    cache._remember({("a",): FUNCTIONS, ("b",): FUNCTIONS})
    for _ in range(2):
        assert cache._contains(("a",), FUNCTIONS)
        cache._remember({})
    # "b" has gone unused for three successful audits; "a" was used in the last one.
    cache._remember({("c",): FUNCTIONS})
    assert not cache._contains(("b",), FUNCTIONS)
    assert cache._contains(("a",), FUNCTIONS) and cache._contains(("c",), FUNCTIONS)
    cache._remember({("d",): FUNCTIONS})
    assert not cache._contains(("d",), FUNCTIONS) and cache.entry_count == 2
    evidence = R.VerifiedReplayCache(max_entries=1)
    evidence._remember({}, {("e",): (FUNCTIONS, {"files": {}, "assets": {}})})
    for _ in range(3):
        evidence._remember({})
    evidence._remember({}, {("f",): (FUNCTIONS, {"files": {}, "assets": {}})})
    assert evidence._recall(("e",), FUNCTIONS) is None and evidence._recall(("f",), FUNCTIONS) is not None


def test_keys_share_one_copy_of_the_checking_function_ids():
    cache = R.VerifiedReplayCache()
    functions = (len, repr)
    ids = lambda: tuple(id(f) for f in functions)  # noqa: E731
    cache._remember({("p", "x", ids()): functions, ("p", "y", ids()): functions},
                    {("e", "x", ids()): (functions, {"files": {}, "assets": {}})})
    keys = [*cache._VerifiedReplayCache__entries, *cache._VerifiedReplayCache__evidence]
    assert len(keys) == 3 and len({id(key[-1]) for key in keys}) == 1
    assert cache._contains(("p", "x", ids()), functions) and cache._recall(("e", "x", ids()), functions) is not None
    assert not cache._contains(("p", "x", ids()), (len, str))


def test_audits_beyond_the_bound_decode_only_what_the_store_could_not_keep(chain, monkeypatch):
    root, stamp = chain
    missed = []
    original = R.VerifiedReplayCache._recall

    def recall(self, key, functions):
        value = original(self, key, functions)
        if value is None:
            missed.append(key[0])
        return value

    monkeypatch.setattr(R.VerifiedReplayCache, "_recall", recall)
    cache = R.VerifiedReplayCache(max_entries=4)
    with R.use_verified_replay_cache(cache):
        assert all(audit(root, stamp).values())
        assert len(missed) == 5 and cache.evidence_count == cache.entry_count == 4
        for _ in range(3):
            missed.clear()
            assert all(audit(root, stamp).values())
            # The five-layer chain needs five evidence entries; the four kept
            # ones hit on every pass and only the refused one is decoded again.
            assert missed == ["long_boundaries_evidence"] and cache.evidence_count == 4
    assert all(audit(root, stamp).values())
