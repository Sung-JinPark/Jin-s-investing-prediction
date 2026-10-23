"""Strict, additive contracts for the descriptive trendline surface."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONTRACT_RELATIVE = Path("data/contracts/trendlines_v1.yaml")
ASSET_REGISTRY_RELATIVE = Path("data/trendlines/asset_registry.yaml")
SOURCE_POLICY_RELATIVE = Path("data/trendlines/source_policy.yaml")
ASSET_IDS = ("sk-hynix", "soxx", "nasdaq", "sp500", "bitcoin", "dow", "kospi", "samsung", "nvidia", "micron", "mag7")
ENGINE_VERSION = "trendlines-v1.0"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESEARCH_SOURCE_ID = "yahoo_public_history_html"
RESEARCH_SOURCE_CONTEXT = "user_authorized_public_html_research"
RESEARCH_PRICE_BASIS = "provider_reported_ohlc_current_vintage"
RESEARCH_IDENTITIES = {
    "sk-hynix": ("000660.KS", "KRX:000660", "KRW", "KRW_per_share", "XKRX", "Asia/Seoul", "equity", "exchange_close"),
    "soxx": ("SOXX", "NASDAQ:SOXX", "USD", "USD_per_share", "XNAS", "America/New_York", "etf", "exchange_close"),
    "nasdaq": ("^IXIC", "NASDAQ_COMPOSITE_PRICE_INDEX", "USD", "index_points", "XNAS", "America/New_York", "index", "exchange_close"),
    "sp500": ("^GSPC", "SP500_PRICE_INDEX", "USD", "index_points", "XNYS", "America/New_York", "index", "exchange_close"),
    "bitcoin": ("BTC-USD", "BTC_USD_SPOT_SOURCE_MUST_BE_DECLARED", "USD", "USD_per_BTC", "24/7", "UTC", "crypto", "UTC_00_00_next_day"),
    "dow": ("^DJI", "DOW_JONES_INDUSTRIAL_AVERAGE_PRICE_INDEX", "USD", "index_points", "XNYS", "America/New_York", "index", "exchange_close"),
    "kospi": ("^KS11", "KRX_KOSPI_PRICE_INDEX", "KRW", "index_points", "XKRX", "Asia/Seoul", "index", "exchange_close"),
    "samsung": ("005930.KS", "KRX:005930", "KRW", "KRW_per_share", "XKRX", "Asia/Seoul", "equity", "exchange_close"),
    "nvidia": ("NVDA", "NASDAQ:NVDA", "USD", "USD_per_share", "XNAS", "America/New_York", "equity", "exchange_close"),
    "micron": ("MU", "NASDAQ:MU", "USD", "USD_per_share", "XNAS", "America/New_York", "equity", "exchange_close"),
}


class TrendlinesError(ValueError):
    """A rejected source, bar, or derived artifact with an auditable reason."""


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def aware_time(value: str | datetime) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise TrendlinesError("invalid aware timestamp") from exc
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise TrendlinesError("timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


@lru_cache(maxsize=32)
def _parse_yaml(text: str) -> Any:
    return yaml.safe_load(text)


def _yaml(root: Path, relative: Path) -> dict[str, Any]:
    # The file is reread on every call; only the parse of identical text is
    # shared, and callers receive their own copy.
    try:
        value = deepcopy(_parse_yaml((root / relative).read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError) as exc:
        raise TrendlinesError(f"cannot read {relative.as_posix()}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise TrendlinesError(f"invalid contract {relative.as_posix()}")
    return value


def load_contract(root: Path) -> dict[str, Any]:
    value = _yaml(root, CONTRACT_RELATIVE)
    validate_config(value)
    return value


def load_asset_registry(root: Path) -> dict[str, dict[str, Any]]:
    value = _yaml(root, ASSET_REGISTRY_RELATIVE)
    assets = value.get("assets")
    if not isinstance(assets, dict) or tuple(assets) != ASSET_IDS:
        raise TrendlinesError("registry must declare the exact instruments in canonical order")
    for asset_id, asset in assets.items():
        if not isinstance(asset, dict) or asset.get("asset_id") != asset_id:
            raise TrendlinesError("asset registry identity mismatch")
        for field in ("name", "identity", "currency", "unit", "price_basis", "calendar_id", "timezone", "kind", "source_day_cutoff"):
            if not isinstance(asset.get(field), str) or not asset[field]:
                raise TrendlinesError(f"asset missing {field}")
        if not isinstance(asset.get("enabled"), bool):
            raise TrendlinesError("asset enabled must be an explicit boolean")
        if asset["enabled"] and not asset.get("source_id"):
            raise TrendlinesError("enabled asset requires an explicit source")
    return assets


def load_source_policy(root: Path) -> dict[str, Any]:
    value = _yaml(root, SOURCE_POLICY_RELATIVE)
    if value.get("default_action") != "deny" or not isinstance(value.get("sources"), dict):
        raise TrendlinesError("source policy must default deny")
    return value


def default_config() -> dict[str, Any]:
    """Pure-function defaults; the pipeline also validates the checked-in YAML."""
    return {
        "schema_version": 1, "contract_id": "trendlines_display_v1", "engine_version": ENGINE_VERSION,
        "publication_class": "research_reference_proxy", "probability_space": "reference_only",
        "official_forecast_write": False, "price_input": "atomic_approved_ohlc_only", "close_fallback": "forbidden",
        "axes": ["linear", "log"], "default_axis": "linear", "default_window": 63,
        "windows": {"63": {"bars": 63, "left": 3, "right": 3, "min_anchor_gap": 10, "minimum_bars": 78},
                    "252": {"bars": 252, "left": 5, "right": 5, "min_anchor_gap": 20, "minimum_bars": 267},
                    "756": {"bars": 756, "left": 10, "right": 10, "min_anchor_gap": 60, "minimum_bars": 771}},
        "atr": {"period": 14, "averaging": "simple_mean_true_range"},
        "touch": {"atr_multiple": 0.25, "price_fraction": 0.001, "minimum_confirmed_pivots": 3},
        "break": {"atr_multiple": 0.5, "price_fraction": 0.0025, "consecutive_closes": 2},
        "reclaim": {"consecutive_closes": 2}, "max_selected_per_side": 3, "max_recent_broken_per_side": 1,
        "projections": {"exchange": [1, 5, 21], "crypto": [1, 7, 30]}, "settlement_buffer_minutes": 15,
        "comparison_tolerance": {"absolute": 1e-6, "relative": 1e-10},
    }


def validate_config(config: dict[str, Any]) -> None:
    if config.get("contract_id") != "trendlines_display_v1" or config.get("engine_version") != ENGINE_VERSION:
        raise TrendlinesError("unsupported trendlines contract or engine version")
    if config.get("official_forecast_write") is not False or config.get("close_fallback") != "forbidden":
        raise TrendlinesError("official forecast writes and close fallback are forbidden")
    if config.get("probability_space") != "reference_only" or config.get("axes") != ["linear", "log"]:
        raise TrendlinesError("invalid reference-only axis contract")
    if config.get("atr", {}).get("averaging") != "simple_mean_true_range":
        raise TrendlinesError("ATR must be explicitly simple-mean true range")
    period = config.get("atr", {}).get("period")
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise TrendlinesError("invalid ATR period")
    windows = config.get("windows")
    if not isinstance(windows, dict) or not windows:
        raise TrendlinesError("missing windows")
    for key, spec in windows.items():
        if not isinstance(spec, dict) or str(spec.get("bars")) != str(key):
            raise TrendlinesError("window key mismatch")
        for field in ("bars", "left", "right", "min_anchor_gap", "minimum_bars"):
            if isinstance(spec.get(field), bool) or not isinstance(spec.get(field), int) or spec[field] < 1:
                raise TrendlinesError(f"invalid window {field}")
        if spec["minimum_bars"] < spec["bars"] + max(period, spec["left"]) + 1:
            raise TrendlinesError("insufficient declared ATR/pivot warmup")
    for block in ("touch", "break"):
        for field in ("atr_multiple", "price_fraction"):
            if not _finite_number(config.get(block, {}).get(field)) or config[block][field] <= 0:
                raise TrendlinesError(f"invalid {block} {field}")
    if config["touch"].get("minimum_confirmed_pivots") != 3:
        raise TrendlinesError("three confirmed pivots required for confirmed geometry")
    if config["break"].get("consecutive_closes") != 2 or config.get("reclaim", {}).get("consecutive_closes") != 2:
        raise TrendlinesError("two completed closes required for break and reclaim")
    if config.get("projections") != {"exchange": [1, 5, 21], "crypto": [1, 7, 30]}:
        raise TrendlinesError("unsupported extension horizons")
    for key in ("max_selected_per_side", "max_recent_broken_per_side", "settlement_buffer_minutes"):
        if isinstance(config.get(key), bool) or not isinstance(config.get(key), int) or config[key] < 1:
            raise TrendlinesError(f"invalid {key}")


def validate_source(asset: dict[str, Any], source_policy: dict[str, Any] | None) -> dict[str, Any]:
    source = (source_policy or {}).get("sources", {}).get(asset.get("source_id"))
    if not isinstance(source, dict) or source.get("rights_status") != "approved_free":
        raise TrendlinesError("source_not_approved_free")
    for field in ("allow_collection", "allow_derived_display", "allow_ohlc"):
        if source.get(field) is not True:
            raise TrendlinesError(f"source_permission_denied:{field}")
    for field, value in (("asset_ids", asset["asset_id"]), ("allowed_price_bases", asset["price_basis"]),
                         ("calendar_ids", asset["calendar_id"])):
        if value not in source.get(field, []):
            raise TrendlinesError(f"source_identity_mismatch:{field}")
    if not source.get("allowed_domains") or source.get("parser_id") != "json_ohlc_v1":
        raise TrendlinesError("missing approved domain/parser")
    publication_lag(asset, source)
    if asset["price_basis"] == "split_adjusted_price":
        if source.get("adjustment_method") != "split_only" or source.get("adjustment_vintage_guarantee") is not True:
            raise TrendlinesError("unverified split-only adjustment or event vintage")
    elif source.get("adjustment_method") not in {"none", "published_index"}:
        raise TrendlinesError("unverified published price adjustment basis")
    return source


def publication_lag(asset: dict[str, Any], source: dict[str, Any] | None = None) -> int:
    value = (source or {}).get("publication_lag_minutes", asset.get("publication_lag_minutes", 0))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrendlinesError("publication_lag_minutes must be an explicit nonnegative integer")
    return value


def validate_research_source(asset: dict[str, Any], source_policy: dict[str, Any] | None) -> dict[str, Any]:
    """Explicit uncertified public-HTML scope; this never grants source approval.

    Collection/raw metadata binding remains at the receipt/parser boundary.
    These identities prevent a different instrument, ETF or synthetic basket
    from being labelled as one of the user's requested research instruments.
    """
    identity = RESEARCH_IDENTITIES.get(asset.get("asset_id"))
    if identity is None:
        raise TrendlinesError("research instrument has no exact public HTML source")
    fields = ("provider_symbol", "identity", "currency", "unit", "calendar_id", "timezone", "kind", "source_day_cutoff")
    if any(asset.get(field) != expected for field, expected in zip(fields, identity)):
        raise TrendlinesError("research instrument identity mismatch")
    if asset.get("source_id") != RESEARCH_SOURCE_ID or asset.get("price_basis") != RESEARCH_PRICE_BASIS:
        raise TrendlinesError("research source or current-vintage price basis mismatch")
    source = (source_policy or {}).get("sources", {}).get(RESEARCH_SOURCE_ID)
    if not isinstance(source, dict):
        raise TrendlinesError("missing explicit research source context")
    if (source.get("rights_status") != "uncertified_research_source"
            or source.get("source_context") != RESEARCH_SOURCE_CONTEXT
            or source.get("verified_source") is not False or source.get("adjustment_verified") is not False):
        raise TrendlinesError("research source cannot claim approval or verified adjustment")
    for field, value in (("asset_ids", asset["asset_id"]), ("allowed_price_bases", RESEARCH_PRICE_BASIS),
                         ("calendar_ids", asset["calendar_id"]), ("allowed_symbols", asset["provider_symbol"])):
        if value not in source.get(field, []):
            raise TrendlinesError(f"research source identity mismatch:{field}")
    if source.get("allowed_domains") != ["finance.yahoo.com"] or source.get("parser_id") != "yahoo_history_html_v1":
        raise TrendlinesError("research source domain/parser mismatch")
    publication_lag(asset, source)
    return source


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


@lru_cache(maxsize=24)
def session_schedule(calendar_id: str, start: str, end: str) -> tuple[tuple[str, datetime, datetime], ...]:
    try:
        import exchange_calendars as xcals
        calendar = xcals.get_calendar(calendar_id)
        if start < str(calendar.first_session.date()) or end > str(calendar.last_session.date()):
            calendar = xcals.get_calendar(calendar_id, start=(date.fromisoformat(start) - timedelta(days=7)).isoformat(),
                                          end=(date.fromisoformat(end) + timedelta(days=7)).isoformat())
        schedule = calendar.schedule.loc[start:end]
    except (ImportError, KeyError, ValueError, TypeError) as exc:
        raise TrendlinesError(f"calendar unavailable: {calendar_id}") from exc
    return tuple((str(day.date()), row["open"].to_pydatetime(), row["close"].to_pydatetime())
                 for day, row in schedule.iterrows())


@lru_cache(maxsize=16)
def _default_session_index(calendar_id: str):
    try:
        import exchange_calendars as xcals
        calendar = xcals.get_calendar(calendar_id)
        first, last = str(calendar.first_session.date()), str(calendar.last_session.date())
    except (ImportError, KeyError, ValueError, TypeError) as exc:
        raise TrendlinesError(f"calendar unavailable: {calendar_id}") from exc
    return calendar, first, last, {row[0]: row for row in session_schedule(calendar_id, first, last)}


def _session_on(calendar_id: str, day: str) -> tuple[tuple[str, datetime, datetime], ...]:
    """Exactly ``session_schedule(calendar_id, day, day)``, indexed per calendar.

    A per-bar range query misses the small range cache on every distinct day.
    Days inside the same default calendar are read from its one schedule; any
    other day or calendar instance takes the original query.
    """
    calendar, first, last, sessions = _default_session_index(calendar_id)
    try:
        import exchange_calendars as xcals
        current = xcals.get_calendar(calendar_id)
    except (ImportError, KeyError, ValueError, TypeError) as exc:
        raise TrendlinesError(f"calendar unavailable: {calendar_id}") from exc
    if current is not calendar or not first <= day <= last:
        return session_schedule(calendar_id, day, day)
    row = sessions.get(day)
    return () if row is None else (row,)


def latest_completed_session(asset: dict[str, Any], as_of: str | datetime, *, buffer_minutes: int = 15,
                             source_policy: dict[str, Any] | None = None) -> str | None:
    current = aware_time(as_of)
    start = (current.date() - timedelta(days=21)).isoformat()
    end = (current.date() + timedelta(days=1)).isoformat()
    source = validate_source(asset, source_policy) if source_policy is not None and asset.get("enabled") else None
    lag = publication_lag(asset, source)
    eligible = [day for day, _opened, closed in session_schedule(asset["calendar_id"], start, end)
                if closed + timedelta(minutes=buffer_minutes + lag) <= current]
    return eligible[-1] if eligible else None


completed_session = latest_completed_session


def validate_bar(bar: dict[str, Any], asset: dict[str, Any], as_of: str | datetime | None = None,
                 source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(bar, dict):
        raise TrendlinesError("bar must be an object")
    source = validate_source(asset, source_policy) if source_policy is not None else None
    for field in ("bar_id", "asset_id", "source_id", "session_date", "currency", "unit", "price_basis", "calendar_id",
                  "available_at", "fetched_at", "finalized_at", "raw_sha256", "receipt_id"):
        if not isinstance(bar.get(field), str) or not bar[field]:
            raise TrendlinesError(f"bar missing {field}")
    for field in ("asset_id", "source_id", "currency", "unit", "price_basis", "calendar_id"):
        if bar[field] != asset.get(field):
            raise TrendlinesError(f"bar identity mismatch:{field}")
    if not SHA256.fullmatch(bar["raw_sha256"]):
        raise TrendlinesError("invalid raw SHA256")
    try:
        day = date.fromisoformat(bar["session_date"])
    except ValueError as exc:
        raise TrendlinesError("invalid session date") from exc
    if day.isoformat() != bar["session_date"]:
        raise TrendlinesError("noncanonical session date")
    prices = [bar.get(field) for field in ("open", "high", "low", "close")]
    if not all(_finite_number(value) and value > 0 for value in prices):
        raise TrendlinesError("OHLC must be finite positive numbers; close fallback forbidden")
    if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
        raise TrendlinesError("OHLC containment violation")
    if "volume" in bar and bar["volume"] is not None and (not _finite_number(bar["volume"]) or bar["volume"] < 0):
        raise TrendlinesError("invalid volume")
    revision = bar.get("revision_seq")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise TrendlinesError("invalid bar revision_seq")
    prior = bar.get("supersedes_bar_id")
    if "supersedes_bar_id" not in bar or (revision == 1 and prior is not None) or (
        revision > 1 and (not isinstance(prior, str) or not prior)):
        raise TrendlinesError("invalid supersedes_bar_id")
    available, fetched, finalized = (aware_time(bar[field]) for field in ("available_at", "fetched_at", "finalized_at"))
    schedule = _session_on(asset["calendar_id"], day.isoformat())
    if len(schedule) != 1 or schedule[0][0] != day.isoformat():
        raise TrendlinesError("nontrading session bar")
    if (finalized < schedule[0][2] or available < finalized or fetched < available
            or available < schedule[0][2] + timedelta(minutes=publication_lag(asset, source))):
        raise TrendlinesError("bar temporal ordering violation")
    if as_of is not None and (available > aware_time(as_of) or fetched > aware_time(as_of) or finalized > aware_time(as_of)):
        raise TrendlinesError("future bar is ineligible at cutoff")
    return bar
