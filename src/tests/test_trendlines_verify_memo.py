"""Worker audits reuse decoded evidence only for bytes they hash again."""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, critical as K, full_history as F, research as R, storage as S
from ai_fc.trendlines import long_boundaries as B, representative as V
from test_trendlines_critical import capture

REPOSITORY = Path(__file__).resolve().parents[2]
STORES = (R.ROOT, F.ROOT, K.ROOT, V.ROOT, B.ROOT)


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("chain")
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE,
                     K.POLICY_RELATIVE, V.POLICY_RELATIVE, B.POLICY_RELATIVE):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    _, stamp = capture(root, count=270)
    for module in (K, V, B):
        assert module.refresh(root, "bitcoin", now=stamp)["changed"]
    return root, stamp


@pytest.fixture
def chain(template, tmp_path):
    source, stamp = template
    root = tmp_path / "store"
    shutil.copytree(source, root)
    return root, stamp


def audit(root, now):
    return {"research": R.verify(root)["ok"], "full": F.verify(root, now=now)["ok"],
            "critical": K.verify(root, now=now)["ok"],
            "representative": V.verify(root, asset_id="bitcoin", now=now)["ok"],
            "long": B.verify(root, asset_id="bitcoin", now=now)["ok"]}


def latest_file(root, store, name):
    pointer = S.read_json(root / store / "latest.json")["assets"]["bitcoin"]
    return root / store / "exports" / pointer["snapshot_id"] / name


def append(path):
    path.write_bytes(path.read_bytes() + b" ")


def tamper_raw(root):
    append(next((root / R.ROOT / "raw").glob("*.bin")))


def tamper_receipt(root):
    path = next((root / R.ROOT / "receipts").glob("*.json"))
    receipt = R._checked(path)
    receipt["available_at"] = "2020-01-01T00:00:00+00:00"
    S.atomic_json(path, R._hash(receipt))


def tamper_archive(root):
    path = root / S.read_json(root / R.ROOT / "latest.json")["assets"]["bitcoin"]["snapshot_path"]
    archive = R._checked(path)
    archive["bars"][0]["close"] += .25
    S.atomic_json(path, R._hash(archive))


def tamper_renamed_archive(root):
    path = next((root / R.ROOT / "snapshots").glob("*.json"))
    shutil.copyfile(path, path.with_name("research-snapshot-" + "0" * 64 + ".json"))


def tamper_registry(root):
    path = root / C.ASSET_REGISTRY_RELATIVE
    text = path.read_bytes()
    assert text.count("    name: 비트코인\n".encode()) == 1
    path.write_bytes(text.replace("    name: 비트코인\n".encode(), "    name: 비트코인 변경\n".encode()))


def tamper_contract(root):
    path = root / C.CONTRACT_RELATIVE
    text = path.read_bytes()
    assert text.count(b"settlement_buffer_minutes: 15\n") == 1
    path.write_bytes(text.replace(b"settlement_buffer_minutes: 15\n", b"settlement_buffer_minutes: 16\n"))


TAMPERS = {
    "raw": (tamper_raw, "research"),
    "receipt": (tamper_receipt, "research"),
    "archive": (tamper_archive, "research"),
    "renamed_archive": (tamper_renamed_archive, "research"),
    "registry": (tamper_registry, "research"),
    "full_manifest": (lambda root: append(latest_file(root, F.ROOT, "manifest.json")), "full"),
    "full_chunk": (lambda root: append(latest_file(root, F.ROOT, "bars-0000.json")), "full"),
    "critical_export": (lambda root: append(latest_file(root, K.ROOT, "detail.json")), "critical"),
    "critical_shadow": (lambda root: append(root / S.read_json(root / K.ROOT / "latest.json")["assets"]["bitcoin"]["snapshot_path"]),
                        "representative"),
    "representative_export": (lambda root: append(latest_file(root, V.ROOT, "detail.json")), "representative"),
    "long_export": (lambda root: append(latest_file(root, B.ROOT, "detail.json")), "long"),
    "contract": (tamper_contract, "representative"),
}


def test_one_day_calendar_index_matches_the_range_query():
    for calendar_id in ("XKRX", "XNAS", "XNYS", "24/7"):
        day = date(2022, 12, 20)
        while day <= date(2023, 1, 10):
            assert C._session_on(calendar_id, day.isoformat()) == C.session_schedule.__wrapped__(
                calendar_id, day.isoformat(), day.isoformat())
            day += timedelta(days=1)
    # Outside the default calendar's bounds the original range query still decides.
    assert C._session_on("XNYS", "2000-01-03") == C.session_schedule.__wrapped__("XNYS", "2000-01-03", "2000-01-03")
    bar = {"bar_id": "research-bar-x", "asset_id": "sp500", "source_id": "s", "session_date": "2024-01-06",
           "currency": "USD", "unit": "index_points", "price_basis": "p", "calendar_id": "XNYS",
           "available_at": "2024-01-08T00:00:00+00:00", "fetched_at": "2024-01-08T00:00:00+00:00",
           "finalized_at": "2024-01-08T00:00:00+00:00", "raw_sha256": "0" * 64, "receipt_id": "r",
           "open": 1, "high": 2, "low": 1, "close": 2, "revision_seq": 1, "supersedes_bar_id": None}
    asset = {key: bar[key] for key in ("asset_id", "source_id", "currency", "unit", "price_basis", "calendar_id")}
    with pytest.raises(C.TrendlinesError, match="nontrading session bar"):
        C.validate_bar(bar, asset)


def test_contract_parse_is_shared_but_each_read_sees_current_text_in_its_own_copy(tmp_path):
    target = tmp_path / C.ASSET_REGISTRY_RELATIVE
    target.parent.mkdir(parents=True)
    shutil.copyfile(REPOSITORY / C.ASSET_REGISTRY_RELATIVE, target)
    first = C.load_asset_registry(tmp_path)
    first["bitcoin"]["name"] = "mutated by a caller"
    assert C.load_asset_registry(tmp_path)["bitcoin"]["name"] == "비트코인"
    tamper_registry(tmp_path)
    assert C.load_asset_registry(tmp_path)["bitcoin"]["name"] == "비트코인 변경"


def test_warm_audit_reads_every_file_but_decodes_no_unchanged_archive(chain, monkeypatch):
    root, stamp = chain
    decoded = []
    original_identity = R._archive_identity
    monkeypatch.setattr(R, "_archive_identity", lambda *a: decoded.append(1) or original_identity(*a))
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert all(audit(root, stamp).values())
        assert decoded and cache.evidence_count == 5
        decoded.clear()
        reads = set()
        for method in ("read_bytes", "read_text"):
            original = getattr(Path, method)
            monkeypatch.setattr(Path, method, lambda self, *a, _o=original, **k: reads.add(self.resolve()) or _o(self, *a, **k))
        assert all(audit(root, stamp).values())
    assert not decoded and cache.evidence_count == 5
    stored = {path.resolve() for store in STORES for path in (root / store).rglob("*") if path.is_file()}
    assert stored and stored <= reads


@pytest.mark.parametrize("name", TAMPERS)
def test_warm_evidence_gives_the_cold_verdict_after_tampering(chain, name):
    root, stamp = chain
    tamper, owner = TAMPERS[name]
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert all(audit(root, stamp).values())
        assert all(audit(root, stamp).values())
        counts = cache.entry_count, cache.evidence_count
        tamper(root)
        warm = audit(root, stamp)
        assert (cache.entry_count, cache.evidence_count) == counts
    cold = audit(root, stamp)
    assert warm == cold and warm[owner] is False


def test_recalled_evidence_rechecks_the_read_cutoff(chain):
    root, stamp = chain
    earlier = (S.aware_time(stamp) - timedelta(days=30)).isoformat()
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert all(audit(root, stamp).values())
        warm = audit(root, earlier)
        assert all(audit(root, stamp).values())
    cold = audit(root, earlier)
    assert warm == cold and not warm["critical"] and not warm["representative"] and not warm["long"]


def test_failed_audit_mints_neither_proofs_nor_evidence(chain):
    root, stamp = chain
    pointer = S.read_json(root / F.ROOT / "latest.json")
    pointer["assets"]["bitcoin"]["manifest_sha256"] = "0" * 64
    S.atomic_json(root / F.ROOT / "latest.json", R._hash(pointer))
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert R.verify(root)["ok"]
        counts = cache.entry_count, cache.evidence_count
        assert not F.verify(root, now=stamp)["ok"]
        assert (cache.entry_count, cache.evidence_count) == counts
    research = R.VerifiedReplayCache()
    latest = S.read_json(root / R.ROOT / "latest.json")
    latest["assets"]["bitcoin"]["snapshot_sha256"] = "0" * 64
    S.atomic_json(root / R.ROOT / "latest.json", R._hash(latest))
    with R.use_verified_replay_cache(research):
        assert not R.verify(root)["ok"]
    assert research.entry_count == research.evidence_count == 0


def test_representative_reparse_reuses_only_a_matching_source_proof(chain, monkeypatch):
    root, stamp = chain
    calls = []
    original = R._prepare

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(R, "_prepare", counted)
    assert V.verify(root, asset_id="bitcoin", now=stamp)["ok"] and len(calls) == 1
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert V.verify(root, asset_id="bitcoin", now=stamp)["ok"] and len(calls) == 2
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        assert R.verify(root)["ok"] and len(calls) == 3
        assert V.verify(root, asset_id="bitcoin", now=stamp)["ok"] and len(calls) == 3
        assert B.verify(root, asset_id="bitcoin", now=stamp)["ok"] and len(calls) == 3
        # A proof minted by a different parser is not a proof for this one.
        monkeypatch.setattr(R, "_prepare", lambda *args, **kwargs: counted(*args, **kwargs))
        assert V.verify(root, asset_id="bitcoin", now=stamp)["ok"] and len(calls) == 4
        tamper_raw(root)
        assert not V.verify(root, asset_id="bitcoin", now=stamp)["ok"]


def test_evidence_memo_has_no_entry_api_and_is_bounded():
    cache = R.VerifiedReplayCache(max_entries=1)
    functions = (len,)
    cache._remember({}, {("a",): (functions, {"files": {}, "assets": {}}), ("b",): (functions, {"files": {}, "assets": {}})})
    # A full store keeps the entry it already holds; the new one is not kept.
    assert cache.evidence_count == 1 and cache._recall(("b",), functions) is None
    recalled = cache._recall(("a",), functions)
    recalled["files"]["injected"] = "0" * 64
    assert cache._recall(("a",), functions) == {"files": {}, "assets": {}}
    assert cache._recall(("a",), (repr,)) is None
    assert not any(hasattr(cache, name) for name in ("remember", "add", "update", "load", "preload"))
