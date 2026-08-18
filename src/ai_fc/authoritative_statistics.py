"""Authoritative statistics policy and append-only observation lineage.

This module deliberately has no network client and no chart logic.  It is the narrow
boundary between a fetched artifact and any numeric statistic derived from it:

1. register the source in the policy;
2. persist the exact response bytes and append a receipt;
3. append explicit, vintage-aware observations that reference that receipt; and
4. validate every numeric metric's source lineage against the same policy.

Research reports and public aggregators may be retained for insight provenance, but
the policy prevents them from entering the numeric observation ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Literal
from urllib.parse import parse_qsl, urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET_QUERY_KEYS = {
    "api_key", "apikey", "key", "token", "access_token", "secret",
    "registrationkey", "user_id", "userid",
}


class AuthoritativeDataError(ValueError):
    """Base class for auditable lineage rejections."""


class SourcePolicyViolation(AuthoritativeDataError):
    """A source is unknown or is not allowed to supply numeric inputs."""


class RawArtifactMissing(AuthoritativeDataError):
    """A normalized row has no matching, intact raw artifact receipt."""


class AppendConflict(AuthoritativeDataError):
    """An existing immutable key conflicts with a proposed append."""


class NormalizationViolation(AuthoritativeDataError):
    """A row attempts an implicit value or unit transformation."""


class AuthorityClass(StrEnum):
    OFFICIAL_GOVERNMENT = "official_government"
    OFFICIAL_CENTRAL_BANK = "official_central_bank"
    OFFICIAL_REGULATOR = "official_regulator"
    OFFICIAL_SRO = "official_sro"
    OFFICIAL_EXCHANGE = "official_exchange"
    ACADEMIC_RESEARCH = "academic_research"
    INVESTMENT_RESEARCH = "investment_research"
    MEDIA = "media"
    MARKET_DATA_AGGREGATOR = "market_data_aggregator"
    USER_SUPPLIED = "user_supplied"


class SourceRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    display_name: str = Field(min_length=1)
    authority_class: AuthorityClass
    owner: str = Field(min_length=1)
    allowed_domains: tuple[str, ...] = ()
    numeric_input_allowed: bool
    insight_only: bool
    usage_roles: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def source_role_is_unambiguous(self) -> "SourceRule":
        if self.numeric_input_allowed == self.insight_only:
            raise ValueError(
                "exactly one of numeric_input_allowed and insight_only must be true"
            )
        if len(set(self.usage_roles)) != len(self.usage_roles):
            raise ValueError("usage_roles must be unique")
        if self.numeric_input_allowed and not self.allowed_domains:
            raise ValueError("numeric sources require at least one allowed domain")
        if len(set(self.allowed_domains)) != len(self.allowed_domains):
            raise ValueError("allowed_domains must be unique")
        if any(
            not domain or domain != domain.lower() or "/" in domain
            for domain in self.allowed_domains
        ):
            raise ValueError("allowed_domains must be lowercase host names")
        return self


class AuthoritativeSourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    policy_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    default_numeric_input: Literal["deny"]
    raw_before_normalized: Literal["required"]
    unknown_source_action: Literal["reject"]
    authoritative_classes: tuple[AuthorityClass, ...]
    insight_only_classes: tuple[AuthorityClass, ...]
    sources: tuple[SourceRule, ...]

    @model_validator(mode="after")
    def policy_is_closed_and_consistent(self) -> "AuthoritativeSourcePolicy":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        authoritative = set(self.authoritative_classes)
        insight = set(self.insight_only_classes)
        if authoritative & insight:
            raise ValueError("authoritative and insight-only classes must be disjoint")
        for source in self.sources:
            if source.numeric_input_allowed and source.authority_class not in authoritative:
                raise ValueError(
                    f"numeric source {source.source_id} is not in an authoritative class"
                )
            if source.insight_only and source.authority_class not in insight:
                raise ValueError(
                    f"insight source {source.source_id} is not in an insight-only class"
                )
        return self

    def rule_for(self, source_id: str) -> SourceRule:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise SourcePolicyViolation(
            f"unregistered source {source_id!r}; default numeric policy is deny"
        )

    def require_numeric_source(self, source_id: str) -> SourceRule:
        source = self.rule_for(source_id)
        if not source.numeric_input_allowed or source.insight_only:
            raise SourcePolicyViolation(
                f"source {source_id!r} is insight-only and cannot supply numeric inputs"
            )
        return source


def load_authoritative_source_policy(path: Path) -> AuthoritativeSourcePolicy:
    """Load the closed source allowlist without applying implicit defaults."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AuthoritativeSourcePolicy.model_validate(raw)


def validate_numeric_metric_lineage(
    policy: AuthoritativeSourcePolicy,
    *,
    metric_id: str,
    source_ids: Iterable[str],
) -> tuple[SourceRule, ...]:
    """Fail closed unless every numeric input is an authoritative allowlisted source."""
    if not metric_id or not _SAFE_ID_RE.fullmatch(metric_id):
        raise SourcePolicyViolation("metric_id must be a non-empty stable identifier")
    ids = tuple(source_ids)
    if not ids:
        raise SourcePolicyViolation(f"numeric metric {metric_id!r} has no source lineage")
    if len(ids) != len(set(ids)):
        raise SourcePolicyViolation(f"numeric metric {metric_id!r} repeats a source_id")
    return tuple(policy.require_numeric_source(source_id) for source_id in ids)


def _require_aware_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _require_iso_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use canonical YYYY-MM-DD form")
    return parsed


def _require_decimal(value: str, field_name: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be an exact decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _assert_safe_source_uri(source_uri: str) -> None:
    parsed = urlsplit(source_uri)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("source_uri must be an absolute HTTP(S) URI")
    secret_keys = {
        key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    } & _SECRET_QUERY_KEYS
    if secret_keys:
        raise ValueError(
            "source_uri must not persist secret query parameters: "
            + ", ".join(sorted(secret_keys))
        )


def _assert_source_domain(source: SourceRule, source_uri: str) -> None:
    hostname = (urlsplit(source_uri).hostname or "").lower()
    if not any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in source.allowed_domains
    ):
        raise SourcePolicyViolation(
            f"source URI host {hostname!r} is not approved for {source.source_id!r}"
        )


def _json_line(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _append_line(path: Path, line: str) -> None:
    _append_lines(path, (line,))


def _append_lines(path: Path, lines: Iterable[str]) -> None:
    pending = tuple(lines)
    if not pending:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for line in pending:
            handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise AppendConflict(f"malformed immutable ledger line {line_number}: {path}") from exc
        if not isinstance(row, dict):
            raise AppendConflict(f"immutable ledger line {line_number} is not an object: {path}")
        rows.append(row)
    return rows


class RawArtifactReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    receipt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    series_ids: tuple[str, ...]
    source_uri: str = Field(min_length=1)
    http_status: int = Field(ge=100, le=599)
    media_type: str = Field(min_length=1)
    byte_count: int = Field(ge=1)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str = Field(min_length=1)
    fetched_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def receipt_contract(self) -> "RawArtifactReceipt":
        _require_aware_timestamp(self.fetched_at, "fetched_at")
        _assert_safe_source_uri(self.source_uri)
        if len(set(self.series_ids)) != len(self.series_ids):
            raise ValueError("series_ids must be unique")
        if any(not _SAFE_ID_RE.fullmatch(series_id) for series_id in self.series_ids):
            raise ValueError("series_ids must contain stable identifiers")
        return self


def persist_raw_artifact(
    store_root: Path,
    policy: AuthoritativeSourcePolicy,
    *,
    source_id: str,
    payload: bytes,
    source_uri: str,
    fetched_at: str,
    http_status: int,
    media_type: str,
    series_ids: Iterable[str] = (),
) -> RawArtifactReceipt:
    """Persist immutable response bytes, then append their auditable fetch receipt."""
    source = policy.rule_for(source_id)
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("payload must be non-empty bytes")
    _require_aware_timestamp(fetched_at, "fetched_at")
    _assert_safe_source_uri(source_uri)
    _assert_source_domain(source, source_uri)
    normalized_series_ids = tuple(series_ids)
    if len(normalized_series_ids) != len(set(normalized_series_ids)):
        raise ValueError("series_ids must be unique")
    for series_id in normalized_series_ids:
        if not _SAFE_ID_RE.fullmatch(series_id):
            raise ValueError(f"invalid series_id {series_id!r}")

    digest = hashlib.sha256(payload).hexdigest()
    artifact = store_root / "raw" / source_id / f"{digest}.bin"
    receipt_seed = {
        "source_id": source_id,
        "series_ids": normalized_series_ids,
        "source_uri": source_uri,
        "http_status": http_status,
        "media_type": media_type,
        "byte_count": len(payload),
        "raw_sha256": digest,
        "artifact_path": artifact.relative_to(store_root).as_posix(),
        "fetched_at": fetched_at,
    }
    receipt_id = hashlib.sha256(_json_line(receipt_seed).encode("utf-8")).hexdigest()
    receipt = RawArtifactReceipt(receipt_id=receipt_id, **receipt_seed)

    artifact.parent.mkdir(parents=True, exist_ok=True)
    try:
        with artifact.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        existing_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if existing_digest != digest:
            raise AppendConflict(f"content-addressed artifact mismatch: {artifact}") from None

    ledger_path = store_root / "ledgers" / "raw_receipts.jsonl"
    existing = _read_jsonl(ledger_path)
    for row in existing:
        if row.get("receipt_id") == receipt_id:
            if row != receipt.model_dump(mode="json"):
                raise AppendConflict(f"raw receipt {receipt_id} already exists with different data")
            return receipt
    _append_line(ledger_path, _json_line(receipt.model_dump(mode="json")))
    return receipt


def read_raw_artifact_receipts(store_root: Path) -> list[RawArtifactReceipt]:
    rows: list[RawArtifactReceipt] = []
    for row in _read_jsonl(store_root / "ledgers" / "raw_receipts.jsonl"):
        series_ids = row.get("series_ids")
        if not isinstance(series_ids, list):
            raise AppendConflict("raw receipt ledger series_ids must be an array")
        rows.append(RawArtifactReceipt.model_validate(
            {**row, "series_ids": tuple(series_ids)}, strict=True,
        ))
    return rows


class RawReceiptCorrection(BaseModel):
    """Append-only correction that supersedes receipt metadata, never raw bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    correction_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_receipt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    replacement_receipt_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1)
    corrected_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def correction_contract(self) -> "RawReceiptCorrection":
        _require_aware_timestamp(self.corrected_at, "corrected_at")
        if self.supersedes_receipt_id == self.replacement_receipt_id:
            raise ValueError("a receipt correction must point to a different receipt")
        return self


def append_raw_receipt_correction(
    store_root: Path,
    *,
    supersedes_receipt_id: str,
    replacement_receipt_id: str,
    reason: str,
    corrected_at: str,
) -> RawReceiptCorrection:
    """Append a validated receipt-metadata correction with an explicit replacement."""
    receipts = {
        str(row.get("receipt_id")): row
        for row in _read_jsonl(store_root / "ledgers" / "raw_receipts.jsonl")
    }
    if supersedes_receipt_id not in receipts or replacement_receipt_id not in receipts:
        raise AppendConflict("receipt correction references an unknown receipt")
    prior = receipts[supersedes_receipt_id]
    replacement = receipts[replacement_receipt_id]
    if (
        prior.get("source_id") != replacement.get("source_id")
        or prior.get("raw_sha256") != replacement.get("raw_sha256")
    ):
        raise AppendConflict(
            "receipt correction must preserve source_id and exact raw_sha256"
        )
    seed = {
        "supersedes_receipt_id": supersedes_receipt_id,
        "replacement_receipt_id": replacement_receipt_id,
        "reason": reason,
        "corrected_at": corrected_at,
    }
    correction = RawReceiptCorrection(
        correction_id=hashlib.sha256(_json_line(seed).encode("utf-8")).hexdigest(),
        **seed,
    )
    path = store_root / "ledgers" / "raw_receipt_corrections.jsonl"
    existing = _read_jsonl(path)
    for row in existing:
        if row.get("correction_id") == correction.correction_id:
            if row != correction.model_dump(mode="json"):
                raise AppendConflict("raw receipt correction conflicts with existing row")
            return correction
        if row.get("supersedes_receipt_id") == supersedes_receipt_id:
            raise AppendConflict("raw receipt already has a different correction")
    _append_line(path, _json_line(correction.model_dump(mode="json")))
    return correction


def read_raw_receipt_corrections(store_root: Path) -> list[RawReceiptCorrection]:
    return [
        RawReceiptCorrection.model_validate(row, strict=True)
        for row in _read_jsonl(store_root / "ledgers" / "raw_receipt_corrections.jsonl")
    ]


class NormalizedObservation(BaseModel):
    """One exact, vintage-aware numeric value tied to immutable response bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    source_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    series_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    observation_date: str
    vintage_date: str
    revision_seq: int = Field(ge=0)
    available_at: str
    fetched_at: str
    raw_value: str
    value: str
    raw_unit: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    semantic_type: Literal[
        "level", "rate", "index", "probability", "count", "currency", "ratio", "other"
    ]
    transformation_id: str = Field(min_length=1)
    transformation_formula: str | None = None
    parser_version: str = Field(min_length=1)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_observation_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def temporal_and_unit_contract(self) -> "NormalizedObservation":
        observation_date = _require_iso_date(self.observation_date, "observation_date")
        vintage_date = _require_iso_date(self.vintage_date, "vintage_date")
        available_at = _require_aware_timestamp(self.available_at, "available_at")
        fetched_at = _require_aware_timestamp(self.fetched_at, "fetched_at")
        raw_value = _require_decimal(self.raw_value, "raw_value")
        value = _require_decimal(self.value, "value")
        if observation_date > available_at.date():
            raise ValueError("observation_date cannot be later than available_at")
        if vintage_date > fetched_at.date():
            raise ValueError("vintage_date cannot be later than fetched_at")
        if available_at > fetched_at:
            raise ValueError("available_at cannot be later than fetched_at")
        if self.transformation_id == "identity":
            if raw_value != value or self.raw_unit != self.unit:
                raise NormalizationViolation(
                    "identity rows must preserve both the exact value and unit"
                )
            if self.transformation_formula is not None:
                raise NormalizationViolation(
                    "identity rows must not declare a transformation formula"
                )
        elif not self.transformation_formula:
            raise NormalizationViolation(
                "non-identity rows require an explicit transformation_formula"
            )
        if self.semantic_type == "probability":
            if self.unit != "fraction":
                raise NormalizationViolation(
                    "stored probabilities require explicit unit='fraction'; percent is display-only"
                )
            if not Decimal("0") <= value <= Decimal("1"):
                raise NormalizationViolation("probability values must be within [0, 1]")
        return self

    @property
    def key(self) -> tuple[object, ...]:
        """Immutable key; all requested point-in-time coordinates are explicit."""
        return (
            self.source_id,
            self.series_id,
            self.observation_date,
            self.vintage_date,
            self.revision_seq,
            self.available_at,
            self.fetched_at,
            self.unit,
            self.raw_sha256,
        )

    @property
    def observation_id(self) -> str:
        encoded = json.dumps(self.key, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def ledger_row(self) -> dict[str, object]:
        return {"observation_id": self.observation_id, **self.model_dump(mode="json")}


def _receipt_index(store_root: Path) -> dict[tuple[str, str, str], RawArtifactReceipt]:
    path = store_root / "ledgers" / "raw_receipts.jsonl"
    result: dict[tuple[str, str, str], RawArtifactReceipt] = {}
    for raw in _read_jsonl(path):
        raw_series_ids = raw.get("series_ids")
        if not isinstance(raw_series_ids, list):
            raise AppendConflict("raw receipt ledger series_ids must be an array")
        payload = {
            **raw,
            "series_ids": tuple(raw_series_ids),
        }
        receipt = RawArtifactReceipt.model_validate(payload, strict=True)
        result[(receipt.source_id, receipt.raw_sha256, receipt.fetched_at)] = receipt
    return result


def _verify_receipt_artifact(store_root: Path, receipt: RawArtifactReceipt) -> None:
    artifact = store_root / receipt.artifact_path
    try:
        resolved = artifact.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RawArtifactMissing(f"raw artifact is missing: {artifact}") from exc
    raw_root = (store_root / "raw").resolve()
    if raw_root not in resolved.parents:
        raise RawArtifactMissing("receipt artifact_path escapes the raw artifact root")
    payload = resolved.read_bytes()
    if len(payload) != receipt.byte_count:
        raise RawArtifactMissing(f"raw artifact byte count changed: {artifact}")
    if hashlib.sha256(payload).hexdigest() != receipt.raw_sha256:
        raise RawArtifactMissing(f"raw artifact hash changed: {artifact}")


def verify_raw_artifact_receipt(
    store_root: Path,
    policy: AuthoritativeSourcePolicy,
    receipt: RawArtifactReceipt,
) -> None:
    """Revalidate authority, URI binding, HTTP result, and immutable raw bytes."""
    source = policy.rule_for(receipt.source_id)
    _assert_safe_source_uri(receipt.source_uri)
    _assert_source_domain(source, receipt.source_uri)
    if not 200 <= receipt.http_status < 300:
        raise RawArtifactMissing(
            f"raw receipt {receipt.receipt_id} has unsuccessful HTTP status "
            f"{receipt.http_status}"
        )
    _verify_receipt_artifact(store_root, receipt)


def append_normalized_observations(
    store_root: Path,
    policy: AuthoritativeSourcePolicy,
    observations: Iterable[NormalizedObservation],
) -> list[NormalizedObservation]:
    """Append authorized observations; never rewrite, clip, coerce, or normalize values."""
    proposed = tuple(
        NormalizedObservation.model_validate(item.model_dump(mode="python"), strict=True)
        for item in observations
    )
    if not proposed:
        return []
    receipts = _receipt_index(store_root)
    ledger_path = store_root / "ledgers" / "normalized_observations.jsonl"
    existing_rows = _read_jsonl(ledger_path)
    existing: list[NormalizedObservation] = []
    existing_by_id: dict[str, dict[str, object]] = {}
    known_by_lineage: dict[tuple[str, str, str], list[NormalizedObservation]] = {}
    for raw in existing_rows:
        observation_id = raw.get("observation_id")
        if not isinstance(observation_id, str) or not _SHA256_RE.fullmatch(observation_id):
            raise AppendConflict(f"normalized observation ledger has an invalid observation_id")
        model_payload = {key: value for key, value in raw.items() if key != "observation_id"}
        observation = NormalizedObservation.model_validate(model_payload, strict=True)
        if observation.observation_id != observation_id:
            raise AppendConflict(f"normalized observation_id does not match its immutable key")
        existing.append(observation)
        existing_by_id[observation_id] = raw
        known_by_lineage.setdefault(
            (observation.source_id, observation.series_id, observation.observation_date),
            [],
        ).append(observation)

    appended: list[NormalizedObservation] = []
    rows_to_append: list[str] = []
    for observation in proposed:
        policy.require_numeric_source(observation.source_id)
        receipt = receipts.get(
            (observation.source_id, observation.raw_sha256, observation.fetched_at)
        )
        if receipt is None:
            raise RawArtifactMissing(
                "normalized observation requires a prior receipt with matching "
                "source_id, raw_sha256, and fetched_at"
            )
        verify_raw_artifact_receipt(store_root, policy, receipt)
        if receipt.series_ids and observation.series_id not in receipt.series_ids:
            raise RawArtifactMissing(
                f"receipt {receipt.receipt_id} does not declare series {observation.series_id!r}"
            )
        row = observation.ledger_row()
        prior_same_id = existing_by_id.get(observation.observation_id)
        if prior_same_id is not None:
            if prior_same_id != row:
                raise AppendConflict(
                    f"observation {observation.observation_id} already exists with different data"
                )
            continue

        lineage_key = (
            observation.source_id, observation.series_id, observation.observation_date,
        )
        lineage = known_by_lineage.get(lineage_key, [])
        same_revision = [
            item for item in lineage
            if item.vintage_date == observation.vintage_date
            and item.revision_seq == observation.revision_seq
        ]
        if not lineage:
            if observation.revision_seq != 0 or observation.supersedes_observation_id is not None:
                raise AppendConflict(
                    "the first observation revision must use revision_seq=0 without supersedes"
                )
        elif same_revision:
            prior = max(
                same_revision,
                key=lambda item: _require_aware_timestamp(item.fetched_at, "fetched_at"),
            )
            semantic_fields = (
                "available_at", "raw_value", "value", "raw_unit", "unit",
                "semantic_type", "transformation_id", "transformation_formula",
                "parser_version", "supersedes_observation_id",
            )
            changed = [
                field_name for field_name in semantic_fields
                if getattr(prior, field_name) != getattr(observation, field_name)
            ]
            if changed:
                raise AppendConflict(
                    "an existing revision changed without a new revision_seq: "
                    + ", ".join(changed)
                )
        else:
            latest_revision_seq = max(item.revision_seq for item in lineage)
            latest = max(
                (item for item in lineage if item.revision_seq == latest_revision_seq),
                key=lambda item: _require_aware_timestamp(item.fetched_at, "fetched_at"),
            )
            if observation.revision_seq != latest.revision_seq + 1:
                raise AppendConflict("revision_seq must increment the latest revision by exactly one")
            if observation.supersedes_observation_id != latest.observation_id:
                raise AppendConflict("a revision must explicitly supersede the latest observation_id")
            if observation.vintage_date < latest.vintage_date:
                raise AppendConflict("vintage_date cannot move backwards across revisions")

        rows_to_append.append(_json_line(row))
        existing_by_id[observation.observation_id] = row
        known_by_lineage.setdefault(lineage_key, []).append(observation)
        appended.append(observation)
    _append_lines(ledger_path, rows_to_append)
    return appended


def read_normalized_observations(
    store_root: Path,
    *,
    series_id: str | None = None,
    as_of: str | None = None,
) -> list[NormalizedObservation]:
    """Read the immutable ledger with an optional point-in-time knowledge cutoff."""
    cutoff = _require_aware_timestamp(as_of, "as_of") if as_of is not None else None
    path = store_root / "ledgers" / "normalized_observations.jsonl"
    rows: list[NormalizedObservation] = []
    for raw in _read_jsonl(path):
        observation_id = raw.pop("observation_id", None)
        observation = NormalizedObservation.model_validate(raw, strict=True)
        if observation.observation_id != observation_id:
            raise AppendConflict("normalized observation ledger key hash mismatch")
        if series_id is not None and observation.series_id != series_id:
            continue
        if cutoff is not None and _require_aware_timestamp(
            observation.available_at, "available_at"
        ) > cutoff:
            continue
        if cutoff is not None and _require_aware_timestamp(
            observation.fetched_at, "fetched_at"
        ) > cutoff:
            continue
        rows.append(observation)
    return rows
