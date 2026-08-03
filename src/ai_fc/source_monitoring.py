"""D0 source-health monitors for candidate market-data feeds.

Candidate feeds stay disabled until their preregistered stability and license
gates pass. Receipts contain schema/response fingerprints only; raw provider
values are neither archived nor redistributed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .market_extensions import MarketExtensionError
from .quant import feed

DEFILLAMA_CONTRACT = Path("data/contracts/defillama_stablecoins.yaml")
DEFILLAMA_RECEIPTS = Path("data/source_monitoring/defillama_stablecoins")
DEFILLAMA_STATUS = Path("data/source_monitoring/defillama_stablecoins_status.json")


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if value is None:
        return "null"
    return "string"


def _schema_descriptor(row: dict[str, Any]) -> dict[str, Any]:
    descriptor: dict[str, Any] = {}
    for key in sorted(row):
        value = row[key]
        descriptor[key] = {
            "type": _type_name(value),
            **({"keys": sorted(value)} if isinstance(value, dict) else {}),
        }
    return descriptor


def _validate_defillama(raw: str) -> tuple[list[dict[str, Any]], str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MarketExtensionError("DefiLlama monitor returned invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) < 365:
        raise MarketExtensionError("DefiLlama monitor history is unexpectedly short")
    samples = (payload[0], payload[len(payload) // 2], payload[-1])
    required = {"date", "totalCirculating", "totalCirculatingUSD"}
    for row in samples:
        if not isinstance(row, dict) or not required.issubset(row):
            raise MarketExtensionError("DefiLlama monitor schema is incompatible")
        if not str(row["date"]).isdigit():
            raise MarketExtensionError("DefiLlama monitor date is not a Unix timestamp")
        usd = row["totalCirculatingUSD"]
        if not isinstance(usd, dict) or not isinstance(usd.get("peggedUSD"), (int, float)):
            raise MarketExtensionError("DefiLlama monitor USD aggregate is missing")
    descriptor = _schema_descriptor(payload[-1])
    schema_sha = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    latest = datetime.fromtimestamp(int(payload[-1]["date"]), timezone.utc).date().isoformat()
    return payload, schema_sha, latest


def _receipt_files(root: Path) -> list[Path]:
    folder = root / DEFILLAMA_RECEIPTS
    return sorted(path for path in folder.glob("*.json") if path.stem[:4].isdigit())


def _consecutive_tail(receipts: list[dict[str, Any]]) -> int:
    days = sorted(date.fromisoformat(item["checked_date"]) for item in receipts)
    if not days:
        return 0
    count = 1
    for newer, older in zip(reversed(days), reversed(days[:-1])):
        if (newer - older).days != 1:
            break
        count += 1
    return count


def collect_defillama_health(
    root: Path, *, asof: date | None = None, now: datetime | None = None,
    fetch_text: Callable[..., str] = feed.get_with_curl_fallback,
) -> tuple[Path, dict[str, Any], bool]:
    contract = yaml.safe_load((root / DEFILLAMA_CONTRACT).read_text(encoding="utf-8"))
    if contract.get("enabled") is not False:
        raise MarketExtensionError("D0 monitor only runs while DefiLlama remains disabled")
    checked_date = asof or date.today()
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
        timespec="seconds")
    endpoint = str(contract["endpoint"])
    raw = fetch_text(endpoint, timeout=30)
    payload, schema_sha, latest_observation = _validate_defillama(raw)
    receipt = {
        "schema_version": 1,
        "source_id": "defillama_stablecoins",
        "checked_date": checked_date.isoformat(),
        "status": "success",
        "http_status": 200,
        "observations": len(payload),
        "schema_fingerprint": schema_sha,
        "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "observation_period": latest_observation,
        "available_at": checked_at,
        "source_url": endpoint,
        "source_fingerprint": schema_sha,
        "revision_vintage": "captured_current",
        "raw_values_redistributed": False,
    }
    archive = root / DEFILLAMA_RECEIPTS / f"{checked_date.isoformat()}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive_changed = False
    if archive.exists():
        existing = json.loads(archive.read_text(encoding="utf-8"))
        if existing.get("schema_fingerprint") != schema_sha:
            raise MarketExtensionError(
                f"DefiLlama schema changed within monitoring day {checked_date}")
    else:
        archive.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        archive_changed = True

    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in _receipt_files(root)]
    consecutive = _consecutive_tail(receipts)
    schema_stable = len({item["schema_fingerprint"] for item in receipts[-consecutive:]}) == 1
    monitoring_gate_met = consecutive >= 14 and schema_stable
    license_status = str(contract.get("license_status") or "review_required")
    activation_eligible = monitoring_gate_met and license_status == "approved"
    status_name = (
        "eligible_for_manual_activation" if activation_eligible
        else "license_review_required" if monitoring_gate_met
        else "monitoring"
    )
    status = {
        "schema_version": 1,
        "source_id": "defillama_stablecoins",
        "status": status_name,
        "asof": checked_date.isoformat(),
        "latest_observation": latest_observation,
        "consecutive_successful_days": consecutive,
        "required_successful_days": 14,
        "schema_stable": schema_stable,
        "monitoring_gate_met": monitoring_gate_met,
        "license_status": license_status,
        "activation_eligible": activation_eligible,
        "raw_values_redistributed": False,
        "latest_receipt": archive.relative_to(root).as_posix(),
        "reason": (
            "monitoring and license gates passed; manual contract activation still required"
            if activation_eligible else
            "schema gate passed; explicit redistribution license review is still required"
            if monitoring_gate_met else
            f"daily schema monitoring in progress ({consecutive}/14)"
        ),
    }
    status_path = root / DEFILLAMA_STATUS
    status_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
    status_changed = not status_path.exists() or status_path.read_text(encoding="utf-8") != serialized
    if status_changed:
        status_path.write_text(serialized, encoding="utf-8", newline="\n")
    return status_path, status, archive_changed or status_changed
