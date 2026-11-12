"""과열도 v7 — 영향도 점수제의 1회 측정: 순위표·가중·기준값·게이트 판정을 계약 ``frozen`` 에 적는다.

읽기 전용이다(원천 호출 없음, 원장·스냅샷 무수정). 쓰는 것은 검토 산출물뿐이다:
  * 계약 파일 끝의 ``frozen`` 블록 — 비어 있을 때만, 그리고 보고서보다 먼저 적는다. 한 번 적힌 판정은 다시 쓰지 않는다.
  * ``--report`` 로 준 Markdown 보고서와 같은 이름의 JSON(``docs/audit/overheat_v7*.md``)

두 가지로만 돈다.
  * 공식 실행: ``frozen`` 이 비어 있을 때. 반드시 ``--write-frozen`` 과 함께(적지 않는 시험 실행은 거부한다).
  * 재현: ``frozen`` 이 있을 때. 같은 계산을 다시 해 동결값과 대조만 한다.

    python tools/measure_overheat_influence_v7.py --write-frozen --report docs/audit/overheat_v7_validation_20261112.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc import dotcom_overheat_v7 as v7  # noqa: E402

REPORT_DIR = Path("docs/audit")
FROZEN_MARKER = "\nfrozen:"
FOLDS = (
    ("fit 1973-01..1988-12 → test 1990-01..1996-12", date(1988, 12, 31), date(1990, 1, 1), date(1996, 12, 31)),
    ("fit 1973-01..1996-12 → test 2003-01..2009-12", date(1996, 12, 31), date(2003, 1, 1), date(2009, 12, 31)),
    ("fit 1973-01..2009-12 → test 2010-01..2017-12", date(2009, 12, 31), date(2010, 1, 1), date(2017, 12, 31)),
    ("fit train → test holdout", date(2017, 12, 31), date(2020, 1, 1), None),
)


class ToolError(SystemExit):
    def __init__(self, message: str) -> None:
        sys.stderr.write(message + "\n")
        super().__init__(2)


def _gate(passed: Any, value: Any, **extra: Any) -> dict[str, Any]:
    return {"passed": bool(passed), "value": value, **extra}


def guarded(fn) -> dict[str, Any]:
    try:
        return fn()
    except (TypeError, ValueError, KeyError, IndexError, ZeroDivisionError) as exc:
        return {"passed": False, "value": None, "reason": f"not evaluable: {type(exc).__name__}: {exc}"}


def need(value: float | None) -> float:
    if value is None:
        raise ValueError("value on hold or missing")
    return value


def line_record(line: dict[str, Any] | None) -> dict[str, Any] | None:
    if line is None:
        return None
    return {"weights": line["weights"], "signs": {k: int(v) for k, v in line["signs"].items()},
            "anchors": {k: {"median": round(v["median"], 10), "mad": round(v["mad"], 10)} for k, v in line["anchors"].items()},
            "C0": round(line["scale"]["C0"], 8), "Cpk": round(line["scale"]["Cpk"], 8),
            "mad": round(line["scale"]["mad"], 8)}


def placebo_line(panel: v7.Panel, ledger: v7.Store, contract: dict[str, Any], scores: dict[str, dict[str, Any]],
                 group: str, count: int) -> dict[str, Any] | None:
    """위약용 줄 — 자격 문턱 대신 '실제 줄과 같은 개수의 점수 상위 후보'(생산 가능한 것)를 점수 비례로 묶는다."""
    rows = [(key, row) for key, row in scores.items()
            if row["group"] == group and row.get("status") not in {"dropped", "not_scoreable"}
            and v7.standardisation(ledger, key) is not None]
    rows.sort(key=lambda item: -item[1]["E"])
    top = rows[:count]
    if not count or len(top) < count:
        return None
    points = {key: max(float(row["E"]), 1e-6) for key, row in top}
    weights = v7._fill(points, 100.0, float(contract["weights"]["caps"][group]["indicator"])) \
        or {key: 100.0 / len(points) for key in points}
    return {"weights": weights, "signs": {k: panel.sign(k) for k in weights},
            "anchors": {k: v7.standardisation(ledger, k) for k in weights}}


def run(root: Path) -> dict[str, Any]:
    contract = v7.load_contract(root)
    as_of = date.fromisoformat(str(contract["gate_as_of"]))
    analysis = v7.load_analysis_store(root, contract)
    ledger = v7.load_ledger_store(root, contract)
    if analysis.sessions[-1] != as_of:
        raise ToolError(f"analysis inputs end {analysis.sessions[-1]}, contract gate_as_of is {as_of}")
    if ledger.sessions[-1] < as_of:
        raise ToolError(f"ledger ends {ledger.sessions[-1]} before the gate date {as_of}")
    today = ledger.session_index(as_of)
    panel = v7.Panel(analysis, contract)
    base = v7.build_spec(panel, ledger, contract, v7.Options())
    windows = base["windows"]
    heat, pressure = base["lines"]["heat"], base["lines"]["pressure"]
    scores = base["scores"]
    for group_line in (heat, pressure):
        for key, weight in ((group_line or {}).get("weights") or {}).items():
            scores[key]["weight"] = weight
    caps = contract["weights"]["caps"]["heat"]

    # ── 측정 범위(변형)와 부문 제외 범위 ──
    variant_specs: dict[str, Any] = {}
    band: dict[str, float | None] = {"base": v7.heat_today(ledger, heat, index=today)}
    for name, kwargs in v7.VARIANTS.items():
        spec = v7.build_spec(panel, ledger, contract, v7.Options(**kwargs))["lines"]["heat"]
        variant_specs[name] = spec
        band[name] = v7.heat_today(ledger, spec, index=today, clamp=kwargs.get("clamp", True))
    band["drop_top"] = None
    if heat is not None:
        top = max(heat["weights"], key=lambda k: (heat["weights"][k], scores[k]["E"]))
        band["drop_top"] = v7.heat_today(
            ledger, v7.build_spec(panel, ledger, contract, v7.Options(drop=[top]))["lines"]["heat"], index=today)
    family_variants: dict[str, Any] = {}
    family_band: dict[str, float | None] = {}
    for family in sorted({scores[k]["family"] for k in (heat or {}).get("weights", {})}):
        spec = v7.build_spec(panel, ledger, contract, v7.Options(drop_families=[family]))["lines"]["heat"]
        family_band[family] = v7.heat_today(ledger, spec, index=today)
        if spec is not None:
            family_variants[family] = {**line_record(spec), "grid": []}

    # ── 일간 이력(당시 화면 재현) — 표준화 구간의 첫 달부터 ──
    history: list[tuple[int, float | None, tuple]] = []
    if heat is not None:
        first = v7.bisect.bisect_left(ledger.sessions, v7.STD_WINDOW[0])
        for i in range(first, today + 1):
            out = v7.composite(ledger, i, heat)
            history.append((i, v7.headline(out["value"], heat["scale"]), out["periods"]))
    by_index = {i: h for i, h, _ in history}
    month_ends = [i for i in ledger.month_ends if i in by_index]
    dd12 = v7.forward_drawdown(ledger.close, 252)

    def h_on(day: date) -> float:
        return need(by_index.get(ledger.session_index(day)))

    checks: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    pressure_gates: dict[str, Any] = {}
    placebo_note = "위약은 실제 줄과 같은 개수의 점수 상위 후보로 줄을 만든다. 위약에서는 하락장 적중(P3)을 채점하지 않는다"
    n_train = len(v7.train_sample(analysis, windows, 252))
    real_heat = v7.composite_association(panel, heat, windows)
    real_pressure = v7.composite_association(panel, pressure, windows)
    placebo_heat: list[float] = []
    placebo_pressure: list[float] = []
    for k in range(24, n_train - 23, 12):
        shifted = v7.score_candidates(panel, windows, v7.Options(score_p3=False), outcome_shift=k)
        for group, real_line, bucket in (("heat", heat, placebo_heat), ("pressure", pressure, placebo_pressure)):
            if real_line is None:
                continue
            line = placebo_line(panel, ledger, contract, shifted, group, len(real_line["weights"]))
            value = v7.composite_association(panel, line, windows, shift=k)
            if value is None:
                raise ToolError(f"placebo run k={k} for {group} is not computable — the gate cannot be evaluated")
            bucket.append(value)

    if heat is None:
        reason = "heat line not computable (eligible indicators below the minimum or weights infeasible)"
        gates = {f"G{n}": {"passed": False, "value": None, "reason": reason} for n in range(1, 13)}
    else:
        scale = heat["scale"]
        std = [by_index[i] for i in month_ends if v7.STD_WINDOW[0] <= ledger.sessions[i] <= v7.STD_WINDOW[1]
               and by_index[i] is not None]
        checks["C1"] = guarded(lambda: _gate(abs(h_on(v7.PEAK_DAY) - 100) < 1e-6 and abs(float(np.median(std))) < 1e-6,
                                             [round(h_on(v7.PEAK_DAY), 3), round(float(np.median(std)), 3)]))

        def c2() -> dict[str, Any]:
            recent = [need(h) for _, h, _ in history[-61:]]
            moved = sum(1 for a, b in zip(recent, recent[1:]) if round(a, 1) != round(b, 1))
            return _gate(len(recent) == 61 and moved >= 45, moved)

        checks["C2"] = guarded(c2)
        family_sums: dict[str, float] = {}
        for k, w in heat["weights"].items():
            family_sums[scores[k]["family"]] = family_sums.get(scores[k]["family"], 0.0) + w
        price = sum(w for k, w in heat["weights"].items() if panel.candidates[k].get("price_term"))
        checks["C3"] = _gate(
            max(heat["weights"].values()) <= caps["indicator"] + 1e-4 and max(family_sums.values()) <= caps["family"] + 1e-4
            and price <= caps["price_term_total"] + 1e-4 and abs(sum(heat["weights"].values()) - 100.0) < 1e-3,
            {"max_indicator": round(max(heat["weights"].values()), 2), "max_family": round(max(family_sums.values()), 2),
             "price_term": round(price, 2)})
        gates["G1"] = _gate(scale["mad"] > 0 and scale["Cpk"] - scale["C0"] >= 2.0 * 1.4826 * scale["mad"],
                            round((scale["Cpk"] - scale["C0"]) / (1.4826 * scale["mad"]), 2) if scale["mad"] else None)
        gates["G2"] = guarded(lambda: _gate(all(h_on(d) <= 25 for d in v7.BEAR_LOWS),
                                            [round(h_on(d), 1) for d in v7.BEAR_LOWS]))

        def g3() -> dict[str, Any]:
            rows = [(need(by_index[i]), ledger.sessions[i].isoformat()) for i in month_ends
                    if ledger.sessions[i] >= date(2003, 1, 1) and i + 252 <= today and dd12[i] < 0.10]
            top_row = max(rows)
            return _gate(top_row[0] <= 60, [round(top_row[0], 1), top_row[1]], months=len(rows))

        gates["G3"] = guarded(g3)

        def g4() -> dict[str, Any]:
            quiet = [need(by_index[i]) for i in month_ends
                     if date(2012, 1, 1) <= ledger.sessions[i] <= date(2016, 12, 31)]
            if len(quiet) < 55:
                raise ValueError("quiet window is incomplete")
            return _gate(float(np.median(quiet)) <= 15, round(float(np.median(quiet)), 1))

        gates["G4"] = guarded(g4)
        p95 = v7.percentile(placebo_heat, 95)
        gates["G5"] = _gate(real_heat is not None and real_heat > p95, None if real_heat is None else round(real_heat, 3),
                            placebo_p95=round(p95, 3), placebo_median=round(v7.percentile(placebo_heat, 50), 3),
                            placebo_runs=len(placebo_heat), note=placebo_note)
        controls = {k: bool(scores[k].get("would_qualify")) for k in panel.controls}
        gates["G6"] = _gate(not any(controls.values()), controls)

        def g7() -> dict[str, Any]:
            anchor = v7.standardisation(ledger, "speed_d200")
            if anchor is None:
                raise ValueError("no standardisation for the nasdaq_only benchmark")
            bench_spec = {"weights": {"speed_d200": 100.0}, "signs": {"speed_d200": 1.0}, "anchors": {"speed_d200": anchor}}
            rows, usable = [], []
            for label, fit_end, test_start, test_end in FOLDS:
                fit = v7.build_spec(panel, ledger, contract, v7.Options(train_end=fit_end))["lines"]["heat"]
                end = test_end or as_of
                rho, n = v7.window_association(panel, fit, test_start, end)
                bench, bench_n = v7.window_association(panel, bench_spec, test_start, end)
                rows.append({"fold": label, "rho": None if rho is None else round(rho, 3), "n": n,
                             "nasdaq_only": None if bench is None else round(bench, 3), "nasdaq_only_n": bench_n,
                             "indicators": 0 if fit is None else len(fit["weights"])})
                if rho is not None and bench is not None:
                    usable.append((rho, n, bench, bench_n))
            mean = sum(r * n for r, n, _, _ in usable) / sum(n for _, n, _, _ in usable) if usable else None
            bench_mean = sum(b * m for _, _, b, m in usable) / sum(m for _, _, _, m in usable) if usable else None
            passed = len(usable) >= 3 and mean is not None and mean >= 0.10 and mean >= bench_mean - 0.05
            return _gate(passed, None if mean is None else round(mean, 3), folds=rows, computable=len(usable),
                         nasdaq_only_mean=None if bench_mean is None else round(bench_mean, 3))

        gates["G7"] = guarded(g7)

        def g8() -> dict[str, Any]:
            steps = []
            for (_, h0, p0), (i1, h1, p1) in zip(history, history[1:]):
                if ledger.sessions[i1] < date(2023, 1, 1) or p0 == p1:
                    continue
                steps.append((abs(need(h1) - need(h0)), ledger.sessions[i1].isoformat()))
            if not steps:
                raise ValueError("no release day found since 2023-01")
            worst = max(steps)
            return _gate(worst[0] <= 5, [round(worst[0], 1), worst[1]], release_days=len(steps))

        gates["G8"] = guarded(g8)

        def g9() -> dict[str, Any]:
            out = {}
            for label, spec, clamp in (("clamped", heat, True), ("unclamped", variant_specs.get("no_clamp"), False)):
                now = need(v7.heat_today(ledger, spec, index=today, clamp=clamp))
                out[label] = [round(abs(need(v7.heat_today(ledger, spec, index=today, clamp=clamp,
                                                           close=float(ledger.close[today]) * f)) - now), 1)
                              for f in (1.1, 0.9)]
            return _gate(max(max(v) for v in out.values()) <= 10, out)

        gates["G9"] = guarded(g9)
        detail = v7.composite(ledger, today, heat, detail=True)
        clamped = sum(w for k, w in heat["weights"].items()
                      if k in detail["rows"] and abs(detail["rows"][k]["z_raw"]) > 10.0)
        gates["G10"] = _gate(detail["value"] is not None and clamped <= 25, round(clamped, 1))

        def g11() -> dict[str, Any]:
            idx = [i for i in month_ends if ledger.sessions[i] >= date(2010, 1, 1)]
            dh = np.array([need(by_index[b]) - need(by_index[a]) for a, b in zip(idx, idx[1:])])
            dn = np.array([np.log(ledger.close[b] / ledger.close[a]) for a, b in zip(idx, idx[1:])])
            r2 = float(np.corrcoef(dh, dn)[0, 1] ** 2)
            last36 = [need(by_index[i]) for i in month_ends[-36:]]
            spread = max(last36) - min(last36)
            return _gate(r2 <= 0.70 and spread >= 10, {"r2": round(r2, 3), "range_36m": round(spread, 1)})

        gates["G11"] = guarded(g11)
        computed = {k: v for k, v in band.items() if v is not None}
        missing = sorted(k for k, v in band.items() if v is None)
        width = max(computed.values()) - min(computed.values()) if computed else None
        gates["G12"] = _gate(width is not None and width <= 35 and len(missing) < 2 and band["base"] is not None,
                             None if width is None else round(width, 1),
                             lo=None if not computed else [min(computed, key=computed.get), round(min(computed.values()), 1)],
                             hi=None if not computed else [max(computed, key=computed.get), round(max(computed.values()), 1)],
                             uncomputable=missing)

    pressure_gates["Q1"] = _gate(pressure is not None, None if pressure is None else len(pressure["weights"]))
    if pressure is None:
        pressure_gates["Q2"] = {"passed": False, "value": None, "reason": "no pressure line"}
    else:
        p90 = v7.percentile(placebo_pressure, 90)
        pressure_gates["Q2"] = _gate(real_pressure is not None and real_pressure > p90,
                                     None if real_pressure is None else round(real_pressure, 3),
                                     placebo_p90=round(p90, 3), placebo_runs=len(placebo_pressure), note=placebo_note)

    # ── 공시(게이트 아님) ──
    def assoc(spec: Any, start: date, end: date) -> Any:
        rho, n = v7.window_association(panel, spec, start, end)
        return {"rho": None if rho is None else round(rho, 3), "n": n}

    def noise(row: dict[str, Any]) -> float | None:
        if row.get("placebo90") is None or row.get("placebo_median") is None:
            return None
        return float(row["placebo90"]) - float(row["placebo_median"])

    families: dict[str, dict[str, Any]] = {}
    for key, row in scores.items():
        if row["group"] == "control":
            continue
        entry = families.setdefault(row["family"], {"group": row["group"], "candidates": 0, "eligible": 0,
                                                    "best": None, "best_score": -1.0, "best_noise": None, "weight": 0.0})
        entry["candidates"] += 1
        entry["eligible"] += bool(row.get("eligible"))
        entry["weight"] = round(entry["weight"] + float(row.get("weight") or 0.0), 2)
        if row["E"] > entry["best_score"]:
            entry["best"], entry["best_score"], entry["best_noise"] = key, row["E"], noise(row)
    names = sorted(families, key=lambda f: -families[f]["best_score"])
    indistinct = []
    for a_i, a in enumerate(names):
        for b in names[a_i + 1:]:
            na, nb = families[a]["best_noise"], families[b]["best_noise"]
            if na is None or nb is None:
                continue
            gap = families[a]["best_score"] - families[b]["best_score"]
            if gap < (na + nb) / 2.0:
                indistinct.append([a, b, round(gap, 1)])
    h_at = {}
    for label in ("2000-03-10", "2007-10-31", "2020-02-19", "2021-11-19", as_of.isoformat()):
        value = by_index.get(ledger.session_index(date.fromisoformat(label))) if heat is not None else None
        h_at[label] = None if value is None else round(value, 1)
    reported = {
        "in_sample_association": {"heat": None if real_heat is None else round(real_heat, 3),
                                  "pressure": None if real_pressure is None else round(real_pressure, 3)},
        "holdout": assoc(heat, date(2020, 1, 1), as_of),
        "holdout_equal_weights": assoc(variant_specs.get("equal_weights"), date(2020, 1, 1), as_of),
        "h_at": h_at, "families": families, "family_pairs_not_distinguishable": indistinct,
        "episodes": [{"peak": e["peak"].isoformat(), "trigger": e["trigger"].isoformat(), "low": e["low"].isoformat(),
                      "in_train": windows.segment_end(e["peak"]) is not None} for e in panel.episodes],
        "train_near_high_months": n_train,
        "chance_note": "위약 문턱이 90 백분위이므로 영향이 없는 후보도 10개 중 1개꼴로 그 관문을 넘는다",
    }
    all_gates = heat is not None and all(g["passed"] for g in gates.values()) and all(c["passed"] for c in checks.values())
    pressure_ok = pressure is not None and all(g["passed"] for g in pressure_gates.values())
    pressure_q = None
    if pressure is not None:
        pressure_q = v7.percentile_of(v7.composite(ledger, today, pressure)["value"], pressure["scale"]["grid"])
    return {
        "contract_id": contract["contract_id"], "contract_version": contract["version"],
        "rules_fixed_at": contract["rules_fixed_at"], "rules_sha256": v7.rules_digest(contract),
        "gate_as_of": as_of.isoformat(),
        "inputs_sha256": json.loads((root / v7.INPUTS_RELATIVE).read_text(encoding="utf-8"))["sha256"],
        "ritter_raw_sha256": v7.ritter_fingerprint(root),
        "scores": scores, "heat": line_record(heat), "pressure": line_record(pressure),
        "heat_grid": None if heat is None else heat["scale"]["grid"],
        "pressure_grid": None if pressure is None else pressure["scale"]["grid"],
        "construction_checks": checks, "gates": gates, "pressure_gates": pressure_gates,
        "verdict": "passed" if all_gates else "failed",
        "failed_gates": [k for k, g in {**gates, **checks}.items() if not g["passed"]],
        "pressure_displayable": pressure_ok,
        "measurement_band": {k: (None if v is None else round(v, 1)) for k, v in band.items()},
        "family_band": {k: (None if v is None else round(v, 1)) for k, v in family_band.items()},
        "family_variants": family_variants, "pressure_today": None if pressure_q is None else round(pressure_q, 1),
        "reported": reported,
    }


def frozen_block(report: dict[str, Any], stamp: str) -> dict[str, Any]:
    heat, pressure = report["heat"], report["pressure"]
    if heat is not None:
        heat = {**heat, "grid": report["heat_grid"]}
    if pressure is not None:
        pressure = {**pressure, "grid": report["pressure_grid"], "displayable": report["pressure_displayable"]}
    band = {k: v for k, v in report["measurement_band"].items() if v is not None}
    return {
        "frozen_at": stamp, "gate_as_of": report["gate_as_of"], "inputs_sha256": report["inputs_sha256"],
        "ritter_raw_sha256": report["ritter_raw_sha256"], "rules_sha256": report["rules_sha256"],
        "verdict": report["verdict"], "failed_gates": report["failed_gates"],
        "gates": {k: {"passed": g["passed"], "value": g.get("value")} for k, g in report["gates"].items()},
        "construction_checks": {k: {"passed": g["passed"], "value": g.get("value")}
                                for k, g in report["construction_checks"].items()},
        "pressure_gates": {k: {"passed": g["passed"], "value": g.get("value")} for k, g in report["pressure_gates"].items()},
        "scores": {k: {f: row.get(f) for f in ("group", "family", "sign", "rank", "E", "E_core", "placebo90", "P1", "P2",
                                              "P3", "P4", "rho12", "rho24", "n", "status", "reason", "weight")}
                   for k, row in report["scores"].items()},
        "heat": heat, "pressure": pressure, "family_variants": report["family_variants"],
        "measurement_band_today": None if not band else {"lo": int(round(min(band.values()))),
                                                          "hi": int(round(max(band.values())))},
        "episodes": report["reported"]["episodes"],
    }


def write_frozen(path: Path, block: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    cut = text.rfind(FROZEN_MARKER)
    if cut < 0:
        raise ToolError(f"{path}: no trailing 'frozen:' block to fill")
    tail = yaml.safe_load(text[cut:])
    if not isinstance(tail, dict) or list(tail) != ["frozen"] or tail["frozen"]:
        raise ToolError(f"{path}: frozen block is not empty — a re-run needs a new contract revision")
    body = yaml.safe_dump({"frozen": json.loads(json.dumps(block, default=str))}, allow_unicode=True,
                          sort_keys=False, width=110)
    scratch = path.with_suffix(path.suffix + ".tmp")
    scratch.write_bytes((text[:cut].rstrip("\n") + "\n\n" + body).encode("utf-8"))
    os.replace(scratch, path)


def _mark(passed: Any) -> str:
    return "통과" if passed else "실패"


def markdown(report: dict[str, Any], contract: dict[str, Any]) -> str:
    labels = {row["id"]: row["label"] for row in contract["candidates"]}
    rules = {g["id"]: g["rule"] for g in [*contract["gates"], *contract["pressure_gates"], *contract["construction_checks"]]}
    scores = report["scores"]
    lines = [
        "# 닷컴 대비 과열도 v7 — 영향도 점수제 측정",
        "",
        f"- 계약 판 `{report['contract_version']}` · 규칙 고정 {report['rules_fixed_at']} · 실행 전 수정 "
        f"{contract.get('rules_amended_before_run_at')} · 판정 기준일 {report['gate_as_of']}",
        f"- 입력 지문 `{report['inputs_sha256'][:16]}…` · 규칙 지문 `{report['rules_sha256'][:16]}…`",
        f"- **과열도 줄 판정: {'통과' if report['verdict'] == 'passed' else '탈락'}**"
        + ("" if not report["failed_gates"] else f" — 실패 {', '.join(report['failed_gates'])}"),
        f"- 긴축 압력 줄: {'표시 가능' if report['pressure_displayable'] else '표시 불가'}",
        f"- 동결 블록과 이번 재현 일치: {report.get('matches_frozen')}",
        f"- 기록 정오: 계약 `errata` {len(contract.get('errata') or [])}건(G6 는 실제로는 충족, 측정 범위 값은 변형 3개에서만 나온 것, "
        "'우연 문턱 통과 11개'와 '자격 충족 6개'의 구분 등)",
        "",
        "참고 지표다. 확률이 아니며 매매 신호가 아니다. 가중은 과거 자료(1973~2017, 닷컴 1997~2002 제외)에 맞춘 표본 내 점수다.",
        f"{report['reported']['chance_note']}.",
        "",
        "## 순위표 (전 후보)",
        "",
        "| 순위 | 지표 | 줄 | 부문 | 점수 E | 순위상관 12/24개월 | P1 | P2 | P3 | P4 | 위약 90% | 상태 | 가중 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, row in sorted(scores.items(), key=lambda kv: (kv[1].get("rank") is None, kv[1].get("rank") or 0)):
        name = labels.get(key, key)
        if row.get("status") in {"dropped", "not_scoreable"}:
            lines.append(f"| — | {name} | {row['group']} | {row['family']} | — | — | — | — | — | — | — | "
                         f"채점 불가({row.get('reason')}) | — |")
            continue
        p3 = "미채점" if row.get("P3") is None else f"{row['P3']:.0f}"
        state = "편입" if row.get("eligible") else ("대조군" + ("(통과 — 규칙 실패)" if row.get("would_qualify") else "")
                                                   if row["group"] == "control" else f"참고 — {row.get('reason')}")
        weight = f"{row['weight']:.1f}" if row.get("weight") else "—"
        lines.append(f"| {row.get('rank')} | {name} | {row['group']} | {row['family']} | {row['E']:.1f} | "
                     f"{row['rho12']} / {row['rho24']} | {row['P1']:.0f} | {row['P2']:.0f} | {p3} | {row['P4']:.0f} | "
                     f"{row['placebo90']} (실제 {row['E_core']:.1f}) | {state} | {weight} |")
    lines += ["", "## 부문별 영향도", "", "| 부문 | 줄 | 후보 | 편입 | 최고점 지표 | 최고점 | 부문 가중 |", "|---|---|---|---|---|---|---|"]
    for family, row in sorted(report["reported"]["families"].items(), key=lambda kv: -kv[1]["best_score"]):
        lines.append(f"| {family} | {row['group']} | {row['candidates']} | {row['eligible']} | "
                     f"{labels.get(row['best'], row['best'])} | {row['best_score']:.1f} | {row['weight']:.1f} |")
    pairs = report["reported"]["family_pairs_not_distinguishable"]
    lines += ["", "최고점 차이가 위약 분포 폭보다 작아 순위를 구분할 수 없는 부문 쌍: "
              + (", ".join(f"{a} ↔ {b}(차이 {gap})" for a, b, gap in pairs) if pairs else "없음")]
    lines += ["", "## 구성 확인 (정의상 성립 — 검증이 아니다)", "", "| 항목 | 규칙 | 값 | 결과 |", "|---|---|---|---|"]
    for key, row in report["construction_checks"].items():
        lines.append(f"| {key} | {rules.get(key, '')} | {row.get('value')} | {_mark(row['passed'])} |")
    lines += ["", "## 게이트 (과열도 줄)", "", "| 게이트 | 규칙 | 값 | 결과 |", "|---|---|---|---|"]
    for key, row in report["gates"].items():
        extra = {k: v for k, v in row.items() if k not in {"passed", "value", "folds", "note"}}
        lines.append(f"| {key} | {str(rules.get(key, '')).replace('|', '/')} | {row.get('value')}"
                     f"{' · ' + json.dumps(extra, ensure_ascii=False) if extra else ''} | {_mark(row['passed'])} |")
    if "folds" in report["gates"].get("G7", {}):
        lines += ["", "걷기 전진 접힘: " + "; ".join(
            f"{f['fold']} = {f['rho']} (n {f['n']}, NASDAQ 단독 {f['nasdaq_only']}, 지표 {f['indicators']}개)"
            for f in report["gates"]["G7"]["folds"])]
    lines += ["", "## 게이트 (긴축 압력 줄)", "", "| 게이트 | 규칙 | 값 | 결과 |", "|---|---|---|---|"]
    for key, row in report["pressure_gates"].items():
        extra = {k: v for k, v in row.items() if k not in {"passed", "value", "note"}}
        lines.append(f"| {key} | {rules.get(key, '')} | {row.get('value')}"
                     f"{' · ' + json.dumps(extra, ensure_ascii=False) if extra else ''} | {_mark(row['passed'])} |")
    lines += ["", "## 기준일의 값", "",
              "- 측정 범위(점수 규칙의 대안들): " + ", ".join(f"{k} {v}" for k, v in report["measurement_band"].items()),
              "- 부문 제외 범위(게이트 아님, 화면에 함께 싣는다): " + ", ".join(f"{k} 제외 {v}" for k, v in report["family_band"].items()),
              f"- 긴축 압력 백분위: {report['pressure_today']}",
              "- 주요 시점의 과열도: " + ", ".join(f"{k} {v}" for k, v in report["reported"]["h_at"].items()),
              f"- 표본 내 상관(가중을 같은 표본에서 골랐다 — 게이트 아님): {report['reported']['in_sample_association']}",
              f"- holdout(2020~) 상관: {report['reported']['holdout']} · 동일 가중: {report['reported']['holdout_equal_weights']}",
              f"- train 고점 부근 월말 표본: {report['reported']['train_near_high_months']}개월",
              "", "## 규칙이 찾은 하락장", "", "| 고점일 | 25% 확인일 | 저점일 | train |", "|---|---|---|---|"]
    lines += [f"| {e['peak']} | {e['trigger']} | {e['low']} | {'예' if e['in_train'] else '—'} |"
              for e in report["reported"]["episodes"]]
    return "\n".join(lines) + "\n"


def compare_with_frozen(report: dict[str, Any], frozen: dict[str, Any]) -> dict[str, bool]:
    def weights(line: Any) -> Any:
        return None if not line else {k: round(float(v), 4) for k, v in line["weights"].items()}

    return {
        "verdict": frozen.get("verdict") == report["verdict"],
        "failed_gates": frozen.get("failed_gates") == report["failed_gates"],
        "heat_weights": weights(frozen.get("heat")) == weights(report["heat"]),
        "pressure_weights": weights(frozen.get("pressure")) == weights(report["pressure"]),
        "scores": all(abs(float(frozen["scores"][k]["E"]) - float(row["E"])) < 0.01 for k, row in report["scores"].items()
                      if k in frozen.get("scores", {})),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default=None, help="docs/audit/overheat_v7*.md (a .json twin is written beside it)")
    parser.add_argument("--write-frozen", action="store_true", help="the single official run: fill the EMPTY frozen block")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract = v7.load_contract(root)
    frozen = contract.get("frozen") or {}
    if args.write_frozen and frozen:
        raise ToolError("frozen block already holds a verdict — a re-run needs a new contract revision")
    if not frozen and not args.write_frozen:
        raise ToolError("the frozen block is empty: the only allowed run is the official one (--write-frozen)")
    out = None
    if args.report:
        out = (root / args.report).resolve()
        if out.parent != (root / REPORT_DIR).resolve() or out.suffix != ".md" or not out.name.startswith("overheat_v7"):
            raise ToolError(f"--report must be {REPORT_DIR.as_posix()}/overheat_v7*.md")
    report = run(root)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["generated_at"] = stamp
    if args.write_frozen:
        write_frozen(root / v7.CONTRACT_RELATIVE, frozen_block(report, stamp))
        report["matches_frozen"] = "official run"
    else:
        report["matches_frozen"] = compare_with_frozen(report, frozen)
    if out:
        out.write_text(markdown(report, contract), encoding="utf-8", newline="\n")
        out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
                                            encoding="utf-8", newline="\n")
    summary = {"verdict": report["verdict"], "failed": report["failed_gates"],
               "heat_today": report["measurement_band"].get("base"), "pressure_displayable": report["pressure_displayable"],
               "matches_frozen": report["matches_frozen"]}
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
