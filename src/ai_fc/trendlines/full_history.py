"""Additive, private geometry for every captured finalized observation.

The captured period is not a claim of history since listing. Original captures,
the approved store and the three existing windows are never rewritten. Readers
verify immutable transport bindings; refresh/verify additionally replay source
evidence and independently check scalar line arithmetic.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import contracts as C, display as D, engine as E, research as R, storage as S

ROOT = Path("data/trendlines_research_full")
SNAPSHOT_PREFIX = "research-full-snapshot-"
SNAPSHOT_RE = re.compile(re.escape(SNAPSHOT_PREFIX) + r"[0-9a-f]{64}\Z")
TRANSPORT_CONTRACT = "trendlines_private_full_transport_v1"
MANIFEST_CONTRACT = "trendlines_private_full_manifest_v1"
CHUNK_CONTRACT = "trendlines_private_full_bars_v1"
MAX_BARS = 4096
CHUNK_SIZE = 512
MINIMUM_BARS = 771
SCOPE = "all_captured_finalized_sessions"
BAR_COLUMNS = R.PRIVATE_BAR_COLUMNS


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "content_hash": C.canonical_hash(body)}


def _path(root: Path, relative: Path) -> Path:
    return S.safe_path(Path(root), relative.as_posix())


def _config(archive: dict[str, Any], count: int) -> dict[str, Any]:
    if type(count) is not int or not 1 <= count <= MAX_BARS:
        raise C.TrendlinesError("full_history_bar_count_out_of_bounds_no_truncation")
    return {"schema_version": 1, "contract_id": "trendlines_private_full_geometry_v1",
            "full_scope": SCOPE, "max_bars": MAX_BARS, "chunk_size": CHUNK_SIZE,
            "points_encoding": "equations", "axes": ["linear", "log"],
            "source_config_sha256": C.canonical_hash(archive["config"]),
            "parameters": {"bars": count, "minimum_bars": MINIMUM_BARS,
                           "left": 10, "right": 10, "min_anchor_gap": 60}}


def _normalize(archive: dict[str, Any]):
    """Use calendar ordinals, including missing sessions, without price filling."""
    asset, settings, cutoff = archive["asset"], archive["config"], archive["capture_asof"]
    C.validate_config(settings)
    C.validate_research_source(asset, archive["source_policy"])
    rows = E._select_rows(archive["bars"], asset, cutoff)
    _config(archive, len(rows))
    if any(C.aware_time(row["fetched_at"]) != C.aware_time(row["available_at"]) for row in rows):
        raise C.TrendlinesError("full_history_capture_availability_binding_invalid")
    expected = E._completed(asset, cutoff, settings, archive["source_policy"], research=True)
    end = max((date.fromisoformat(rows[-1]["session_date"]) + timedelta(days=120)).isoformat(),
              expected or rows[-1]["session_date"])
    schedule = C.session_schedule(asset["calendar_id"], rows[0]["session_date"], end)
    coordinates = {day: index for index, (day, _opened, _closed) in enumerate(schedule)}
    for row in rows:
        if expected is None or row["session_date"] > expected:
            raise C.TrendlinesError("full_history_unfinalized_candle")
        row.update(session=row["session_date"], session_index=coordinates[row["session_date"]])
    last = rows[-1]["session_index"]
    future = [{"offset": offset, "index": last + offset, "session": schedule[last + offset][0]}
              for offset in settings["projections"]["crypto" if asset["kind"] == "crypto" else "exchange"]]
    return rows, future


def _scalar_price(line: dict[str, Any], index: int) -> float | None:
    """Independent anchor interpolation; never use the engine equation helper."""
    first, second = line["first_anchor"], line["second_anchor"]
    ratio = (index - first["index"]) / (second["index"] - first["index"])
    try:
        if line["axis"] == "linear":
            value = first["price"] + (second["price"] - first["price"]) * ratio
        else:
            value = math.exp(math.log(first["price"]) +
                             (math.log(second["price"]) - math.log(first["price"])) * ratio)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _near(actual, expected, name: str) -> None:
    if actual is None or expected is None:
        if actual is not expected:
            raise C.TrendlinesError("full_history_scalar_" + name)
    elif (isinstance(actual, bool) or not isinstance(actual, (int, float))
          or not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6)):
        raise C.TrendlinesError("full_history_scalar_" + name)


def _scalar_verify(rows, asset, settings, spec, config_hash, analyses, audit_lines, future) -> dict[str, Any]:
    """Independent ATR, pivot contacts, anchor arithmetic and selected borders."""
    period = settings["atr"]["period"]
    atr, ranges = [None], []
    for before, row in zip(rows, rows[1:]):
        if row["session_index"] != before["session_index"] + 1:
            ranges = []
            atr.append(None)
        else:
            ranges.append(max(row["high"] - row["low"], abs(row["high"] - before["close"]),
                              abs(row["low"] - before["close"])))
            atr.append(math.fsum(ranges[-period:]) / period if len(ranges) >= period else None)
    def contiguous(start, end):
        return all(rows[i + 1]["session_index"] == rows[i]["session_index"] + 1 for i in range(start, end))
    pivots = {"support": [], "resistance": []}
    for side, column in (("support", "low"), ("resistance", "high")):
        for i in range(spec["left"], len(rows) - spec["right"]):
            left, right = i - spec["left"], i + spec["right"]
            value = rows[i][column]
            a, b = rows[left:i], rows[i + 1:right + 1]
            valid = (all(value < row[column] for row in a) and all(value <= row[column] for row in b)
                     if side == "support" else
                     all(value > row[column] for row in a) and all(value >= row[column] for row in b))
            if contiguous(left, right) and valid:
                known = max(C.aware_time(row[field]) for row in rows[left:right + 1]
                            for field in ("available_at", "fetched_at"))
                pivots[side].append({"row": i, "confirmation_row": right, "session": rows[i]["session_date"],
                                     "index": rows[i]["session_index"], "price": value, "bar_id": rows[i]["bar_id"],
                                     "confirmed_at": known.isoformat(), "confirmation_session": rows[right]["session_date"]})
    def epsilon(price, volatility):
        return max(asset.get("tick_size", 0.0), settings["touch"]["atr_multiple"] * volatility,
                   settings["touch"]["price_fraction"] * price, 1e-12 * price)
    def rank(line):
        return (-line["touch_count"], -line["latest_touch_index"], -line["anchor_span"],
                line["formation_penetration"], math.inf if line["distance_score"] is None else line["distance_score"],
                line["line_id"])
    expected_ids = {axis: set() for axis in analyses}
    if len(rows) >= MINIMUM_BARS:
        # Enumerate every pair independently. A producer omission must not make
        # both the candidate manifest and the nearest boundary appear complete.
        for axis in analyses:
            for side, side_pivots in pivots.items():
                for offset, first in enumerate(side_pivots):
                    for second in side_pivots[offset + 1:]:
                        start, stop = first["row"], second["confirmation_row"]
                        span = second["index"] - first["index"]
                        if (span < spec["min_anchor_gap"] or first["price"] == second["price"]
                                or not contiguous(max(0, start - spec["left"]), stop)
                                or any(atr[i] is None for i in range(start, stop + 1))):
                            continue
                        oracle = {"axis": axis, "first_anchor": first, "second_anchor": second}
                        admitted = True
                        for i in range(start, stop + 1):
                            price = _scalar_price(oracle, rows[i]["session_index"])
                            if price is None:
                                admitted = False
                                break
                            adverse = price - rows[i]["low"] if side == "support" else rows[i]["high"] - price
                            if adverse > epsilon(price, atr[i]):
                                admitted = False
                                break
                        if admitted:
                            formation_hash = C.canonical_hash([row["bar_id"] for row in rows[start:stop + 1]])
                            identity = {"asset_id": asset["asset_id"], "axis": axis, "window": len(rows), "side": side,
                                        "first_bar_id": first["bar_id"], "second_bar_id": second["bar_id"],
                                        "config_sha256": config_hash, "formation_input_hash": formation_hash}
                            expected_ids[axis].add("trend-line-" + C.canonical_hash(identity)[:32])
    for axis, ids in expected_ids.items():
        reported = [line["line_id"] for line in audit_lines if line["axis"] == axis]
        if len(reported) != len(set(reported)) or set(reported) != ids:
            raise C.TrendlinesError("full_history_scalar_candidate_completeness")
    count = 0
    for line in audit_lines:
        side, axis = line["side"], line["axis"]
        if side not in pivots or axis not in {"linear", "log"} or line["state"] != "research_reference":
            raise C.TrendlinesError("full_history_scalar_line_identity")
        anchors = []
        for key in ("first_anchor", "second_anchor"):
            anchor = line[key]
            found = [p for p in pivots[side] if p["bar_id"] == anchor["bar_id"]]
            if len(found) != 1 or anchor != {k: found[0][k] for k in anchor}:
                raise C.TrendlinesError("full_history_scalar_anchor")
            anchors.append(found[0])
        first, second = anchors
        span = second["index"] - first["index"]
        start, stop = first["row"], second["confirmation_row"]
        if (span < spec["min_anchor_gap"] or first["price"] == second["price"]
                or not contiguous(max(0, start - spec["left"]), stop)
                or line["window"] != len(rows) or line["coordinate_origin_index"] != first["index"]
                or line["direction"] != ("rising" if second["price"] > first["price"] else "falling")):
            raise C.TrendlinesError("full_history_scalar_formation")
        transform = float if axis == "linear" else math.log
        _near(line["intercept"], transform(first["price"]), "intercept")
        _near(line["slope"], (transform(second["price"]) - transform(first["price"])) / span, "slope")
        formation_hash = C.canonical_hash([r["bar_id"] for r in rows[start:stop + 1]])
        identity = {"asset_id": asset["asset_id"], "axis": axis, "window": len(rows), "side": side,
                    "first_bar_id": first["bar_id"], "second_bar_id": second["bar_id"],
                    "config_sha256": config_hash, "formation_input_hash": formation_hash}
        known = max([C.aware_time(first["confirmed_at"]), C.aware_time(second["confirmed_at"]),
                     *(C.aware_time(row[field]) for row in rows[start:stop + 1] for field in ("available_at", "fetched_at"))])
        if (line["line_id"] != "trend-line-" + C.canonical_hash(identity)[:32]
                or line["formation_input_hash"] != formation_hash or line["activation_session"] != rows[stop]["session_date"]
                or C.aware_time(line["activation_asof"]) != known):
            raise C.TrendlinesError("full_history_scalar_issuance_binding")
        penetration = 0.0
        for i in range(start, stop + 1):
            price = _scalar_price(line, rows[i]["session_index"])
            if price is None or atr[i] is None:
                raise C.TrendlinesError("full_history_scalar_invalid_formation")
            adverse = price - rows[i]["low"] if side == "support" else rows[i]["high"] - price
            tolerance = epsilon(price, atr[i])
            if adverse > tolerance and not math.isclose(adverse, tolerance, rel_tol=1e-10, abs_tol=1e-6):
                raise C.TrendlinesError("full_history_scalar_penetration")
            penetration = max(penetration, adverse / tolerance)
        _near(line["formation_penetration"], penetration, "penetration")
        contacts = []
        for pivot in pivots[side]:
            i = pivot["row"]
            price = _scalar_price(line, pivot["index"])
            if (pivot["index"] >= first["index"] and atr[i] is not None and contiguous(start, i)
                    and price is not None and abs(pivot["price"] - price) <= epsilon(price, atr[i])):
                contacts.append({key: pivot[key] for key in ("session", "index", "price", "bar_id", "confirmed_at")})
        if (contacts != line["contacts"] or len(contacts) != line["touch_count"] or span != line["anchor_span"]
                or line["latest_touch_index"] != max(item["index"] for item in contacts)
                or line["geometry_status"] != ("confirmed" if len(contacts) >= 3 else "candidate")):
            raise C.TrendlinesError("full_history_scalar_contacts")
        current = _scalar_price(line, rows[-1]["session_index"])
        _near(line["current_price"], current, "current_price")
        distance = None if current is None or atr[-1] is None else abs(current - rows[-1]["close"]) / epsilon(current, atr[-1])
        _near(line["distance_score"], distance, "distance")
        count += 1
    for axis, windows in analyses.items():
        analysis = windows["full"]
        if len(rows) < MINIMUM_BARS:
            if analysis["status"] != "hold" or analysis["lines"] or audit_lines:
                raise C.TrendlinesError("full_history_minimum_history_hold")
            continue
        candidates = [line for line in audit_lines if line["axis"] == axis]
        expected_pivots = [{key: pivot[key] for key in ("session", "index", "price", "bar_id", "confirmation_session", "confirmed_at")}
                           | {"side": side} for side in ("support", "resistance") for pivot in pivots[side]]
        if analysis["pivots"] != expected_pivots or analysis["candidate_count"] != len(candidates):
            raise C.TrendlinesError("full_history_scalar_pivot_or_candidate_manifest")
        eligible = [line for line in candidates if line["current_price"] is not None]
        down = sorted((line for line in eligible if line["current_price"] <= rows[-1]["close"]),
                      key=lambda line: (-line["current_price"], *rank(line)))[:3]
        up = sorted((line for line in eligible if line["current_price"] > rows[-1]["close"]),
                    key=lambda line: (line["current_price"], *rank(line)))[:3]
        for side, expected in (("down", down), ("up", up)):
            actual = analysis["borders"][side]
            if [b["line_id"] for b in actual] != [line["line_id"] for line in expected]:
                raise C.TrendlinesError("full_history_scalar_border_rank")
            for border, line in zip(actual, expected):
                _near(border["price"], _scalar_price(line, rows[-1]["session_index"]), "border")
        selected = {}
        for side in ("support", "resistance"):
            for line in sorted((line for line in candidates if line["side"] == side), key=rank)[:settings["max_selected_per_side"]]:
                selected[line["line_id"]] = line
        selected.update({line["line_id"]: line for line in down + up})
        if set(selected) != {line["line_id"] for line in analysis["lines"]} or analysis["projection_sessions"] != future:
            raise C.TrendlinesError("full_history_scalar_selection_or_horizon")
        for line in analysis["lines"]:
            base = selected[line["line_id"]]
            if any(line.get(key) != value for key, value in base.items()):
                raise C.TrendlinesError("full_history_scalar_display_differs_from_audit")
            if [{k: p[k] for k in ("offset", "session", "index")} for p in line["projections"]] != future:
                raise C.TrendlinesError("full_history_scalar_projection_binding")
            for p in line["projections"]:
                value = _scalar_price(line, p["index"])
                _near(p["price"], value, "projection")
                if p["status"] != ("ready" if value is not None else "unavailable"):
                    raise C.TrendlinesError("full_history_scalar_projection_status")
            for point in line["points"]:
                _near(point["price"], _scalar_price(line, point["index"]), "point")
    return {"ok": True, "method": "independent_scalar_anchors_atr_pivots_contacts_ranks_projections", "checked_lines": count}


def _calculate(archive):
    rows, future = _normalize(archive)
    config = _config(archive, len(rows))
    config_hash = C.canonical_hash(config)
    analyses, audits, baseline = {}, [], {}
    # Same finalized inputs, rather than pretending the current 756-row view is
    # comparable to all captured rows. Long-window pivot rules happen to agree.
    old_spec = {**archive["config"]["windows"]["756"], "bars": len(rows), "minimum_bars": MINIMUM_BARS}
    for axis in config["axes"]:
        analysis, events, candidates = E._analyze(rows, archive["asset"], archive["config"], axis,
                                                 config["parameters"], future, config_hash, research=True)
        if events or analysis["events"]:
            raise C.TrendlinesError("full_history_historical_signal_forbidden")
        analyses[axis] = {"full": analysis}
        audits.extend(candidates)
        baseline[axis] = E._analyze(rows, archive["asset"], archive["config"], axis, old_spec,
                                    future, config_hash, research=True)[0]
    scalar = _scalar_verify(rows, archive["asset"], archive["config"], config["parameters"],
                            config_hash, analyses, audits, future)
    shadow = {"status": "new_supplemental_not_promoted", "input_hash": C.canonical_hash(rows),
              "baseline_parameters": old_spec, "candidate_parameters": config["parameters"],
              "baseline_input_hash": C.canonical_hash(rows), "candidate_input_hash": C.canonical_hash(rows),
              "baseline_analysis_sha256": C.canonical_hash(baseline),
              "candidate_analysis_sha256": C.canonical_hash({axis: windows["full"] for axis, windows in analyses.items()}),
              "changed_axes": [axis for axis in config["axes"] if baseline[axis] != analyses[axis]["full"]],
              "current_windows_have_different_input_scope": True,
              "current_engine_snapshot_sha256": archive["engine_snapshot"]["content_hash"],
              "current_analyses_sha256": C.canonical_hash(archive["engine_snapshot"]["analyses"])}
    return {"full_config": config, "full_config_sha256": config_hash, "input_hash": C.canonical_hash(rows),
            "bars": rows, "analyses": analyses, "audit_lines": audits, "events": [],
            "independent_validation": scalar, "shadow": shadow}


def _envelope(body):
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > R.MAX_PRIVATE_PAYLOAD_BYTES:
        raise C.TrendlinesError("full_history_payload_exceeds_256KiB")
    envelope = {"schema_version": 1, "contract_id": TRANSPORT_CONTRACT, "publication_scope": "private_only",
                "asset_id": body["asset_id"], "snapshot_id": body["snapshot_id"],
                "payload_json": payload, "payload_sha256": _sha(payload.encode("utf-8"))}
    if len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError("full_history_envelope_exceeds_512KiB")
    return envelope


def decode_envelope(envelope: dict[str, Any], expected_contract: str | None = None) -> dict[str, Any]:
    """Validate the exact transport string before exposing its JSON body."""
    try:
        if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "contract_id", "publication_scope",
                "asset_id", "snapshot_id", "payload_json", "payload_sha256"}
                or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1
                or envelope["contract_id"] != TRANSPORT_CONTRACT or envelope["publication_scope"] != "private_only"
                or envelope["asset_id"] not in R.SYMBOLS or not SNAPSHOT_RE.fullmatch(envelope["snapshot_id"])
                or not isinstance(envelope["payload_json"], str)
                or len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES):
            raise C.TrendlinesError("full_history_transport_contract_invalid")
        raw = envelope["payload_json"].encode("utf-8")
        if len(raw) > R.MAX_PRIVATE_PAYLOAD_BYTES or _sha(raw) != envelope["payload_sha256"]:
            raise C.TrendlinesError("full_history_transport_payload_binding_invalid")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise C.TrendlinesError("full_history_transport_duplicate_key")
                value[key] = item
            return value
        body = json.loads(envelope["payload_json"], object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (not isinstance(body, dict) or type(body.get("schema_version")) is not int or body["schema_version"] != 1
                or body.get("contract_id") not in {MANIFEST_CONTRACT, CHUNK_CONTRACT}
                or (expected_contract is not None and body["contract_id"] != expected_contract)
                or body.get("publication_scope") != "private_only" or body.get("asset_id") != envelope["asset_id"]
                or body.get("snapshot_id") != envelope["snapshot_id"]):
            raise C.TrendlinesError("full_history_transport_body_binding_invalid")
        if body["contract_id"] == CHUNK_CONTRACT:
            _unpack(body)
        return body
    except C.TrendlinesError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise C.TrendlinesError("full_history_transport_json_invalid") from exc


def _unpack(body):
    packed = body.get("bars_packed")
    if (not isinstance(packed, dict) or set(packed) != {"columns", "bar_id_prefix", "rows"}
            or packed["columns"] != list(BAR_COLUMNS) or packed["bar_id_prefix"] != R.PRIVATE_BAR_ID_PREFIX
            or not isinstance(packed["rows"], list) or not 1 <= len(packed["rows"]) <= CHUNK_SIZE
            or type(body.get("count")) is not int or body["count"] != len(packed["rows"])
            or type(body.get("chunk_index")) is not int or not 0 <= body["chunk_index"] < MAX_BARS // CHUNK_SIZE):
        raise C.TrendlinesError("full_history_chunk_contract_invalid")
    bars, ids, sessions = [], set(), set()
    previous = -1
    for values in packed["rows"]:
        if not isinstance(values, list) or len(values) != len(BAR_COLUMNS):
            raise C.TrendlinesError("full_history_chunk_row_shape_invalid")
        session, index, opened, high, low, close, suffix = values
        if (type(index) is not int or index <= previous or index < 0 or not isinstance(session, str)
                or date.fromisoformat(session).isoformat() != session or session in sessions
                or not isinstance(suffix, str) or not C.SHA256.fullmatch(suffix) or suffix in ids
                or any(not C._finite_number(price) or price <= 0 for price in (opened, high, low, close))
                or not low <= min(opened, close) <= max(opened, close) <= high):
            raise C.TrendlinesError("full_history_chunk_price_or_identity_invalid")
        bars.append(dict(zip(BAR_COLUMNS, values[:-1] + [R.PRIVATE_BAR_ID_PREFIX + suffix])))
        previous = index
        ids.add(suffix)
        sessions.add(session)
    if body.get("start_index") != bars[0]["session_index"] or body.get("end_index") != bars[-1]["session_index"]:
        raise C.TrendlinesError("full_history_chunk_endpoint_binding_invalid")
    return bars


def _exports(snapshot):
    sid, asset_id = snapshot["snapshot_id"], snapshot["asset_id"]
    bars = [{key: row[key] for key in BAR_COLUMNS} for row in snapshot["bars"]]
    chunks, pins = [], []
    for position in range(0, len(bars), CHUNK_SIZE):
        subset = bars[position:position + CHUNK_SIZE]
        if any(not bar["bar_id"].startswith(R.PRIVATE_BAR_ID_PREFIX)
               or not C.SHA256.fullmatch(bar["bar_id"][len(R.PRIVATE_BAR_ID_PREFIX):]) for bar in subset):
            raise C.TrendlinesError("full_history_bar_identity_invalid")
        body = {"schema_version": 1, "contract_id": CHUNK_CONTRACT, "publication_scope": "private_only",
                "asset_id": asset_id, "snapshot_id": sid, "source_snapshot_id": snapshot["source_snapshot_id"],
                "chunk_index": len(chunks), "count": len(subset), "start_index": subset[0]["session_index"],
                "end_index": subset[-1]["session_index"], "bars_packed": {"columns": list(BAR_COLUMNS),
                    "bar_id_prefix": R.PRIVATE_BAR_ID_PREFIX,
                    "rows": [[bar[key] for key in BAR_COLUMNS[:-1]] + [bar["bar_id"][len(R.PRIVATE_BAR_ID_PREFIX):]]
                             for bar in subset]}}
        envelope = _envelope(body)
        decode_envelope(envelope, CHUNK_CONTRACT)
        chunks.append(envelope)
        pins.append({"chunk_index": body["chunk_index"], "count": len(subset), "start_index": body["start_index"],
                     "end_index": body["end_index"], "payload_sha256": envelope["payload_sha256"],
                     "envelope_sha256": _sha(S.encode(envelope))})
    metadata = deepcopy(snapshot["display_metadata"])
    metadata.update({"schema_version": 1, "contract_id": MANIFEST_CONTRACT, "snapshot_id": sid,
                     "source_snapshot_id": snapshot["source_snapshot_id"],
                     "source_engine_snapshot_id": snapshot["source_engine_snapshot_id"],
                     "source_engine_content_hash": snapshot["source_engine_content_hash"],
                     "full_scope": SCOPE, "bar_count": len(bars), "chunk_size": CHUNK_SIZE,
                     "observation_start": bars[0]["session"], "observation_through": bars[-1]["session"],
                     "full_parameters": snapshot["full_config"]["parameters"],
                     "full_config_sha256": snapshot["full_config_sha256"], "points_encoding": "equations",
                     "bars_sha256": C.canonical_hash(bars), "chunks": pins, "analyses": deepcopy(snapshot["analyses"])})
    for windows in metadata["analyses"].values():
        analysis = windows["full"]
        analysis["pivot_count"] = len(analysis["pivots"])
        analysis["pivots"] = []
        for line in analysis["lines"]:
            line.pop("contacts", None)
    return _envelope(metadata), chunks


def _source(root, asset_id, now=None):
    if asset_id not in R.SYMBOLS:
        raise C.TrendlinesError("full_history_asset_has_no_research_source")
    pointer = (R._latest(root) or {}).get("assets", {}).get(asset_id)
    if not pointer:
        return None, None
    path = S.safe_path(root, pointer["snapshot_path"])
    archive = R._checked(path)
    if (archive["asset_id"] != asset_id or archive["snapshot_id"] != pointer["snapshot_id"]
            or _sha(path.read_bytes()) != pointer["snapshot_sha256"]):
        raise C.TrendlinesError("full_history_source_latest_binding_invalid")
    if S.aware_time(archive["capture_asof"]) > S.aware_time(now):
        raise C.TrendlinesError("full_history_source_after_read_cutoff")
    return archive, pointer


def _latest(root):
    path = _path(root, ROOT / "latest.json")
    if not path.is_file():
        return {"assets": {}}
    pointer = R._checked(path)
    if (pointer.get("contract_id") != "trendlines_private_full_latest_v1" or pointer.get("schema_version") != 1
            or not isinstance(pointer.get("assets"), dict) or set(pointer["assets"]) - set(R.SYMBOLS)):
        raise C.TrendlinesError("full_history_latest_contract_invalid")
    return pointer


def _read_snapshot(root, sid):
    if not isinstance(sid, str) or not SNAPSHOT_RE.fullmatch(sid):
        raise C.TrendlinesError("full_history_snapshot_id_invalid")
    path = _path(root, ROOT / "snapshots" / (sid + ".json"))
    snapshot = R._checked(path)
    identity = {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "content_hash"}}
    if (snapshot["snapshot_id"] != sid or sid != SNAPSHOT_PREFIX + C.canonical_hash(identity)
            or path.read_bytes() != S.encode(snapshot)
            or snapshot.get("contract_id") != "trendlines_private_full_snapshot_v1" or snapshot.get("schema_version") != 1
            or snapshot.get("publication_scope") != "private_only" or snapshot.get("official_forecast_write") is not False):
        raise C.TrendlinesError("full_history_snapshot_identity_invalid")
    source_path = S.safe_path(root, snapshot["source_snapshot_path"])
    source = R._checked(source_path)
    if (source["snapshot_id"] != snapshot["source_snapshot_id"] or source["asset_id"] != snapshot["asset_id"]
            or _sha(source_path.read_bytes()) != snapshot["source_archive_sha256"]
            or source["engine_snapshot"]["content_hash"] != snapshot["source_engine_content_hash"]
            or source["engine_snapshot"]["snapshot_id"] != snapshot["source_engine_snapshot_id"]):
        raise C.TrendlinesError("full_history_source_archive_binding_invalid")
    receipt = _source_evidence(root, source)
    if snapshot["display_metadata"] != _display_metadata(source, receipt, snapshot["source_snapshot_path"], snapshot["source_archive_sha256"]):
        raise C.TrendlinesError("full_history_display_source_binding_invalid")
    return snapshot, source


def _source_evidence(root, source):
    """Cheap immutable raw/receipt checks; the worker performs scalar replay."""
    asset = R.asset_definition(root, source["asset_id"])
    if (source["asset"] != asset or source["source_policy"] != R.research_source_policy(asset)
            or source.get("publication_scope") != "private_only"
            or source.get("verified_source") is not False or source.get("official_forecast_write") is not False
            or source["engine_snapshot"]["knowledge_cutoff"] != source["capture_asof"]):
        raise C.TrendlinesError("full_history_source_identity_invalid")
    receipt_path = S.safe_path(root, source["receipt_path"])
    receipt = R._checked(receipt_path)
    raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
    if (source["receipt_path"] != (R.ROOT / "receipts" / (source["receipt_id"] + ".json")).as_posix()
            or receipt["raw_path"] != (R.ROOT / "raw" / (source["raw_sha256"] + ".bin")).as_posix()
            or source["receipt_sha256"] != _sha(receipt_path.read_bytes())
            or receipt["receipt_id"] != source["receipt_id"] or receipt["raw_sha256"] != source["raw_sha256"]
            or _sha(raw) != source["raw_sha256"]
            or receipt != R._receipt(raw, {"url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                "sha256": receipt["raw_sha256"], "bytes": receipt["byte_count"], "http_status": receipt["http_status"]},
                asset, source["capture_asof"])):
        raise C.TrendlinesError("full_history_source_receipt_or_raw_binding_invalid")
    return receipt


def _evidence(root, snapshot, source, manifest, chunks):
    """What a successful snapshot check was bound to: each file's digest and the instrument."""
    export_root = ROOT / "exports" / snapshot["snapshot_id"]
    files = {snapshot["source_snapshot_path"]: snapshot["source_archive_sha256"],
             source["receipt_path"]: source["receipt_sha256"],
             (R.ROOT / "raw" / (source["raw_sha256"] + ".bin")).as_posix(): source["raw_sha256"],
             (export_root / "manifest.json").as_posix(): _sha(S.encode(manifest)),
             **{(export_root / f"bars-{i:04d}.json").as_posix(): _sha(S.encode(chunk)) for i, chunk in enumerate(chunks)}}
    return {"snapshot_id": snapshot["snapshot_id"], "asset_id": snapshot["asset_id"], "content_hash": snapshot["content_hash"],
            "source_archive_sha256": snapshot["source_archive_sha256"], "capture_asof": source["capture_asof"],
            "files": files, "assets": {source["asset_id"]: C.canonical_hash(R.asset_definition(root, source["asset_id"]))}}


def _display_metadata(archive, receipt, archive_path, archive_sha):
    """Frozen capture-time provenance, independent of a newer latest pointer."""
    detail = D.compact_snapshot(archive["engine_snapshot"])
    detail.update({"contract_id": "trendlines_research_display_v1", "status": "unverified_display",
                   "publication_class": "research_source", "verified_source": False, "source_context": R.CONTEXT,
                   "publication_scope": "private_only", "rights_status": R.RIGHTS, "numbers_visible": True,
                   "official_forecast_write": False, "engine_snapshot_id": detail["snapshot_id"],
                   "snapshot_id": archive["snapshot_id"], "source_url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                   "receipt_id": receipt["receipt_id"], "raw_sha256": receipt["raw_sha256"],
                   "research_archive_path": archive_path, "research_archive_sha256": archive_sha,
                   "gaps": archive["gaps"], "audit_evidence": "immutable_research_html_receipts_and_replayed_archives",
                   "row_validation_policy": archive["row_validation_policy"],
                   "rejected_rows": [gap for gap in archive["gaps"] if gap["reason"] == "source_invalid_ohlc_no_fill"],
                   "limitations": ["uncertified_public_source_not_an_approved_price_feed",
                                    "current_capture_vintage_not_historical_publication_receipts",
                                    "displayed_ohlc_without_split_adjustment_vintage_guarantee",
                                    "missing_and_unfinished_candles_are_never_filled"]})
    quote = archive["metadata"].get("quote") or {}
    if quote.get("observed_at") and C._finite_number(quote.get("price")) and quote["price"] > 0:
        stamp = S.aware_time(quote["observed_at"])
        local = stamp.astimezone(ZoneInfo(archive["asset"]["timezone"]))
        sessions = C.session_schedule(archive["asset"]["calendar_id"], archive["bars"][0]["session_date"], local.date().isoformat())
        positions = {day: i for i, (day, _open, _close) in enumerate(sessions)}
        last = archive["bars"][-1]
        if not (local.date().isoformat() == last["session_date"] and stamp >= S.aware_time(last["finalized_at"])
                and quote["price"] == last["close"]):
            detail["intraday_quote"] = {"date": local.date().isoformat(), "time": local.strftime("%H:%M:%S"),
                "observed_at": stamp.isoformat(), "price": quote["price"], "session_index": positions.get(local.date().isoformat()),
                "source_url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                "status": "intraday_snapshot_not_final_close", "currency": quote["currency"]}
    return {key: value for key, value in detail.items() if key not in
            {"content_hash", "bars", "analyses", "audit_lines", "input_bar_ids", "selection_changes"}}


@R._audited
def verify(root: Path, *, asset_id: str | None = None, replay: bool = True, now=None) -> dict[str, Any]:
    """Replay every supplemental snapshot and retain old pinned source vintages."""
    root = Path(root)
    resolved = str(root.resolve())
    errors, count = [], 0
    source_audit = R.verify(root, replay=replay)
    if not source_audit["ok"]:
        return {"ok": False, "errors": source_audit["errors"], "snapshots": 0, "replay": replay}
    pending, decoded = {}, {}
    cache = R._ACTIVE_REPLAY_CACHE.get() if replay is True else None
    functions = (_calculate, _normalize, _config, _scalar_verify, _scalar_price,
                 E._analyze, E._make_line, E._pivots, E._atr, E._value, E._epsilon,
                 E._formation, E._contiguous, E._rank, E._project, E._completed, E._select_rows,
                 C.validate_config, C.validate_research_source, C.validate_bar,
                 C.session_schedule, C.latest_completed_session)
    evidence_functions = functions + (verify, _read_snapshot, _source_evidence, _display_metadata, _exports, _evidence,
                                      R._checked, R._receipt, R._receipt_of, R.asset_definition, R.research_source_policy,
                                      D.compact_snapshot)
    try:
        pointer = _latest(root)
        snapshots = {}
        for path, data, digest in R._audit_reads(sorted(_path(root, ROOT / "snapshots").glob("*.json"))):
            evidence_key = ("full_history_evidence", resolved, path.name, digest,
                            tuple(id(f) for f in evidence_functions))
            bound = R._evidence_recall(root, evidence_key, evidence_functions) if cache is not None else None
            snapshot = source = None
            if bound is None:
                snapshot, source = _read_snapshot(root, path.stem)
                if S.encode(snapshot) != data:
                    raise C.TrendlinesError("full_history_snapshot_identity_invalid")
                manifest, chunks = _exports(snapshot)
                export_root = ROOT / "exports" / snapshot["snapshot_id"]
                if _path(root, export_root / "manifest.json").read_bytes() != S.encode(manifest):
                    raise C.TrendlinesError("full_history_manifest_binding_invalid")
                for i, chunk in enumerate(chunks):
                    if _path(root, export_root / f"bars-{i:04d}.json").read_bytes() != S.encode(chunk):
                        raise C.TrendlinesError("full_history_chunk_binding_invalid")
                bound = _evidence(root, snapshot, source, manifest, chunks)
                if cache is not None:
                    decoded[evidence_key] = (evidence_functions, bound)
            key = ("full_history", resolved, bound["content_hash"], digest,
                   bound["source_archive_sha256"], tuple(id(f) for f in functions))
            if replay and R._replay_includes(bound["asset_id"]) and (cache is None or not cache._contains(key, functions)):
                if source is None:
                    snapshot, source = _read_snapshot(root, path.stem)
                    if S.encode(snapshot) != data:
                        raise C.TrendlinesError("full_history_snapshot_identity_invalid")
                expected = _calculate(source)
                if any(snapshot.get(field) != value for field, value in expected.items()):
                    raise C.TrendlinesError("full_history_replay_differs_from_source_geometry")
                if cache is not None:
                    pending[key] = functions
            snapshots[bound["snapshot_id"]] = bound
            count += 1
        for aid, row in pointer["assets"].items():
            snapshot = snapshots[row["snapshot_id"]]
            expected_path = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
            manifest_path = ROOT / "exports" / snapshot["snapshot_id"] / "manifest.json"
            if (snapshot["asset_id"] != aid or row["snapshot_path"] != expected_path.as_posix()
                    or row["snapshot_sha256"] != R._audit_digest(_path(root, expected_path))[0]
                    or row["manifest_path"] != manifest_path.as_posix()
                    or row["manifest_sha256"] != R._audit_digest(_path(root, manifest_path))[0]):
                raise C.TrendlinesError("full_history_latest_snapshot_binding_invalid")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    if not errors and cache is not None:
        cache._remember(pending, decoded)
    return R._scope_report({"ok": not errors, "errors": errors, "snapshots": count, "replay": replay})


def refresh(root: Path, asset_id: str, now=None) -> dict[str, Any]:
    """Publish a separate immutable supplement, then move its private pointer."""
    R._check_replay_asset(asset_id)
    root = Path(root)
    with S.writer_lock(root):
        checked = verify(root, replay=True, now=now)
        if not checked["ok"]:
            raise C.TrendlinesError("full_history_existing_integrity_failed: " + "; ".join(checked["errors"]))
        archive, source_pointer = _source(root, asset_id, now)
        if archive is None:
            return {"changed": False, "asset_id": asset_id, "status": "hold", "reason_codes": ["missing_research_ohlc"]}
        source_before = _sha(S.safe_path(root, source_pointer["snapshot_path"]).read_bytes())
        pointer = _latest(root)
        prior = pointer["assets"].get(asset_id)
        if prior:
            previous, _ = _read_snapshot(root, prior["snapshot_id"])
            if previous["source_snapshot_id"] == archive["snapshot_id"] and previous["full_config"] == _config(archive, len(archive["bars"])):
                return {"changed": False, "asset_id": asset_id, "full_snapshot_id": previous["snapshot_id"],
                        "manifest_path": prior["manifest_path"], "shadow_current_unchanged": True}
        computation = _calculate(archive)
        receipt = _source_evidence(root, archive)
        metadata = _display_metadata(archive, receipt, source_pointer["snapshot_path"], source_pointer["snapshot_sha256"])
        body = {"schema_version": 1, "contract_id": "trendlines_private_full_snapshot_v1", "asset_id": asset_id,
                "publication_scope": "private_only", "official_forecast_write": False,
                "source_snapshot_id": archive["snapshot_id"], "source_snapshot_path": source_pointer["snapshot_path"],
                "source_archive_sha256": source_pointer["snapshot_sha256"],
                "source_engine_snapshot_id": archive["engine_snapshot"]["snapshot_id"],
                "source_engine_content_hash": archive["engine_snapshot"]["content_hash"],
                "display_metadata": metadata, **computation}
        body["snapshot_id"] = SNAPSHOT_PREFIX + C.canonical_hash(body)
        snapshot = _hash(body)
        manifest, chunks = _exports(snapshot)
        if source_before != _sha(S.safe_path(root, source_pointer["snapshot_path"]).read_bytes()):
            raise C.TrendlinesError("full_history_source_changed_during_shadow")
        snapshot_path = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
        exports = ROOT / "exports" / snapshot["snapshot_id"]
        manifest_path = exports / "manifest.json"
        # Immutable pieces first. A failure leaves the last good pointer intact.
        for i, chunk in enumerate(chunks):
            S.atomic_json(_path(root, exports / f"bars-{i:04d}.json"), chunk, immutable=True)
        S.atomic_json(_path(root, manifest_path), manifest, immutable=True)
        S.atomic_json(_path(root, snapshot_path), snapshot, immutable=True)
        assets = deepcopy(pointer["assets"])
        assets[asset_id] = {"snapshot_id": snapshot["snapshot_id"], "snapshot_path": snapshot_path.as_posix(),
                            "snapshot_sha256": _sha(S.encode(snapshot)), "manifest_path": manifest_path.as_posix(),
                            "manifest_sha256": _sha(S.encode(manifest))}
        S.atomic_json(_path(root, ROOT / "latest.json"), _hash({"schema_version": 1,
                      "contract_id": "trendlines_private_full_latest_v1", "assets": assets}))
        return {"changed": True, "asset_id": asset_id, "full_snapshot_id": snapshot["snapshot_id"],
                "source_snapshot_id": archive["snapshot_id"], "bar_count": len(computation["bars"]),
                "manifest_path": manifest_path.as_posix(),
                "chunks": [(exports / f"bars-{i:04d}.json").as_posix() for i in range(len(chunks))],
                "shadow_current_unchanged": True, "validation": computation["independent_validation"],
                "shadow": computation["shadow"]}


def load_manifest(root: Path, asset_id: str, now=None) -> dict[str, Any] | None:
    """Read a replayed immutable export; callers bind it to their current view."""
    root = Path(root)
    if asset_id not in R.SYMBOLS:
        raise C.TrendlinesError("full_history_asset_has_no_research_source")
    row = _latest(root)["assets"].get(asset_id)
    if row is None:
        return None
    snapshot, source = _read_snapshot(root, row["snapshot_id"])
    if S.aware_time(source["capture_asof"]) > S.aware_time(now):
        raise C.TrendlinesError("full_history_source_after_read_cutoff")
    path = S.safe_path(root, row["manifest_path"])
    envelope = S.read_json(path)
    body = decode_envelope(envelope, MANIFEST_CONTRACT)
    if (_sha(path.read_bytes()) != row["manifest_sha256"] or envelope != _exports(snapshot)[0]
            or body["asset_id"] != asset_id):
        raise C.TrendlinesError("full_history_manifest_binding_invalid")
    return envelope


def load_chunk(root: Path, asset_id: str, snapshot_id: str, chunk_index: int, now=None) -> dict[str, Any]:
    """A pinned old snapshot remains available across a newer source capture."""
    if type(chunk_index) is not int or not 0 <= chunk_index < MAX_BARS // CHUNK_SIZE:
        raise C.TrendlinesError("full_history_chunk_index_invalid")
    root = Path(root)
    snapshot, source = _read_snapshot(root, snapshot_id)
    if snapshot["asset_id"] != asset_id or S.aware_time(source["capture_asof"]) > S.aware_time(now):
        raise C.TrendlinesError("full_history_chunk_asset_or_cutoff_invalid")
    _manifest, expected = _exports(snapshot)
    if chunk_index >= len(expected):
        raise C.TrendlinesError("full_history_chunk_index_invalid")
    path = _path(root, ROOT / "exports" / snapshot_id / f"bars-{chunk_index:04d}.json")
    envelope = S.read_json(path)
    decode_envelope(envelope, CHUNK_CONTRACT)
    if path.read_bytes() != S.encode(expected[chunk_index]):
        raise C.TrendlinesError("full_history_chunk_binding_invalid")
    return envelope
