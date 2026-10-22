"""Narrow, audited FRB substitutes for current display statistics (never ALFRED).

Only explicitly mapped series are eligible. A substitute must reproduce every
stored overlapping observation and cover the previous endpoint before promotion.
The original download, rather than a fabricated FRED CSV, is retained as evidence.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

H6 = "https://www.federalreserve.gov/releases/h6/data/FRB_h6_xml.zip"
H15 = "https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip"
# Same current-release table ZIP used by the existing approved Z.1 collector.
# The separate all-series FRB_Z1_csv.zip has a different format and size.
Z1 = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
# No reverse engineering of a series by numeric similarity. These identifiers
# and units belong to the publisher's series dictionary.
SERIES = {
    "M2SL": (H6, "M2.M", "billions_usd", "SA", "129", "Currency", "1e+09"),
    "FEDFUNDS": (H15, "RIFSPFF_N.M", "percent", None, "129", "Percent:_Per_Year", "1"),
    "GS10": (H15, "RIFLGFCY10_N.M", "percent", None, "129", "Percent:_Per_Year", "1"),
    "BOGZ1LM153064475Q": (Z1, "LM153064475.Q", "millions_usd", None, None, None, None),
    "BOGZ1LM893064105Q": (Z1, "LM893064105.Q", "millions_usd", None, None, None, None),
}


class NativeSourceError(ValueError):
    """A source is unavailable, incompatible, or differs from its approved overlap."""


def parse_native(raw: bytes, series_id: str, *, cutoff: date) -> list[dict[str, Any]]:
    url, field, _unit, adjusted, freq, unit, mult = SERIES[series_id]
    if len(raw) > 30_000_000:
        raise NativeSourceError("native download exceeds size budget")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 150_000_000:
            raise NativeSourceError("native expanded download exceeds size budget")
        rows: list[tuple[str, str]] = []
        if url == Z1:
            member = {"BOGZ1LM153064475Q": "csv/S1M_e_b.csv",
                      "BOGZ1LM893064105Q": "csv/F51_1_s.csv"}[series_id]
            table = csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig")))
            if field not in (table.fieldnames or []):
                raise NativeSourceError(f"missing native field: {field}")
            for row in table:
                label, value = row["date"], row[field]
                if value in ("", "ND"):
                    continue
                if len(label) != 7 or label[4:6] != ":Q" or label[-1] not in "1234":
                    raise NativeSourceError("invalid native quarterly date")
                rows.append((f"{label[:4]}-{(int(label[-1])-1)*3+1:02d}-01", value))
        else:
            member = "H6_data.xml" if url == H6 else "H15_data.xml"
            xml = archive.read(member)
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise NativeSourceError("native XML entities are forbidden")
            tree = ET.fromstring(xml)
            matches = [x for x in tree.iter() if x.tag.rsplit("}", 1)[-1] == "Series"
                       and x.get("SERIES_NAME") == field]
            if len(matches) != 1:
                raise NativeSourceError("native series identity is not unique")
            series = matches[0]
            if (series.get("FREQ") != freq or series.get("UNIT") != unit
                    or series.get("UNIT_MULT") != mult
                    or adjusted and series.get("ADJUSTED") != adjusted):
                raise NativeSourceError("native frequency/adjustment/unit changed")
            for obs in series:
                if obs.tag.rsplit("}", 1)[-1] != "Obs":
                    continue
                if obs.get("OBS_STATUS") == "ND":
                    continue
                if obs.get("OBS_STATUS") != "A":
                    raise NativeSourceError("unsupported native observation status")
                observed = date.fromisoformat(obs.attrib["TIME_PERIOD"])
                # FRB uses month-end labels; FRED uses month-start for the same
                # monthly observation. No daily values are averaged or filled.
                rows.append((observed.replace(day=1).isoformat(), obs.attrib["OBS_VALUE"]))
    result, seen = [], set()
    for observed, value in rows:
        day, number = date.fromisoformat(observed), float(value)
        if not math.isfinite(number) or observed in seen:
            raise NativeSourceError("native duplicate/non-finite observation")
        if series_id in {"M2SL", "BOGZ1LM153064475Q", "BOGZ1LM893064105Q"} and number <= 0:
            raise NativeSourceError("native monetary/equity level must be positive")
        if day > cutoff:
            raise NativeSourceError("native future observation")
        seen.add(observed)
        result.append({"date": observed, "value": number})
    result.sort(key=lambda x: x["date"])
    if not result:
        raise NativeSourceError("native series is empty")
    return result


def verify_overlap(rows: list[dict[str, Any]], previous: list[dict[str, Any]],
                   *, minimum: int = 24) -> dict[str, Any]:
    old = {r["date"]: r["value"] for r in previous}
    new = {r["date"]: r["value"] for r in rows}
    common = sorted(old.keys() & new.keys())
    if len(common) < minimum or old.keys() - new.keys():
        raise NativeSourceError("native coverage does not retain approved history")
    differences = [d for d in common if abs(old[d] - new[d]) > max(1e-8, abs(old[d])*1e-12)]
    if differences:
        raise NativeSourceError(f"native overlap differs: {len(differences)} observations")
    return {"policy": "frb-exact-overlap-v1", "observations": len(common),
            "differences": 0, "previous_through": max(old), "native_through": max(new)}


class NativeCollector:
    def __init__(self, request: Callable[[str], bytes]):
        self.request, self.downloads = request, {}

    def fetch(self, series_id: str, *, start: str, cutoff: date,
              previous: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bytes, dict[str, Any]]:
        url = SERIES[series_id][0]
        if url not in self.downloads:
            self.downloads[url] = self.request(url)
        raw = self.downloads[url]
        rows = [r for r in parse_native(raw, series_id, cutoff=cutoff) if r["date"] >= start]
        audit = verify_overlap(rows, previous)
        return rows, raw, {
            "source_url": url, "request_url": url, "provider": "Federal Reserve Board (direct release)",
            "policy_source_id": "federal_reserve_board", "authority_class": "official_statistical_agency",
            "media_type": "application/zip", "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "refresh_status": "verified_native_fallback", "equivalence_audit": audit,
        }


def collect_current(root: Path, specs: dict[str, Any], *, fetcher, request,
                    cutoff: date) -> tuple[dict, dict, dict]:
    """Isolate an upstream outage without disguising old observations as new.

    A cache is allowed only from the approved append-only store, with every
    selected observation bound to intact raw bytes. A semantic/parser failure
    remains fatal. Missing coverage is quarantined and retains the dated cache.
    """
    from . import fred_api
    from .authoritative_statistics import (
        load_authoritative_source_policy, read_normalized_observations,
        read_raw_artifact_receipts, verify_raw_artifact_receipt, persist_raw_artifact,
    )
    from .statistics_lab import load_statistics_lab, _load_authoritative_current_rows
    previous = load_statistics_lab(root)
    meta = {x["series_id"]: x for x in previous.get("sources", [])}
    preferences = {k: v["policy_source_id"] for k, v in meta.items() if k in specs}
    cached = _load_authoritative_current_rows(root, source_preferences=preferences)
    store = root / "data/statistics/official_store"
    policy = load_authoritative_source_policy(root / "data/contracts/authoritative_statistics_sources.yaml")
    receipts = {(r.source_id, r.raw_sha256, r.fetched_at): r for r in read_raw_artifact_receipts(store)}
    verified = set()
    cached_observations = read_normalized_observations(store)
    for row in cached_observations:
        if row.series_id not in specs or row.source_id != preferences.get(row.series_id):
            continue
        key = row.source_id, row.raw_sha256, row.fetched_at
        receipt = receipts.get(key)
        if receipt is None or row.series_id not in receipt.series_ids:
            raise NativeSourceError("cached observation has no declared raw receipt")
        if row.unit != specs[row.series_id]["unit"]:
            raise NativeSourceError("cached observation unit differs from contract")
        if key not in verified:
            verify_raw_artifact_receipt(store, policy, receipt)
            verified.add(key)
    for sid in specs:
        item = meta.get(sid, {})
        bound = [r for r in receipts.values() if r.source_id == preferences.get(sid)
                 and r.raw_sha256 == item.get("raw_sha256") and sid in r.series_ids]
        if (not bound or not cached.get(sid)
                or item.get("latest_observation") != cached[sid][-1]["date"]
                or item.get("latest_observation", "") > cutoff.isoformat()
                or item.get("raw_path") != "data/statistics/official_store/" + bound[-1].artifact_path):
            raise NativeSourceError(f"cached source summary is not bound to its ledger: {sid}")
        verify_raw_artifact_receipt(store, policy, bound[-1])
    native = NativeCollector(request)
    def native_candidate(sid, previous):
        if specs[sid]["unit"] != SERIES[sid][2]:
            raise NativeSourceError("configured unit differs from native contract")
        return native.fetch(sid, start=specs[sid].get("window_start", "1995-01-01"),
                            cutoff=cutoff, previous=previous)
    source_rows, raw_payloads, metadata = {}, {}, {}
    offline = False
    failed_probes = 0
    circuit_reason = "fred_api_unavailable"
    for sid, spec in specs.items():
        failure = None
        if not offline:
            try:
                rows, raw = fetcher(sid)
                regressed = (not rows or rows[-1]["date"] < cached[sid][-1]["date"]
                             or bool({r["date"] for r in cached[sid]} - {r["date"] for r in rows}))
                if sid in SERIES:
                    try:
                        # Compare with the fetched FRED vintage when complete;
                        # otherwise require the entire previously approved view.
                        # A HTTP 200 with an old endpoint is not a freshness gate.
                        nr, nb, nm = native_candidate(sid, cached[sid] if regressed else rows)
                    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
                        pass  # a rejected optional candidate cannot suppress healthy FRED
                    else:
                        if regressed or nr[-1]["date"] > rows[-1]["date"]:
                            nm["refresh_reason"] = "fred_valid_response_behind_verified_native_release"
                            source_rows[sid], raw_payloads[sid], metadata[sid] = nr, nb, nm
                            failed_probes = 0
                            continue
                if regressed and sid == "DCOILWTICO":
                    from .wti_history import review_current, WtiCoverageError
                    try:
                        history = review_current(root, rows=rows, raw=raw,
                                                 cached=cached[sid], observations=cached_observations,
                                                 cutoff=cutoff)
                    except WtiCoverageError:
                        pass  # unreviewed omissions keep the existing quarantine
                    else:
                        # Only actually returned current rows cross the append
                        # boundary. The canonical view retains the separately
                        # pinned archive revisions with their original clocks.
                        source_rows[sid], raw_payloads[sid] = rows, raw
                        metadata[sid] = {"refresh_status": "current_fred", "history_coverage": history}
                        failed_probes = 0
                        continue
                if regressed:
                    # A decoded but incomplete response is evidence, not a new
                    # approved vintage. Preserve it without normalizing any rows
                    # or rebinding the retained observations to its new receipt.
                    rejected = persist_raw_artifact(
                        store, policy, source_id="fred_market_signals", payload=raw,
                        source_uri=fred_api.observations_public_url(
                            sid, observation_start=spec.get("window_start", "1995-01-01")),
                        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        http_status=200, media_type="text/csv", series_ids=[sid],
                    )
                    missing = sorted({r["date"] for r in cached[sid]} - {r["date"] for r in rows})
                    source_rows[sid] = cached[sid]
                    metadata[sid] = {
                        **meta[sid], "refresh_status": "verified_cache_waiting_source",
                        "refresh_reason": "fred_coverage_regressed",
                        "coverage_audit": {
                            "missing_count": len(missing), "missing_dates_sample": missing[:32],
                            "approved_endpoint": cached[sid][-1]["date"],
                            "received_endpoint": rows[-1]["date"] if rows else None,
                            "rejected_raw_sha256": rejected.raw_sha256,
                            "rejected_receipt_id": rejected.receipt_id,
                            "rejected_raw_path": "data/statistics/official_store/" + rejected.artifact_path,
                        },
                    }
                    failed_probes = 0
                    continue
                source_rows[sid], raw_payloads[sid] = rows, raw
                metadata[sid] = {"refresh_status": "current_fred"}
                failed_probes = 0
                continue
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                if isinstance(exc, fred_api.FredApiError) and not (
                    "3 attempts" in str(exc) or "FRED_API_KEY" in str(exc)
                ):
                    raise
                if (isinstance(exc, RuntimeError) and not isinstance(exc, fred_api.FredApiError)
                        and not str(exc).startswith(("curl transport unavailable", "curl failed", "curl --resolve failed"))):
                    raise
                # Never persist transport exception text: it may contain a
                # request URL with credentials. Only a closed reason code.
                circuit_reason = "fred_credentials_unavailable" if "FRED_API_KEY" in str(exc) else "fred_api_unavailable"
                # A failure for one series is not proof that all other FRED
                # series are unavailable. Probe a different series before
                # opening the circuit; a successful response resets it.
                failed_probes += 1
                offline, failure = failed_probes >= 2, circuit_reason
        else:
            failure = "fred_api_probe_circuit_open"
        if sid in SERIES:
            try:
                rows, raw, native_meta = native_candidate(sid, cached[sid])
                native_meta["refresh_reason"] = failure
                source_rows[sid], raw_payloads[sid], metadata[sid] = rows, raw, native_meta
                continue
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
                failure = "native_unavailable_or_equivalence_rejected"
        prior = meta.get(sid)
        if not prior or not cached.get(sid):
            raise NativeSourceError(f"no verified previous observations: {sid}")
        # Keep the *original* availability time and raw identity for old rows.
        # No synthetic observation or fresh acquisition receipt is appended.
        source_rows[sid] = cached[sid]
        metadata[sid] = {**prior, "refresh_status": "verified_cache_waiting_source",
                         "refresh_reason": failure}
    return source_rows, raw_payloads, metadata
