"""Daily display forecast for the frozen V8 model (display-only, never scored).

사용자 결정 2026-10-07: 시계열 예측 화면은 매일 갱신한다. 채점·성적(검증 성적 탭,
라이브 전진 타일, score100)은 그대로 **주간** 섀도 원장이 맡는다.

Why this module lives outside ``src/ai_fc/timeseries_v8/``
----------------------------------------------------------
Every file in that package (and ``timeseries_v2/features.py``) is part of the
recorded ``model_code_hash`` of the weekly shadow ledger, and the V2 sealed run
re-checks its own code hash.  Touching them — even for a pure refactor — would
change the recorded identity of every future weekly row.  So the hashed set is
left byte-identical and this module *calls* the same frozen functions:

* bundle assembly: ``pipeline._sealed_bundle`` (unchanged), with provisional
  observations overlaid in memory on the archive reader it uses;
* inference: ``walk_forward_dev_backtest_v8(..., emit_forecast=True)`` with the
  exact argument set the weekly ``shadow_forecast_timeseries_v8`` passes
  (``frozen_inference`` — a test pins the two call sites to identical kwargs and
  the real 2026-10-02 weekly row was recomputed bit-for-bit through this path).

Provisional inputs
------------------
FRED/H.15 post the US session's VIX·DGS2·DGS10 only the next US afternoon, but
the original publishers have them the same evening.  Missing required sessions
are filled **in memory only** from those publishers, each tagged
``{source, provisional: true}``; nothing is written to the market archive.  The
weekly-published dollar index is carried as-of from the archive until the next
H.10 publication deadline (tagged ``carried_forward``, not provisional). When the
archive later confirms the session, a ``confirmed`` row for the same origin is
appended with an explicit ``supersedes`` link.  If a required series is still
unavailable, the origin is the latest session where every required series
exists — nothing is fabricated.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from .timeseries_v8.contracts import (
    MODEL_ID,
    MODEL_VERSION,
    canonical_hash,
    frozen_hash,
    load_contract_v8,
    model_code_hash,
    verify_v2_benchmark,
)

DAILY_LEDGER_RELATIVE = Path("data/timeseries_v8/ledgers/daily_display_forecasts.jsonl")
DAILY_LATEST_RELATIVE = Path("data/timeseries_v8/daily_display_latest.json")
USER_AGENT = "JinsInvestingTimeseries/1.0 (+public research dashboard)"
PROBABILITY_SPACE = "research_timeseries_v8_conditional"
QUANTILE_LEVELS = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90}
FILL_SERIES = ("NASDAQCOM", "VIX", "DGS2", "DGS10")
CARRY_SERIES = "DTWEXBGS"
FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
VIX_LATEST_RELATIVE = Path("data/vix/vix_latest.json")
NASDAQ_LATEST_RELATIVE = Path("data/market_quotes/nasdaq_latest.json")
NASDAQ_HISTORY_RELATIVE = Path("data/market_quotes/nasdaq_closes.jsonl")

Fetcher = Callable[[str], bytes]


class TimeSeriesV8DailyError(RuntimeError):
    """The daily display forecast failed closed."""


def _http_get(url: str, *, timeout: int = 45) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if int(response.status) != 200:
            raise OSError(f"HTTP {response.status} for {url}")
        return response.read()


# ── provisional publisher fills ─────────────────────────────────────────────

def _fill(series_id: str, day: str, value: float, *, source: str, source_url: str,
          retrieved_at: str) -> dict[str, Any]:
    return {
        "series_id": series_id, "observation_time": day, "value": float(value),
        "source": source, "source_url": source_url, "retrieved_at": retrieved_at,
        "provisional": True,
    }


def _contiguous(sessions: list[str], found: dict[str, float]) -> list[tuple[str, float]]:
    """Fills must be gap-free from the archive's last session; stop at the first hole.

    A later session filled across a hole would turn a two-session move into a
    one-session change — the frozen transforms difference consecutive rows.
    """
    out: list[tuple[str, float]] = []
    for day in sessions:
        if day not in found:
            break
        out.append((day, found[day]))
    return out


def treasury_fills(sessions: list[str], *, fetcher: Fetcher, retrieved_at: str) -> list[dict[str, Any]]:
    """DGS2/DGS10 from the US Treasury daily par yield curve (the H.15 source).

    Same endpoint and parser as the archive's own Treasury collector, so a later
    archive confirmation carries the identical value.
    """
    from .timeseries_v2.market_archive import parse_treasury_xml

    if not sessions:
        return []
    rows: dict[str, tuple[float, float]] = {}
    for year in sorted({int(day[:4]) for day in sessions}):
        url = TREASURY_XML_URL.format(year=year)
        for day, two, ten in parse_treasury_xml(fetcher(url)):
            rows[day] = (two, ten)
    url = TREASURY_XML_URL.format(year=int(sessions[-1][:4]))
    out: list[dict[str, Any]] = []
    for index, series_id in ((0, "DGS2"), (1, "DGS10")):
        found = {day: values[index] for day, values in rows.items()}
        out.extend(
            _fill(series_id, day, value, source="us_treasury_daily_par_yield_curve",
                  source_url=url, retrieved_at=retrieved_at)
            for day, value in _contiguous(sessions, found)
        )
    return out


def vix_fills(
    root: Path, sessions: list[str], *, retrieved_at: str, now: datetime,
    quote_fetcher: Callable[[], dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """VIX closes from the morning job's Cboe projection, then the Cboe delayed quote."""
    from .vix_surface import QUOTE_URL, quote_close

    if not sessions:
        return []
    found: dict[str, float] = {}
    sources: dict[str, tuple[str, str]] = {}
    path = root / VIX_LATEST_RELATIVE
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        latest_from_quote = payload.get("latest_source") == "cboe_delayed_quote"
        for point in payload.get("trail") or []:
            day, value = str(point.get("d") or ""), point.get("v")
            if day in sessions and isinstance(value, (int, float)) and value > 0:
                found[day] = float(value)
                quote_row = latest_from_quote and day == payload.get("observed_date")
                sources[day] = (
                    ("cboe_delayed_quote", str(payload.get("latest_source_url") or QUOTE_URL))
                    if quote_row else
                    ("cboe_vix_history", str(payload.get("source_url") or ""))
                )
    if sessions[-1] not in found and quote_fetcher is not None:
        try:
            closed = quote_close(quote_fetcher(), now=now)
        except Exception:  # noqa: BLE001 — 지연 시세가 없으면 채우지 않는다
            closed = None
        if closed is not None and closed[0].isoformat() in sessions:
            day = closed[0].isoformat()
            found[day] = float(closed[1])
            sources[day] = ("cboe_delayed_quote", QUOTE_URL)
    return [
        _fill("VIX", day, value, source=sources[day][0], source_url=sources[day][1],
              retrieved_at=retrieved_at)
        for day, value in _contiguous(sessions, found)
    ]


def nasdaq_fills(
    root: Path, sessions: list[str], *, fetcher: Fetcher | None, retrieved_at: str,
) -> list[dict[str, Any]]:
    """NASDAQCOM from FRED (the archive's own source) first, then the Nasdaq quote files.

    FRED is preferred because the archive confirms from it: the Nasdaq quote API's
    evening close can differ from the final official print (2026-10-06: quote
    27599.79 vs FRED 27599.89).
    """
    from .timeseries_v2.market_archive import parse_fred_graph_csv

    if not sessions:
        return []
    found: dict[str, float] = {}
    sources: dict[str, tuple[str, str]] = {}
    if fetcher is not None:
        url = FRED_GRAPH_URL.format(series="NASDAQCOM", start=sessions[0])
        try:
            for day, value in parse_fred_graph_csv(fetcher(url), series_id="NASDAQCOM"):
                if day in sessions:
                    found[day] = float(value)
                    sources[day] = ("fred_nasdaqcom", url)
        except (OSError, ValueError):
            pass
    quote_rows: list[dict[str, Any]] = []
    history = root / NASDAQ_HISTORY_RELATIVE
    if history.is_file():
        for line in history.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    quote_rows.append(json.loads(line))
                except ValueError:
                    continue
    latest = root / NASDAQ_LATEST_RELATIVE
    if latest.is_file():
        try:
            quote_rows.append(json.loads(latest.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    for row in quote_rows:
        day = str(row.get("session_date") or "")
        close = row.get("close")
        # 장중 값은 종가가 아니다 — market_quotes 가 이미 거부하지만 여기서도 거른다.
        if (day in sessions and day not in found and isinstance(close, (int, float))
                and close > 0 and str(row.get("market_status") or "") != "Open"):
            found[day] = float(close)
            sources[day] = ("nasdaq_quote_api_comp", str(row.get("source_url") or ""))
    return [
        _fill("NASDAQCOM", day, value, source=sources[day][0], source_url=sources[day][1],
              retrieved_at=retrieved_at)
        for day, value in _contiguous(sessions, found)
    ]


# ── input state ─────────────────────────────────────────────────────────────

def _sessions_between(after: str, through: date, *, root: Path) -> list[str]:
    from .market_session import is_trading_day

    cursor = date.fromisoformat(after) + timedelta(days=1)
    out: list[str] = []
    while cursor <= through:
        if is_trading_day(cursor, root=root):
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def _archive_last(rows: list[Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for row in rows:
        if row.series_id not in latest or row.observation_time > latest[row.series_id].observation_time:
            latest[row.series_id] = row
    return latest


def collect_inputs(
    root: Path, *, contract: dict[str, Any], now: datetime,
    fetcher: Fetcher | None = _http_get,
    quote_fetcher: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Archive state plus in-memory provisional fills up to the expected session."""
    from .market_session import expected_latest_session
    from .timeseries_v2.market_archive import read_market_observations

    if quote_fetcher is None and fetcher is not None:
        from .vix_surface import fetch_quote

        quote_fetcher = fetch_quote
    cutoff = now.isoformat(timespec="seconds")
    expected = expected_latest_session(now, root=root)
    archive = read_market_observations(root, knowledge_cutoff=cutoff)
    last = _archive_last(archive)
    retrieved = cutoff
    fills: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    pending = {
        series: _sessions_between(last[series].observation_time, expected, root=root)
        if series in last else []
        for series in FILL_SERIES
    }
    try:
        if fetcher is None:
            raise OSError("network disabled")
        fills.extend(treasury_fills(
            sorted(set(pending["DGS2"]) | set(pending["DGS10"])),
            fetcher=fetcher, retrieved_at=retrieved,
        ))
    except (OSError, ValueError) as exc:
        if pending["DGS2"] or pending["DGS10"]:
            failures.append({"series": "DGS2/DGS10", "reason": type(exc).__name__})
    # DGS2/DGS10 share one request; keep only each series' own missing sessions.
    fills = [row for row in fills if row["observation_time"] in pending[row["series_id"]]]
    fills.extend(vix_fills(
        root, pending["VIX"], retrieved_at=retrieved, now=now, quote_fetcher=quote_fetcher,
    ))
    fills.extend(nasdaq_fills(root, pending["NASDAQCOM"], fetcher=fetcher, retrieved_at=retrieved))
    carried: list[dict[str, Any]] = []
    if CARRY_SERIES in last:
        source_row = last[CARRY_SERIES]
        from .forecast_source_freshness import source_freshness
        if source_freshness(CARRY_SERIES, source_row.observation_time, now)["status"] == "fresh":
            carried.extend(
                {
                    "series_id": CARRY_SERIES, "observation_time": day,
                    "value": float(source_row.value), "carried_from": source_row.observation_time,
                    "source": "market_archive_as_of", "carried_forward": True,
                    "provisional": False,
                }
                for day in _sessions_between(source_row.observation_time, expected, root=root)
            )
    return {
        "expected_session": expected.isoformat(),
        "knowledge_cutoff": cutoff,
        "archive_last": {series: row.observation_time for series, row in sorted(last.items())},
        "fills": fills,
        "carried": carried,
        "failures": failures,
    }


def _overlay_rows(inputs: dict[str, Any]) -> list[Any]:
    """In-memory MarketObservationV2 rows for the fills — never appended to the archive."""
    from .timeseries_v2.market_archive import MarketObservationV2

    out = []
    for row in [*inputs["fills"], *inputs["carried"]]:
        seed = {key: row[key] for key in sorted(row) if key != "retrieved_at"}
        digest = canonical_hash(seed)
        out.append(MarketObservationV2(
            observation_id=f"display-overlay-{digest[:24]}",
            source_id=f"display_overlay_{row['source']}",
            series_id=row["series_id"],
            observation_time=row["observation_time"],
            value=float(row["value"]),
            unit="index" if row["series_id"] in ("NASDAQCOM", "VIX", CARRY_SERIES) else "percentage_point",
            available_at=inputs["knowledge_cutoff"],
            data_grade="captured_forward",
            vintage_start=inputs["knowledge_cutoff"],
            raw_sha256=hashlib.sha256(json.dumps(seed, sort_keys=True).encode("utf-8")).hexdigest(),
            receipt_id=f"display-overlay-{digest[24:48]}",
            revision_seq=1,
            parser_version="display-overlay-v1",
        ))
    return out


@contextlib.contextmanager
def market_overlay(rows: list[Any]) -> Iterator[None]:
    """Expose ``rows`` to the frozen bundle assembly without touching the archive.

    ``timeseries_v2.features`` resolves ``read_market_observations`` at call time;
    the frozen file stays byte-identical (it is inside both model code hashes).
    Archive rows for the same (series, session) win over overlay rows.
    """
    from .timeseries_v2 import features

    original = features.read_market_observations

    def overlaid(root: Path, *, knowledge_cutoff: str | None = None) -> list[Any]:
        base = list(original(root, knowledge_cutoff=knowledge_cutoff))
        present = {(row.series_id, row.observation_time) for row in base}
        extra = [row for row in rows if (row.series_id, row.observation_time) not in present]
        if knowledge_cutoff is not None:
            limit = datetime.fromisoformat(knowledge_cutoff)
            extra = [row for row in extra if datetime.fromisoformat(row.available_at) <= limit]
        return sorted(base + extra, key=lambda row: (row.series_id, row.observation_time))

    features.read_market_observations = overlaid
    try:
        yield
    finally:
        features.read_market_observations = original


# ── frozen inference (shared argument set with the weekly shadow forecast) ──

def frozen_config(contract: dict[str, Any]) -> Any:
    from .timeseries_v8.pipeline import build_config_from_grids

    return build_config_from_grids(
        contract, json.loads(json.dumps(contract["frozen_winner"]["config_overrides"])),
    )


def frozen_inference(contract: dict[str, Any], config: Any, bundle: Any) -> tuple[list[Any], dict[str, Any]]:
    """The weekly shadow forecast's walk-forward call, argument for argument.

    Mirrors ``shadow_forecast_timeseries_v8`` (timeseries_v8/pipeline.py), which
    cannot be refactored without changing the weekly ledger's model_code_hash.
    ``test_daily_inference_passes_the_weekly_argument_set`` pins the two calls.
    """
    from .timeseries_v8 import pipeline

    return pipeline.walk_forward_dev_backtest_v8(
        dates=bundle.dates,
        endog=bundle.endogenous,
        exog=bundle.exogenous,
        endog_names=bundle.endogenous_names,
        exog_names=bundle.exogenous_names,
        model_id=contract["model_id"],
        model_version=int(contract["model_version"]),
        config=config,
        outer_start=str(contract["evaluation"]["outer_start"]),
        outer_end=bundle.dates[-1],
        path_count=int(contract["model"]["distribution"]["sealed_path_count"]),
        pit_min_matured=int(
            contract["research_grids"]["B4_pit_recalibration"]["minimum_matured_origins"]
        ),
        collect_cramer_audit=False,
        emit_forecast=True,
    )


# ── ledger ──────────────────────────────────────────────────────────────────

def read_daily_rows(root: Path) -> list[dict[str, Any]]:
    from .timeseries_v8.pipeline import _read_chain

    return _read_chain(root, DAILY_LEDGER_RELATIVE)


def effective_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows not superseded by a later row (the read model; the ledger is untouched)."""
    superseded = {row.get("supersedes") for row in rows if row.get("supersedes")}
    return [row for row in rows if row["display_id"] not in superseded]


def latest_effective(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    live = effective_rows(rows)
    if not live:
        return None
    return max(live, key=lambda row: (row["origin"], rows.index(row)))


def _compact_horizons(forecast: dict[str, Any]) -> dict[str, Any]:
    count = int(forecast["grid_levels_count"])
    out: dict[str, Any] = {}
    for horizon, values in forecast["horizons"].items():
        grid = [float(value) for value in values["quantile_grid"]]
        row = {name: grid[int(level * count)] for name, level in QUANTILE_LEVELS.items()}
        row.update({
            "p_up": float(values["p_up"]),
            "recalibrated": bool(values["recalibrated"]),
            "matured_pit_count": int(values["matured_pit_count"]),
            "quantile_grid_sha256": canonical_hash(grid),
        })
        if not 0.0 <= row["p_up"] <= 1.0:
            raise TimeSeriesV8DailyError("daily probability escaped the fraction contract")
        ordered = [row[name] for name in QUANTILE_LEVELS]
        if ordered != sorted(ordered):
            raise TimeSeriesV8DailyError("daily quantile crossing")
        out[horizon] = row
    return out


def model_input_fingerprint(bundle: Any, anchor: dict[str, Any]) -> str:
    """Bind retry identity to the actual frozen inference arguments and price anchor.

    Hash transformed PIT inputs, not receipt acquisition clocks. Confirmed
    same-origin corrections and updated macro factors must trigger a revision.
    """
    if not np.isfinite(float(anchor["value"])) or float(anchor["value"]) <= 0:
        raise TimeSeriesV8DailyError("invalid price anchor for daily fingerprint")
    matrices = {}
    for key in ("endogenous", "exogenous"):
        values = np.asarray(getattr(bundle, key), dtype=float)
        names = tuple(getattr(bundle, key + "_names"))
        if (values.ndim != 2 or values.shape != (len(bundle.dates), len(names))
                or not np.isfinite(values).all()):
            raise TimeSeriesV8DailyError(f"invalid {key} inputs for daily fingerprint")
        matrices[key] = {"names": names, "values": values.tolist()}
    return canonical_hash({"schema_version": 1, "dates": tuple(bundle.dates),
                           "matrices": matrices, "anchor": anchor})


def _input_provenance(
    inputs: dict[str, Any], origin: str, *, model_input_sha256: str | None = None,
) -> dict[str, Any]:
    fills = sorted(
        (row for row in inputs["fills"] if row["observation_time"] <= origin),
        key=lambda row: (row["series_id"], row["observation_time"]),
    )
    carried = sorted(
        (row for row in inputs["carried"] if row["observation_time"] <= origin),
        key=lambda row: (row["series_id"], row["observation_time"]),
    )
    state = {
        "origin": origin,
        "provisional_inputs": [
            {key: row[key] for key in ("series_id", "observation_time", "value", "source")}
            for row in fills
        ],
        "carried_forward": [
            {key: row[key] for key in ("series_id", "observation_time", "value", "carried_from")}
            for row in carried
        ],
    }
    if model_input_sha256 is not None:
        state["model_input_sha256"] = model_input_sha256
    return {
        "provisional_inputs": fills,
        "carried_forward": carried,
        "input_state": "provisional" if fills else "confirmed",
        "input_state_hash": canonical_hash(state),
    }


def daily_forecast_timeseries_v8(
    root: Path, *, now: datetime | None = None,
    fetcher: Fetcher | None = _http_get,
    quote_fetcher: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Append the daily display forecast for the latest completed session (idempotent)."""
    from .timeseries_v8.pipeline import _chain_append, _sealed_bundle, _sealed_gate_passed
    from .timeseries_v2.contracts import require_dfm_runtime

    now = now or datetime.now(timezone.utc)
    contract = load_contract_v8(root)
    verify_v2_benchmark(root, contract)
    require_dfm_runtime()
    sealed_row = _sealed_gate_passed(root)
    inputs = collect_inputs(root, contract=contract, now=now, fetcher=fetcher,
                            quote_fetcher=quote_fetcher)
    with market_overlay(_overlay_rows(inputs)):
        bundle = _sealed_bundle(root, contract)
    origin = bundle.dates[-1]
    anchor = _anchor_level(root, origin, inputs)
    model_input_sha256 = model_input_fingerprint(bundle, anchor)
    provenance = _input_provenance(inputs, origin, model_input_sha256=model_input_sha256)
    rows = read_daily_rows(root)
    newest = latest_effective(rows)
    summary = {
        "origin": origin, "expected_session": inputs["expected_session"],
        "input_state": provenance["input_state"],
        "provisional_series": sorted({row["series_id"] for row in provenance["provisional_inputs"]}),
        "fill_failures": inputs["failures"],
    }
    if newest is not None and newest["origin"] > origin:
        return {**summary, "skipped": f"a newer daily origin {newest['origin']} already exists"}
    same_origin = [row for row in effective_rows(rows) if row["origin"] == origin]
    previous = same_origin[-1] if same_origin else None
    if previous is not None and previous["input_state_hash"] == provenance["input_state_hash"]:
        return {**summary, "display_id": previous["display_id"],
                "skipped": "this origin and input state are already recorded"}
    if (previous is not None and previous["input_state"] == "confirmed"
            and provenance["input_state"] == "provisional"):
        return {**summary, "display_id": previous["display_id"],
                "skipped": "a confirmed row for this origin is not replaced by a provisional one"}
    config = frozen_config(contract)
    scores, run_summary = frozen_inference(contract, config, bundle)
    forecast = run_summary["shadow_forecast"]
    if forecast["origin"] != origin:
        raise TimeSeriesV8DailyError("inference origin drifted from the bundle origin")
    identity = {
        "model": contract["model_id"], "config": config.as_manifest(),
        "origin": origin, "input_state_hash": provenance["input_state_hash"],
    }
    display_id = "tsv8-daily-" + canonical_hash(identity)[:24]
    if any(row["display_id"] == display_id for row in rows):
        # Returning to an older superseded state is a new transition, not a
        # duplicate append. Preserve normal IDs and link the returning state.
        identity["supersedes"] = None if previous is None else previous["display_id"]
        display_id = "tsv8-daily-" + canonical_hash(identity)[:24]
    payload = {
        "schema_version": 1,
        "display_id": display_id,
        "kind": "daily_display",
        "display_only": True,
        "scoring_excluded": True,
        "cadence": "daily",
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "origin": origin,
        "expected_session": inputs["expected_session"],
        "input_state": provenance["input_state"],
        "input_state_hash": provenance["input_state_hash"],
        "input_fingerprint_version": 2,
        "model_input_sha256": model_input_sha256,
        "provisional_inputs": provenance["provisional_inputs"],
        "carried_forward": provenance["carried_forward"],
        "supersedes": None if previous is None else previous["display_id"],
        "knowledge_cutoff": inputs["knowledge_cutoff"],
        "contract_hash": frozen_hash(contract),
        "model_code_hash": model_code_hash(root),
        "sealed_run_id": sealed_row["run_id"],
        "config": config.as_manifest(),
        "anchor": anchor,
        "grid_levels_count": forecast["grid_levels_count"],
        "ensemble_weights": forecast["ensemble_weights"],
        "block_length": forecast["block_length"],
        "ewma_lambda": forecast["ewma_lambda"],
        "horizons": _compact_horizons(forecast),
        "matured_origins_at_emit": len({row.date for row in scores}),
        "probability_unit": "fraction",
    }
    row = _chain_append(root, DAILY_LEDGER_RELATIVE, payload, key="display_id")
    return {**summary, "display_id": row["display_id"], "supersedes": row["supersedes"],
            "appended": True}


def _anchor_level(root: Path, origin: str, inputs: dict[str, Any]) -> dict[str, Any]:
    from .timeseries_v2.market_archive import read_market_observations

    for row in read_market_observations(root, knowledge_cutoff=inputs["knowledge_cutoff"]):
        if row.series_id == "NASDAQCOM" and row.observation_time == origin:
            return {"series_id": "NASDAQCOM", "value": float(row.value),
                    "source": row.source_id, "provisional": False}
    for row in inputs["fills"]:
        if row["series_id"] == "NASDAQCOM" and row["observation_time"] == origin:
            return {"series_id": "NASDAQCOM", "value": float(row["value"]),
                    "source": row["source"], "provisional": True}
    raise TimeSeriesV8DailyError(f"NASDAQCOM level at {origin} is unavailable")


# ── display pointer ─────────────────────────────────────────────────────────

def _age_hours(observation_time: str, now: datetime) -> float:
    end = datetime.fromisoformat(observation_time).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc)
    return max(0.0, (now - end).total_seconds() / 3600.0)


def publish_daily_display_latest(root: Path, *, now: datetime | None = None, persist: bool = True) -> dict[str, Any]:
    """Write the fail-closed daily display pointer (same schema as the weekly pointer).

    Gates mirror ``publish_latest_timeseries_v8``: the disclosed sealed gate,
    input freshness (measured on the inputs the daily row actually used —
    archive or provisional — so a weekend archive lag does not hide a fresh
    daily row), and the weekly shadow-resolution CRPS monitor.  The sealed and
    monitoring logic is copied, not imported, because the weekly publisher
    lives in the hashed package.
    """
    from .timeseries_v2.market_archive import read_market_observations
    from .timeseries_v8.pipeline import (
        SHADOW_RESOLUTION_LEDGER,
        TimeSeriesV8PipelineError,
        _atomic_json,
        _read_chain,
        _sealed_gate_passed,
    )

    contract = load_contract_v8(root)
    now = now or datetime.now(timezone.utc)
    cutoff = now.isoformat(timespec="seconds")
    reasons: list[str] = []
    sealed_row = None
    try:
        sealed_row = _sealed_gate_passed(root)
    except TimeSeriesV8PipelineError as exc:
        reasons.append(str(exc))
    rows = read_daily_rows(root)
    row = latest_effective(rows)
    if row is None:
        reasons.append("daily display forecast가 아직 없음")
    elif sealed_row is not None and row.get("sealed_run_id") != sealed_row["run_id"]:
        reasons.append("daily row의 봉인 run id가 봉인 원장과 다름")
    if row is not None and row.get("contract_hash") != frozen_hash(contract):
        reasons.append("daily row의 contract_hash가 동결 계약과 다름")
    operational = contract["operational_gate"]
    market = read_market_observations(root, knowledge_cutoff=cutoff)
    used = [] if row is None else list(row.get("provisional_inputs") or [])
    freshness = []
    for alternatives in operational["required_market_groups"]:
        label = "_or_".join(alternatives)
        candidates = [
            (item.observation_time, "archive") for item in market if item.series_id in set(alternatives)
        ] + [
            (item["observation_time"], "provisional") for item in used
            if item["series_id"] in set(alternatives)
            and (row is None or item["observation_time"] <= row["origin"])
        ]
        if not candidates:
            freshness.append({"group": label, "status": "missing"})
            reasons.append(f"필수 시장 입력 누락: {label}")
            continue
        observation, origin_kind = max(candidates)
        from .forecast_source_freshness import source_freshness
        # Preserve the real observation date; a fresh fetch cannot reset age.
        report = source_freshness(alternatives[0], observation, now)
        status = report["status"]
        freshness.append({
            **report, "group": label, "provisional": origin_kind == "provisional",
        })
        if status != "fresh":
            reasons.append(f"필수 시장 입력 신선도 초과: {label}")
    resolutions = _read_chain(root, SHADOW_RESOLUTION_LEDGER)
    recent_required = int(operational["recent_origins"])
    matured = sorted({item["origin"] for item in resolutions if item["horizon"] == 63})
    monitoring: dict[str, Any] = {"matured_shadow_origins": len(matured)}
    if len(matured) >= recent_required:
        recent = set(matured[-recent_required:])
        window = [item for item in resolutions if item["origin"] in recent]
        model_crps = float(np.mean([i["model_crps"] for i in window if i["horizon"] in (21, 63)]))
        baseline_crps = float(np.mean([i["baseline_crps"] for i in window if i["horizon"] in (21, 63)]))
        under = (model_crps - baseline_crps) / baseline_crps if baseline_crps > 0 else 0.0
        monitoring.update({
            "source": "shadow_resolutions",
            "recent_long_horizon_crps_underperformance": under,
        })
        if under > float(operational["crps_max_underperformance"]):
            reasons.append("최근 shadow 원점 CRPS가 기준선 대비 허용치 초과")
    else:
        monitoring["source"] = "sealed_backtest_until_shadow_origins_mature"
    visible = not reasons
    payload: dict[str, Any] = {
        "schema_version": 1,
        "model_id": contract["model_id"],
        "model_version": int(contract["model_version"]),
        "status": "shadow_live" if visible else "shadow_operational_hold",
        "display_state": "research_reference" if visible else "validation_pending",
        "as_of": None if row is None else row["origin"],
        "knowledge_cutoff": cutoff,
        "probability_unit": "fraction",
        "probability_space": str(contract["probability_contract"]["space"]),
        "publication": {
            "customer_numbers_visible": visible,
            "combined_with_official_forecasts": False,
            "combined_with_scenario_v5_2": False,
            "reference_opinion_only": True,
        },
        "gate": {
            "sealed_gate_pass": bool(sealed_row is not None),
            "sealed_run_id": None if sealed_row is None else sealed_row["run_id"],
            "operational_pass": visible,
            "reasons": reasons,
        },
        "operational": {"freshness": freshness, "monitoring": monitoring},
        "daily": {
            "cadence": "daily",
            "display_only": True,
            "scoring_excluded": True,
            "display_id": None if row is None else row["display_id"],
            "input_state": None if row is None else row["input_state"],
            "provisional_series": [] if row is None else sorted(
                {item["series_id"] for item in row.get("provisional_inputs") or []}),
            "provisional_inputs": [] if row is None else [
                {key: item[key] for key in ("series_id", "observation_time", "value", "source")}
                for item in row.get("provisional_inputs") or []
            ],
            "carried_forward": [] if row is None else [
                {key: item[key] for key in ("series_id", "observation_time", "carried_from")}
                for item in row.get("carried_forward") or []
            ],
            "anchor": None if row is None else row["anchor"],
            "row_knowledge_cutoff": None if row is None else row["knowledge_cutoff"],
        },
        "footnote": "*미국 시장·미국 공식 거시자료 기준 · 참고 의견",
    }
    if visible and row is not None:
        payload["horizons"] = {
            horizon: {
                **{name: float(values[name]) for name in QUANTILE_LEVELS},
                "probability_up": float(values["p_up"]),
            }
            for horizon, values in row["horizons"].items()
        }
    payload["content_hash"] = canonical_hash(payload)
    if persist:
        _atomic_json(root / DAILY_LATEST_RELATIVE, payload)
    return payload


def verify_daily_display(root: Path) -> dict[str, Any]:
    """Chain integrity, supersede discipline, and the scoring exclusion of daily rows."""
    from .timeseries_v8.pipeline import (
        SHADOW_FORECAST_LEDGER,
        SHADOW_RESOLUTION_LEDGER,
        _read_chain,
        verify_chain,
    )

    errors = list(verify_chain(root, DAILY_LEDGER_RELATIVE))
    rows = read_daily_rows(root)
    seen: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if row.get("kind") != "daily_display" or row.get("scoring_excluded") is not True \
                or row.get("display_only") is not True:
            errors.append(f"daily[{index}]: row is not marked display-only/scoring-excluded")
        version = row.get("input_fingerprint_version")
        if version == 2:
            digest = row.get("model_input_sha256")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                errors.append(f"daily[{index}]: invalid model input fingerprint")
            else:
                expected = _input_provenance(
                    {"fills": row.get("provisional_inputs", []), "carried": row.get("carried_forward", [])},
                    row["origin"], model_input_sha256=digest,
                )["input_state_hash"]
                if row.get("input_state_hash") != expected:
                    errors.append(f"daily[{index}]: model input fingerprint binding mismatch")
        elif version not in (None, 1):
            errors.append(f"daily[{index}]: unsupported input fingerprint version")
        target = row.get("supersedes")
        if target is not None:
            prior = seen.get(target)
            if prior is None:
                errors.append(f"daily[{index}]: supersedes an unknown or later row")
            elif prior["origin"] != row["origin"]:
                errors.append(f"daily[{index}]: supersedes a different origin")
        seen[row["display_id"]] = row
    daily_ids = set(seen)
    shadow_ids = {row.get("forecast_id") for row in _read_chain(root, SHADOW_FORECAST_LEDGER)}
    resolved_ids = {row.get("forecast_id") for row in _read_chain(root, SHADOW_RESOLUTION_LEDGER)}
    if daily_ids & (shadow_ids | resolved_ids):
        errors.append("a daily display row leaked into the weekly shadow/resolution ledgers")
    return {"ok": not errors, "errors": errors, "daily_rows": len(rows),
            "effective_rows": len(effective_rows(rows))}


# ── evidence helper: publisher values vs the archive ───────────────────────

def treasury_matches_archive(root: Path, payload: bytes) -> dict[str, Any]:
    """Compare Treasury par-curve 2Y/10Y against archived DGS2/DGS10 (2 decimals)."""
    from .timeseries_v2.market_archive import parse_treasury_xml, read_market_observations

    archive = {(row.series_id, row.observation_time): row.value
               for row in read_market_observations(root)}
    compared = mismatched = 0
    for day, two, ten in parse_treasury_xml(payload):
        for series, value in (("DGS2", two), ("DGS10", ten)):
            if (series, day) in archive:
                compared += 1
                if round(archive[(series, day)], 2) != round(value, 2):
                    mismatched += 1
    return {"compared": compared, "mismatched": mismatched}


def parse_treasury_csv(payload: bytes) -> list[tuple[str, float, float]]:
    """Parse the Treasury CSV export (``Date``, ``2 Yr``, ``10 Yr``) — same values as the XML."""
    out = []
    for row in csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))):
        raw_day, two, ten = row.get("Date"), row.get("2 Yr"), row.get("10 Yr")
        if not raw_day or not two or not ten:
            continue
        day = datetime.strptime(raw_day.strip(), "%m/%d/%Y").date().isoformat()
        out.append((day, float(two), float(ten)))
    return out
