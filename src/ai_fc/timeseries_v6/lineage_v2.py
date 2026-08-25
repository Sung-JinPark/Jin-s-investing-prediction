"""Independent V6 receipt, observation, revision, and raw-object verifier."""

from __future__ import annotations

import gzip
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping


ALLOWED_RELATIONS = frozenset({"parsed_from", "revision_evidence", "cross_check"})


@dataclass(frozen=True)
class LineageFinding:
    code: str
    entity_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "entity_id": self.entity_id, "detail": self.detail}


@dataclass(frozen=True)
class LineageResult:
    passed: bool
    findings: tuple[LineageFinding, ...]
    counts: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "pass": self.passed,
            "finding_count": len(self.findings),
            "finding_counts": dict(sorted(Counter(item.code for item in self.findings).items())),
            "counts": dict(self.counts),
            "findings": [finding.as_dict() for finding in self.findings],
        }


def _add(findings: list[LineageFinding], code: str, entity: Any, detail: str) -> None:
    findings.append(LineageFinding(code=code, entity_id=str(entity), detail=detail))


def _decoded_object(data: bytes, compression: str) -> bytes:
    if compression == "none":
        return data
    if compression == "gzip":
        return gzip.decompress(data)
    raise ValueError(f"unsupported integrity compression: {compression}")


def verify_lineage(
    *,
    raw_objects: Iterable[Mapping[str, Any]],
    receipts: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
    observation_versions: Iterable[Mapping[str, Any]],
    links: Iterable[Mapping[str, Any]],
    object_loader: Callable[[str], bytes] | None = None,
) -> LineageResult:
    """Verify all material lineage invariants without trusting summary flags."""

    raw_rows = list(raw_objects)
    receipt_rows = list(receipts)
    outcome_rows = list(outcomes)
    version_rows = list(observation_versions)
    link_rows = list(links)
    findings: list[LineageFinding] = []

    objects = {str(row["object_sha256"]): row for row in raw_rows}
    if len(objects) != len(raw_rows):
        _add(findings, "duplicate_raw_object", "raw_object", "object SHA appears more than once")
    receipts_by_id = {str(row["receipt_id"]): row for row in receipt_rows}
    if len(receipts_by_id) != len(receipt_rows):
        _add(findings, "duplicate_receipt", "receipt", "receipt ID appears more than once")
    versions = {str(row["observation_version_id"]): row for row in version_rows}
    if len(versions) != len(version_rows):
        _add(findings, "duplicate_observation_version", "observation", "version ID appears more than once")

    outcomes_by_receipt: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in outcome_rows:
        outcomes_by_receipt[str(row["receipt_id"])].append(row)
    links_by_receipt: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    links_by_version: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in link_rows:
        receipt_id = str(row["receipt_id"])
        version_id = str(row["observation_version_id"])
        relation = str(row["relation"])
        if relation not in ALLOWED_RELATIONS:
            _add(findings, "invalid_relation", f"{receipt_id}:{version_id}", relation)
        if receipt_id not in receipts_by_id:
            _add(findings, "orphan_link_receipt", receipt_id, "link references missing receipt")
        if version_id not in versions:
            _add(findings, "orphan_link_version", version_id, "link references missing observation version")
        links_by_receipt[receipt_id].append(row)
        links_by_version[version_id].append(row)

    for receipt_id, receipt in sorted(receipts_by_id.items()):
        receipt_outcomes = outcomes_by_receipt.get(receipt_id, [])
        if len(receipt_outcomes) != 1:
            _add(
                findings,
                "terminal_outcome_cardinality",
                receipt_id,
                f"expected 1 receipt outcome, found {len(receipt_outcomes)}",
            )
        else:
            outcome = receipt_outcomes[0]
            parsed_links = sum(
                row["relation"] == "parsed_from" for row in links_by_receipt.get(receipt_id, [])
            )
            if outcome["outcome_status"] == "parsed" and int(outcome["observation_count"]) != parsed_links:
                _add(
                    findings,
                    "fact_count_mismatch",
                    receipt_id,
                    f"declared={outcome['observation_count']} linked={parsed_links}",
                )
        object_sha = str(receipt["object_sha256"])
        if object_sha not in objects:
            _add(findings, "missing_raw_object", receipt_id, object_sha)

    for receipt_id in sorted(set(outcomes_by_receipt) - set(receipts_by_id)):
        _add(findings, "orphan_outcome", receipt_id, "outcome references missing receipt")

    by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for version_id, row in versions.items():
        key = str(row["observation_key_id"])
        by_key[key].append(row)
        parent = row.get("supersedes_observation_version_id")
        seq = int(row["revision_seq"])
        if seq == 0 and parent is not None:
            _add(findings, "invalid_revision_root", version_id, "revision 0 has parent")
        if seq > 0 and parent is None:
            _add(findings, "missing_revision_parent", version_id, "revision >0 lacks parent")
        if parent is not None:
            parent_id = str(parent)
            children[parent_id].append(version_id)
            parent_row = versions.get(parent_id)
            if parent_row is None:
                _add(findings, "missing_revision_parent", version_id, parent_id)
            else:
                if str(parent_row["observation_key_id"]) != key:
                    _add(findings, "cross_key_revision", version_id, parent_id)
                if int(parent_row["revision_seq"]) != seq - 1:
                    _add(findings, "revision_seq_gap", version_id, f"parent_seq={parent_row['revision_seq']} child_seq={seq}")
        object_sha = str(row["raw_object_sha256"])
        if object_sha not in objects:
            _add(findings, "missing_raw_object", version_id, object_sha)
        if not links_by_version.get(version_id):
            _add(findings, "orphan_observation_version", version_id, "no receipt_fact_link")

    for parent, child_ids in sorted(children.items()):
        if len(child_ids) > 1:
            _add(findings, "revision_branch", parent, ",".join(sorted(child_ids)))

    for key, rows in sorted(by_key.items()):
        seqs = sorted(int(row["revision_seq"]) for row in rows)
        if seqs != list(range(len(seqs))):
            _add(findings, "revision_seq_gap", key, f"sequences={seqs}")

    for start in sorted(versions):
        visited: set[str] = set()
        current: str | None = start
        while current is not None and current in versions:
            if current in visited:
                _add(findings, "revision_cycle", start, f"cycle_at={current}")
                break
            visited.add(current)
            parent = versions[current].get("supersedes_observation_version_id")
            current = str(parent) if parent is not None else None

    if object_loader is not None:
        for object_sha, row in sorted(objects.items()):
            try:
                stored = object_loader(str(row["object_uri"]))
                stored_sha = hashlib.sha256(stored).hexdigest()
                decoded = _decoded_object(stored, str(row["compression"]))
                decoded_sha = hashlib.sha256(decoded).hexdigest()
            except Exception as exc:
                _add(findings, "raw_object_unreadable", object_sha, type(exc).__name__)
                continue
            if stored_sha != row["stored_sha256"]:
                _add(findings, "stored_object_hash_mismatch", object_sha, stored_sha)
            if decoded_sha != object_sha:
                _add(findings, "raw_object_hash_mismatch", object_sha, decoded_sha)
            if len(decoded) != int(row["decompressed_bytes"]):
                _add(findings, "raw_object_size_mismatch", object_sha, str(len(decoded)))

    findings.sort(key=lambda item: (item.code, item.entity_id, item.detail))
    return LineageResult(
        passed=not findings,
        findings=tuple(findings),
        counts={
            "raw_objects": len(raw_rows),
            "receipts": len(receipt_rows),
            "outcomes": len(outcome_rows),
            "observation_versions": len(version_rows),
            "links": len(link_rows),
        },
    )
