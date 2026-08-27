"""R5 E3' PIT calendar event-variance multiplier candidate."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import math
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from ai_fc.timeseries_v7_r4.cross_fit_calibration import CalibrationCase, cross_fit_quantiles
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.empirical_mixture import empirical_mixture_crps, optimize_empirical_mixture

from .conditional_scale_selection import _eligible, canonical_json
from .e0_nesting import load_e0_matrix, prove_e0_nesting
from .e0_rescale import _paired_summary
from .fhs_har_first_light import E0_FLOORS, HORIZONS, _label_inputs, _mixture_quantiles, _sample_hash


EVENT_KINDS = ("fomc", "cpi", "nfp")
GAMMA_BOUNDS = (-0.75, 4.0)
USER_AGENT = "Mozilla/5.0 (compatible; AIInvestingResearch/1.0; contact=research@example.invalid)"
MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
WEEKDAYS = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
MONTH_TOKENS = {
    "Jan.": 1, "Feb.": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "Aug.": 8, "Sept.": 9, "Oct.": 10, "Nov.": 11, "Dec.": 12,
    **MONTHS,
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        self.values.append(data)


def _visible_text(raw: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.values))).strip()


def parse_bls_schedule(raw: bytes, year: int) -> list[dict[str, str]]:
    text = _visible_text(raw)
    pattern = re.compile(
        rf"(?:{WEEKDAYS}),\s+(?P<month>{'|'.join(MONTHS)})\s+(?P<day>\d{{1,2}}),\s+"
        rf"(?P<year>{year})\s+\d{{1,2}}:\d{{2}}\s+(?:AM|PM)\s+"
        r"(?P<release>Employment Situation|Consumer Price Index)(?=\s+for\b)"
    )
    result: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        release = match.group("release")
        result.append({
            "kind": "nfp" if release == "Employment Situation" else "cpi",
            "date": f"{year:04d}-{MONTHS[match.group('month')]:02d}-{int(match.group('day')):02d}",
            "source": f"https://www.bls.gov/schedule/{year}/home.htm",
            "schedule_status": "official_historical_annual_calendar",
        })
    # The 1990s/early-2000s annual pages list release name first and the
    # publication date second (often omitting the repeated calendar year).
    legacy = re.compile(
        rf"(?:The )?(?P<release>Employment Situation|Consumer Price Index(?:es)?),\s+"
        rf"[A-Za-z]+\s+(?P<observation_year>\d{{4}})\s+"
        rf"(?P<month>{'|'.join(re.escape(k) for k in MONTH_TOKENS)})\s+"
        rf"(?P<day>\d{{1,2}})(?:,\s*{year})?\s+\d{{1,2}}:\d{{2}}\s+(?:am|pm)", re.IGNORECASE,
    )
    for match in legacy.finditer(text):
        release = match.group("release").lower()
        token = next(key for key in MONTH_TOKENS if key.lower() == match.group("month").lower())
        schedule_year = year + int(MONTH_TOKENS[token] == 1
                                   and int(match.group("observation_year")) >= year)
        result.append({
            "kind": "nfp" if "employment" in release else "cpi",
            "date": f"{schedule_year:04d}-{MONTH_TOKENS[token]:02d}-{int(match.group('day')):02d}",
            "source": f"https://www.bls.gov/schedule/{year}/home.htm",
            "schedule_status": "official_historical_annual_calendar",
        })
    return result


def parse_fomc_schedule(raw: bytes, year: int) -> list[dict[str, str]]:
    text = _visible_text(raw)
    pattern = re.compile(
        rf"(?P<month>{'|'.join(MONTHS)})\s+(?P<first>\d{{1,2}})(?:-(?P<last>\d{{1,2}}))?\s+"
        rf"Meeting\s+-\s+{year}\b"
    )
    result: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        day = int(match.group("last") or match.group("first"))
        result.append({
            "kind": "fomc", "date": f"{year:04d}-{MONTHS[match.group('month')]:02d}-{day:02d}",
            "source": f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm",
            "schedule_status": "official_historical_meeting_calendar",
        })
    if not result:
        source_html = raw.decode("utf-8", errors="replace")
        start = source_html.find(f"{year} FOMC Meetings")
        if start >= 0:
            later = [position for candidate in range(year + 1, year + 8)
                     if (position := source_html.find(f"{candidate} FOMC Meetings", start + 1)) >= 0]
            section = source_html[start:min(later) if later else len(source_html)]
            current_pattern = re.compile(
                r"fomc-meeting__month[^>]*>\s*<strong>(?P<month>[A-Za-z]+)</strong>.*?"
                r"fomc-meeting__date[^>]*>\s*(?P<first>\d{1,2})(?:-(?P<last>\d{1,2}))?\*?\s*</div>",
                re.DOTALL,
            )
            for match in current_pattern.finditer(section):
                if match.group("month") not in MONTHS:
                    continue
                day = int(match.group("last") or match.group("first"))
                result.append({
                    "kind": "fomc", "date": f"{year:04d}-{MONTHS[match.group('month')]:02d}-{day:02d}",
                    "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                    "schedule_status": "official_meeting_calendar_archive_section",
                })
    return result


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"official schedule returned HTTP {response.status}: {url}")
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        # BLS rejects Python's HTTP stack while serving the identical public page
        # through Windows WebRequest.  Capture raw response bytes as base64; no
        # credentials, cookies, or provider secrets cross this boundary.
        script = (
            "$ProgressPreference='SilentlyContinue';"
            f"$r=Invoke-WebRequest -Uri '{url}' -Headers @{{'User-Agent'='{USER_AGENT}'}} "
            "-UseBasicParsing;[Convert]::ToBase64String($r.RawContentStream.ToArray())"
        )
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                                   check=False, capture_output=True, text=True, timeout=45)
        if completed.returncode != 0 or not completed.stdout.strip():
            raise RuntimeError(f"official schedule retrieval failed: {url}") from error
        return base64.b64decode(completed.stdout.strip())


def collect_official_event_calendar(output_dir: Path, *, start_year: int = 1997,
                                    end_year: int = 2022) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    events: list[dict[str, str]] = []
    receipts: list[dict[str, Any]] = []
    retrieved_at = datetime.now(timezone.utc).isoformat()
    for year in range(start_year, end_year + 1):
        sources = (
            ("bls", f"https://www.bls.gov/schedule/{year}/home.htm", parse_bls_schedule),
            ("federal_reserve", (f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
                                  if year <= 2020 else
                                  "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
             parse_fomc_schedule),
        )
        for source_id, url, parser in sources:
            raw = _fetch(url)
            digest = hashlib.sha256(raw).hexdigest()
            source_dir = raw_dir / source_id
            source_dir.mkdir(exist_ok=True)
            (source_dir / f"{digest}.html").write_bytes(raw)
            parsed = parser(raw, year)
            if not parsed:
                raise ValueError(f"no required official events parsed for {source_id}:{year}")
            events.extend(parsed)
            receipts.append({"source_id": source_id, "year": year, "url": url,
                             "retrieved_at": retrieved_at, "raw_sha256": digest,
                             "raw_bytes": len(raw), "parsed_event_count": len(parsed)})
    unique = {(row["kind"], row["date"]): row for row in events}
    events = [unique[key] for key in sorted(unique)]
    if {row["kind"] for row in events} != set(EVENT_KINDS):
        raise ValueError("official event calendar is missing a required event kind")
    with (output_dir / "official_event_calendar.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in events:
            handle.write(canonical_json(row).decode("utf-8") + "\n")
    receipt = {
        "schema": "r5_official_historical_event_calendar_v1",
        "years": [start_year, end_year], "event_count": len(events),
        "counts": {kind: sum(row["kind"] == kind for row in events) for kind in EVENT_KINDS},
        "sources": receipts, "credential_used": False,
        "pit_basis": "official annual release and meeting calendars; event dates only, no outcomes",
    }
    (output_dir / "calendar_receipt.json").write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def load_event_calendar(path: Path) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows or {row.get("kind") for row in rows} != set(EVENT_KINDS):
        raise ValueError("complete official event calendar is required")
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("date", ""))) for row in rows):
        raise ValueError("event dates must be ISO calendar dates")
    return rows


def event_flags(events: list[dict[str, str]], *, origin: str, label_end: str) -> tuple[int, int, int]:
    return tuple(int(any(row["kind"] == kind and origin < row["date"] <= label_end
                         for row in events)) for kind in EVENT_KINDS)


def fit_event_gammas(train_rows: list[tuple[float, tuple[int, int, int]]]) -> tuple[float, float, float]:
    if len(train_rows) < 500:
        raise ValueError("at least 500 train rows are required")
    outcomes = np.asarray([row[0] for row in train_rows], dtype=float)
    design = np.asarray([row[1] for row in train_rows], dtype=float)
    base_variance = max(float(np.mean(outcomes ** 2)), 1e-12)

    def objective(gammas: np.ndarray) -> float:
        factors = np.prod(1.0 + design * gammas, axis=1)
        if np.any(factors <= 0):
            return 1e100
        variances = base_variance * factors
        return float(np.mean(np.log(variances) + outcomes ** 2 / variances))

    result = minimize(objective, np.zeros(3), method="SLSQP",
                      bounds=[GAMMA_BOUNDS] * 3, options={"ftol": 1e-12, "maxiter": 1000})
    if not result.success or not np.isfinite(result.fun):
        raise RuntimeError(f"event multiplier fit failed: {result.message}")
    return tuple(float(value) for value in result.x)


def event_multiplier_samples(e0: Iterable[float], *, flags: tuple[int, int, int],
                             gammas: tuple[float, float, float]) -> np.ndarray:
    values = np.asarray(tuple(e0), dtype=np.float64)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("finite E0 samples are required")
    if len(flags) != 3 or len(gammas) != 3 or any(gamma <= -1 for gamma in gammas):
        raise ValueError("three valid event flags and multipliers are required")
    if all(gamma == 0.0 for gamma in gammas):
        return values.copy()
    factor = math.prod(1.0 + gamma * flag for gamma, flag in zip(gammas, flags, strict=True))
    if factor <= 0:
        raise ValueError("event variance factor must be positive")
    center = float(np.mean(values))
    return center + (values - center) * math.sqrt(factor)


def run_event_multiplier(export_path: Path, *, calendar_path: Path, registered_e0_matrix: Path,
                         output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan, roles = export["five_role_plan"], export["five_role_plan"]["role_origins"]
    if plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("outer role must remain sealed")
    events = load_event_calendar(calendar_path)
    grouped, lookup = _label_inputs(export)
    train_cutoff = max(roles["train"])
    gammas: dict[int, tuple[float, float, float]] = {}
    fit_counts: dict[int, int] = {}
    for horizon in HORIZONS:
        rows: list[tuple[float, tuple[int, int, int]]] = []
        for origin in roles["train"]:
            label = lookup.get((origin, horizon))
            if label is None or str(label["mature_at"])[:10] > train_cutoff:
                continue
            rows.append((float(label["value"]), event_flags(
                events, origin=origin, label_end=str(label["label_end_session"]))))
        gammas[horizon] = fit_event_gammas(rows)
        fit_counts[horizon] = len(rows)

    matrix_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    horizon_summary: dict[str, Any] = {}
    for horizon in HORIZONS:
        gamma = gammas[horizon]
        role_data: dict[str, tuple[list[np.ndarray], list[np.ndarray], list[float]]] = {}
        for role in ("stacking", "calibration"):
            e0_rows: list[np.ndarray] = []
            candidate_rows: list[np.ndarray] = []
            actuals: list[float] = []
            for origin in roles[role]:
                label = lookup[(origin, horizon)]
                e0 = _eligible(grouped, origin, horizon)
                flags = event_flags(events, origin=origin, label_end=str(label["label_end_session"]))
                candidate = event_multiplier_samples(e0, flags=flags, gammas=gamma)
                e0_rows.append(e0); candidate_rows.append(candidate); actuals.append(float(label["value"]))
                matrix_rows.append({
                    "role": role, "origin_session": origin, "horizon_sessions": horizon,
                    "family": "E3_prime_event_multiplier", "factorization": {
                        "flags": dict(zip(EVENT_KINDS, flags, strict=True)),
                        "gammas": dict(zip(EVENT_KINDS, gamma, strict=True)),
                    },
                    "sample_hash": _sample_hash(candidate, origin=origin, horizon=horizon,
                                                 family="E3_prime_event_multiplier"),
                    "e0_sample_hash": _sample_hash(e0, origin=origin, horizon=horizon, family="E0"),
                })
            role_data[role] = (e0_rows, candidate_rows, actuals)
        e0_stack, candidate_stack, stack_actuals = role_data["stacking"]
        fitted = optimize_empirical_mixture([e0_stack, candidate_stack], stack_actuals,
                                            e0_floor=E0_FLOORS[horizon])
        weights = (float(fitted.weights[0]), float(fitted.weights[1]))
        e0_cal, candidate_cal, cal_actuals = role_data["calibration"]
        cases: list[CalibrationCase] = []
        provisional: list[dict[str, Any]] = []
        for origin, e0, candidate, actual in zip(roles["calibration"], e0_cal, candidate_cal,
                                                 cal_actuals, strict=True):
            e0_score = empirical_crps(e0, actual)
            candidate_score = empirical_crps(candidate, actual)
            stacked_score = empirical_mixture_crps([[e0], [candidate]], [actual], weights)
            cases.append(CalibrationCase(origin, "calibration",
                                         _mixture_quantiles(e0, candidate, weights), actual))
            provisional.append({"origin_session": origin, "horizon": horizon,
                                "role": "calibration", "actual": actual,
                                "e0_crps": e0_score, "candidate_crps": candidate_score,
                                "stacked_crps": stacked_score,
                                "paired_advantage": e0_score - stacked_score,
                                "e0_weight": weights[0], "candidate_weight": weights[1]})
        calibrated = cross_fit_quantiles(cases)
        for row in provisional:
            quantiles = calibrated[row["origin_session"]]
            row.update({"p10": quantiles[1], "p25": quantiles[4], "p50": quantiles[9],
                        "p75": quantiles[14], "p90": quantiles[17]})
            score_rows.append(row)
        horizon_summary[str(horizon)] = {
            "gammas": dict(zip(EVENT_KINDS, gamma, strict=True)), "fit_role": "train",
            "fit_rows": fit_counts[horizon],
            "weights": {"E0": weights[0], "E3_prime": weights[1]},
            "e0_floor": E0_FLOORS[horizon], "stacking_crps": fitted.crps,
            "stacking_e0_only_fallback": fitted.used_e0_only_fallback,
            **_paired_summary(provisional, horizon=horizon),
            "cross_fit_calibration": {
                "fit_role": "calibration_temporal_cross_fit",
                "evaluation_role": "calibration_cross_fit_holdout",
                "case_count": len(provisional),
                "coverage80": float(np.mean([row["p10"] <= row["actual"] <= row["p90"]
                                               for row in provisional])),
                "coverage50": float(np.mean([row["p25"] <= row["actual"] <= row["p75"]
                                               for row in provisional])),
            },
        }

    nesting = prove_e0_nesting(
        load_e0_matrix(registered_e0_matrix),
        lambda coordinate: event_multiplier_samples(coordinate.values, flags=(1, 1, 1),
                                                     gammas=(0.0, 0.0, 0.0)), tolerance=1e-12,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(score_rows).to_parquet(output_dir / "calibration_paired_scores.parquet", index=False)
    with (output_dir / "factorized_sample_matrix.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in matrix_rows:
            handle.write(canonical_json(row).decode("utf-8") + "\n")
    summary = {
        "schema": "r5_e3_prime_event_multiplier_v1", "family": "E3_prime_event_multiplier",
        "event_kinds": list(EVENT_KINDS), "gamma_bounds": list(GAMMA_BOUNDS),
        "horizons": horizon_summary, "nesting_proof": nesting,
        "role_hashes": plan["role_hashes"],
        "calendar_sha256": hashlib.sha256(calendar_path.read_bytes()).hexdigest(),
        "sample_matrix": {"format": "exact_factorized_matrix_v1", "coordinate_count": len(matrix_rows)},
        "row_use_counters": {"train_rows_used": sum(fit_counts.values()),
                             "stacking_rows_used": len(roles["stacking"]) * 4,
                             "calibration_rows_used": len(roles["calibration"]) * 4,
                             "outer_rows_used": 0},
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (output_dir / "event_multiplier_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--output-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--export", type=Path, required=True)
    run.add_argument("--calendar", type=Path, required=True)
    run.add_argument("--registered-e0-matrix", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "collect":
        collect_official_event_calendar(args.output_dir)
    else:
        run_event_multiplier(args.export, calendar_path=args.calendar,
                             registered_e0_matrix=args.registered_e0_matrix,
                             output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
