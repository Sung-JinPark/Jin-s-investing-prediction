"""Deterministic Excel audit view of the authoritative append-only data store.

The workbook is a review/export boundary, never the canonical database.  Values
come exclusively from the committed source catalog, raw-receipt ledger, normalized
observation ledger, chart lineage, and research-candidate evidence registry.
"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape


WORKBOOK_RELATIVE = Path("data/statistics/workbooks/official_data_latest.xlsx")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(reference: str, value: Any, *, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{reference}"{style_attr}/>'
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"{style_attr}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}"{style_attr}><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{reference}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _sheet_xml(
    rows: Iterable[Iterable[Any]], *, widths: list[float], freeze_header: bool = True,
) -> str:
    materialized = [list(row) for row in rows]
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    xml_rows: list[str] = []
    for row_index, row in enumerate(materialized, start=1):
        cells = "".join(
            _cell(f"{_column_name(column_index)}{row_index}", value, style=1 if row_index == 1 else 0)
            for column_index, value in enumerate(row, start=1)
        )
        xml_rows.append(f'<row r="{row_index}"{(" ht=\"26\" customHeight=\"1\"" if row_index == 1 else "")}>{cells}</row>')
    pane = (
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        if freeze_header else '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    )
    last_column = _column_name(max((len(row) for row in materialized), default=1))
    last_row = max(len(materialized), 1)
    auto_filter = f'<autoFilter ref="A1:{last_column}{last_row}"/>' if freeze_header else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'{pane}<cols>{columns}</cols><sheetData>{"".join(xml_rows)}</sheetData>{auto_filter}'
        '</worksheet>'
    )


def _workbook_parts(sheet_names: list[str]) -> dict[str, str]:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    relationships = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(sheet_names) + 1)
    ) + (
        f'<Relationship Id="rId{len(sheet_names) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(sheet_names) + 1)
    )
    return {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f'{overrides}</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{sheets}</sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{relationships}</Relationships>'
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="10"/><name val="Aptos"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF14213D"/>'
            '<bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
            '</styleSheet>'
        ),
    }


def _quality_gate_rows(
    root: Path,
    *,
    statistics: dict[str, Any],
    observations: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    scenario: dict[str, Any],
) -> list[list[Any]]:
    """Calculate workbook gate states from the committed evidence, never labels."""
    from .authoritative_statistics import (
        RawArtifactReceipt,
        RawReceiptCorrection,
        load_authoritative_source_policy,
        verify_raw_artifact_receipt,
    )
    from .statistics_lab import validate_statistics_lab

    validate_statistics_lab(statistics)
    policy_path = root / "data/contracts/authoritative_statistics_sources.yaml"
    if not policy_path.is_file():
        policy_path = (
            Path(__file__).resolve().parents[2]
            / "data/contracts/authoritative_statistics_sources.yaml"
        )
    policy = load_authoritative_source_policy(policy_path)
    receipt_models = [RawArtifactReceipt.model_validate(
        {**row, "series_ids": tuple(row.get("series_ids") or [])}, strict=True,
    ) for row in receipts]
    correction_models = [
        RawReceiptCorrection.model_validate(row, strict=True) for row in corrections
    ]
    receipt_by_id = {receipt.receipt_id: receipt for receipt in receipt_models}
    corrected = {
        correction.supersedes_receipt_id: correction.replacement_receipt_id
        for correction in correction_models
    }
    receipt_keys: dict[tuple[str, str, str], RawArtifactReceipt] = {}
    raw_errors: list[str] = []
    store = root / "data/statistics/official_store"
    for receipt in receipt_models:
        try:
            verify_raw_artifact_receipt(store, policy, receipt)
        except Exception as exc:  # gate output keeps the exact failing receipt auditable
            raw_errors.append(f"{receipt.receipt_id}:{type(exc).__name__}")
            continue
        receipt_keys[(receipt.source_id, receipt.raw_sha256, receipt.fetched_at)] = receipt
    correction_errors = [
        correction.correction_id
        for correction in correction_models
        if correction.supersedes_receipt_id not in receipt_by_id
        or correction.replacement_receipt_id not in receipt_by_id
        or receipt_by_id[correction.supersedes_receipt_id].source_id
        != receipt_by_id[correction.replacement_receipt_id].source_id
        or receipt_by_id[correction.supersedes_receipt_id].raw_sha256
        != receipt_by_id[correction.replacement_receipt_id].raw_sha256
    ]
    orphan_observations: list[dict[str, Any]] = []
    series_mismatches: list[str] = []
    for row in observations:
        receipt = receipt_keys.get((
            str(row.get("source_id")), str(row.get("raw_sha256")),
            str(row.get("fetched_at")),
        ))
        if receipt is None:
            orphan_observations.append(row)
            continue
        effective = receipt_by_id.get(corrected.get(receipt.receipt_id, receipt.receipt_id))
        if effective is None or (
            effective.series_ids and str(row.get("series_id")) not in effective.series_ids
        ):
            series_mismatches.append(str(row.get("observation_id")))
    statistics_authority = all(
        source.get("numeric_input_allowed") is True for source in statistics["sources"]
    ) and all(
        not chart.get("research_context_source_ids") for chart in statistics["charts"]
    )
    blocked_report_ids = {
        "kiplinger_jobs_consensus_and_commentary",
        "fed_rate_distribution_pre_post",
        "post_jobs_cross_asset_state",
    }
    report_separation = all(
        evidence.get("used_numerically") is False
        for evidence in scenario.get("evidence_registry") or []
        if evidence.get("evidence_id") in blocked_report_ids
    )
    scenario_unapproved = [
        evidence.get("evidence_id")
        for evidence in scenario.get("evidence_registry") or []
        if evidence.get("used_numerically") is True
        and evidence.get("authority_class") not in {
            "official_government", "official_central_bank", "official_regulator",
            "official_sro", "official_exchange",
        }
    ]
    return [
        ["gate", "status", "evidence"],
        [
            "STATISTICS_SOURCE_AUTHORITY",
            "PASS" if statistics_authority else "FAIL",
            f"{len(statistics['sources'])} registered sources / {len(statistics['charts'])} charts",
        ],
        [
            "SCENARIO_SOURCE_AUTHORITY",
            "HOLD" if scenario_unapproved else "PASS",
            "research candidate holds: " + ", ".join(str(item) for item in scenario_unapproved),
        ],
        [
            "RAW_BEFORE_DERIVE",
            "PASS" if not raw_errors and not correction_errors and not orphan_observations and not series_mismatches else "FAIL",
            f"{len(receipts)} receipts; corrections={len(corrections)}; raw_errors={len(raw_errors)}; correction_errors={len(correction_errors)}; orphan_rows={len(orphan_observations)}; series_mismatches={len(series_mismatches)}",
        ],
        [
            "NORMALIZED_LEDGER",
            "PASS" if observations and not orphan_observations and not series_mismatches else "FAIL",
            f"{len(observations)} append-only rows",
        ],
        [
            "REPORT_NUMERIC_SEPARATION",
            "PASS" if report_separation else "FAIL",
            "report/media values are blocked from the candidate numeric adjustment",
        ],
        ["PIT_MODEL_USE", "HOLD", "current-release histories are not historical PIT inputs"],
        ["OFFICIAL_FORECAST", "UNCHANGED", "official snapshot and ledger were not modified"],
    ]


def export_official_data_workbook(root: Path) -> tuple[Path, dict[str, int]]:
    statistics = json.loads(
        (root / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8")
    )
    store = root / "data/statistics/official_store/ledgers"
    observations = _jsonl(store / "normalized_observations.jsonl")
    receipts = _jsonl(store / "raw_receipts.jsonl")
    corrections = _jsonl(store / "raw_receipt_corrections.jsonl")
    from .authoritative_statistics import read_normalized_observations
    validated_observations = [
        item.ledger_row()
        for item in read_normalized_observations(root / "data/statistics/official_store")
    ]
    if observations != validated_observations:
        raise ValueError("normalized observation ledger failed exact model reconciliation")
    scenario = json.loads(
        (root / "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json")
        .read_text(encoding="utf-8")
    )
    rows: dict[str, tuple[list[list[Any]], list[float]]] = {}
    rows["README"] = ([
        ["AI INVESTING OFFICIAL DATA LEDGER", "value"],
        ["generated_at", statistics["generated_at"]],
        ["latest_observation", statistics["as_of"]],
        ["authoritative_series", len(statistics["sources"])],
        ["normalized_observations", len(observations)],
        ["raw_receipts", len(receipts)],
        ["receipt_corrections", len(corrections)],
        ["published_charts", len(statistics["charts"])],
        ["canonical_store", "append-only JSONL; workbook is review-only"],
        ["research_reports", "insight-only; numeric input denied"],
        ["scenario_status", f"{scenario['status']} · {scenario['promotion_state']}"],
    ], [34, 90])
    source_headers = [
        "series_id", "title", "provider", "unit", "frequency", "latest_observation",
        "row_count", "authority_class", "policy_source_id", "numeric_allowed", "raw_sha256",
    ]
    rows["SourceCatalog"] = ([source_headers, *[[
        item.get("series_id"), item.get("title"), item.get("provider"), item.get("unit"),
        item.get("native_frequency"), item.get("latest_observation"), item.get("row_count"),
        item.get("authority_class"), item.get("policy_source_id"),
        item.get("numeric_input_allowed"), item.get("raw_sha256"),
    ] for item in statistics["sources"]]], [20, 38, 44, 22, 18, 18, 12, 30, 24, 16, 68])
    observation_headers = [
        "observation_id", "source_id", "series_id", "observation_date", "vintage_date",
        "revision_seq", "available_at", "fetched_at", "raw_value", "value", "raw_unit",
        "unit", "semantic_type", "transformation_id", "parser_version", "raw_sha256",
        "supersedes_observation_id",
    ]
    rows["Observations"] = ([observation_headers, *[[item.get(key) for key in observation_headers]
        for item in observations]], [22, 24, 28, 16, 15, 12, 26, 26, 16, 16, 22, 22, 18, 20, 22, 68, 68])
    corrected_by_id = {
        str(item["supersedes_receipt_id"]): str(item["replacement_receipt_id"])
        for item in corrections
    }
    receipt_headers = [
        "receipt_id", "source_id", "series_ids", "source_uri", "http_status", "media_type",
        "byte_count", "raw_sha256", "artifact_path", "fetched_at", "status", "replacement_receipt_id",
    ]
    rows["RawReceipts"] = ([receipt_headers, *[[
        item.get("receipt_id"), item.get("source_id"), " | ".join(item.get("series_ids") or []),
        item.get("source_uri"), item.get("http_status"), item.get("media_type"),
        item.get("byte_count"), item.get("raw_sha256"), item.get("artifact_path"),
        item.get("fetched_at"),
        "superseded" if item.get("receipt_id") in corrected_by_id else "active",
        corrected_by_id.get(str(item.get("receipt_id"))),
    ] for item in receipts]], [22, 24, 36, 65, 12, 30, 14, 68, 50, 26, 14, 68])
    correction_headers = [
        "correction_id", "supersedes_receipt_id", "replacement_receipt_id",
        "reason", "corrected_at",
    ]
    rows["ReceiptCorrections"] = ([correction_headers, *[[
        item.get("correction_id"), item.get("supersedes_receipt_id"),
        item.get("replacement_receipt_id"), item.get("reason"), item.get("corrected_at"),
    ] for item in corrections]], [68, 68, 68, 74, 26])
    chart_headers = [
        "chart_id", "title", "category", "unit", "metric_source_ids",
        "research_numeric_sources", "scope", "conclusion",
    ]
    rows["ChartLineage"] = ([chart_headers, *[[
        item.get("id"), item.get("title"), item.get("category"), item.get("unit"),
        " | ".join(item.get("metric_source_ids") or item.get("source_ids") or []),
        " | ".join(item.get("research_context_source_ids") or []), item.get("scope_note"),
        item.get("conclusion"),
    ] for item in statistics["charts"]]], [32, 36, 16, 24, 52, 24, 32, 90])
    evidence_headers = [
        "evidence_id", "authority_class", "used_numerically", "effective_strength",
        "role", "available_at", "source_path",
    ]
    rows["ScenarioLineage"] = ([evidence_headers, *[[item.get(key) for key in evidence_headers]
        for item in scenario.get("evidence_registry") or []]], [34, 28, 18, 18, 58, 26, 64])
    rows["QualityGates"] = (_quality_gate_rows(
        root,
        statistics=statistics,
        observations=observations,
        receipts=receipts,
        corrections=corrections,
        scenario=scenario,
    ), [34, 18, 90])

    sheet_names = list(rows)
    parts = _workbook_parts(sheet_names)
    for index, name in enumerate(sheet_names, start=1):
        values, widths = rows[name]
        parts[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(
            values, widths=widths, freeze_header=name != "README",
        )
    target = root / WORKBOOK_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".xlsx.tmp")
    generated = datetime.fromisoformat(str(statistics["generated_at"]).replace("Z", "+00:00"))
    zip_time = generated.astimezone(timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=zip_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body.encode("utf-8"))
    os.replace(temporary, target)
    return target, {
        "sources": len(statistics["sources"]), "observations": len(observations),
        "receipts": len(receipts), "charts": len(statistics["charts"]),
    }
