import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:([A-Za-z]):)/, "$1:")), "..");
const inputPath = path.join(root, "outputs", "timeseries_v6", "audit", "workbook_input.json");
const outputDir = path.dirname(inputPath);
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));

const workbook = Workbook.create();
const navy = "#11233F";
const blue = "#1D4ED8";
const pale = "#E8EEF7";
const green = "#0F766E";
const red = "#B91C1C";
const gray = "#64748B";

function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function title(sheet, titleText, subtitle, columns) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, 1, columns).merge();
  sheet.getRangeByIndexes(0, 0, 1, columns).values = [[titleText]];
  sheet.getRangeByIndexes(0, 0, 1, columns).format = {
    fill: navy,
    font: { bold: true, color: "#FFFFFF", size: 16 },
    rowHeight: 30,
    verticalAlignment: "center",
  };
  sheet.getRangeByIndexes(1, 0, 1, columns).merge();
  sheet.getRangeByIndexes(1, 0, 1, columns).values = [[subtitle]];
  sheet.getRangeByIndexes(1, 0, 1, columns).format = {
    fill: "#F8FAFC",
    font: { color: gray, italic: true, size: 10 },
    wrapText: true,
    rowHeight: 30,
  };
}

function table(sheet, headers, rows, { startRow = 3, widths = [] } = {}) {
  const columns = headers.length;
  const header = sheet.getRangeByIndexes(startRow - 1, 0, 1, columns);
  header.values = [headers];
  header.format = {
    fill: pale,
    font: { bold: true, color: navy },
    borders: { bottom: { style: "medium", color: navy } },
    rowHeight: 24,
    wrapText: true,
  };
  if (rows.length) {
    const body = sheet.getRangeByIndexes(startRow, 0, rows.length, columns);
    body.values = rows.map((row) => row.map(text));
    body.format = {
      font: { color: "#111827", size: 9 },
      borders: { insideHorizontal: { style: "thin", color: "#E2E8F0" } },
      verticalAlignment: "top",
    };
  }
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, Math.max(rows.length + startRow, 4), 1).format.columnWidth = width;
  });
  sheet.freezePanes.freezeRows(startRow);
}

const sources = workbook.worksheets.add("Sources");
title(sources, "V6 Source Ledger", "Immutable public archive receipts. Reconstructed archives are not described as native PIT.", 6);
table(sources, ["Source ID", "Series", "Data grade", "Rows", "Receipt ID", "Raw SHA-256"], data.sources.map((row) => [row.source_id, row.series_id, row.data_grade, row.row_count, row.receipt_id, row.raw_sha256]), { widths: [20, 16, 30, 12, 31, 66] });
sources.getRange(`D4:D${3 + data.sources.length}`).format.numberFormat = "#,##0";

const observations = workbook.worksheets.add("Observations");
title(observations, "Observation Partitions", "Parquet partitions and observation-version reconciliation; full rows remain in the immutable store.", 7);
table(observations, ["Source ID", "Series", "Rows", "First observation", "Last observation", "Unique versions", "Parquet SHA-256"], data.observations.map((row) => [row.source_id, row.series_id, row.row_count, row.first_observation, row.last_observation, row.unique_observation_versions, row.parquet_sha256]), { widths: [20, 16, 12, 25, 25, 15, 66] });
observations.getRange(`C4:C${3 + data.observations.length}`).format.numberFormat = "#,##0";
observations.getRange(`F4:F${3 + data.observations.length}`).format.numberFormat = "#,##0";
observations.getRange(`D4:E${3 + data.observations.length}`).format.numberFormat = "yyyy-mm-dd";

const vintages = workbook.worksheets.add("Vintages");
title(vintages, "Vintage & Availability Audit", "Availability timestamps and data-grade labels used by the V6 PIT join.", 7);
table(vintages, ["Source ID", "Series", "Data grade", "First available", "Last available", "Collected at", "Native PIT"], data.vintages.map((row) => [row.source_id, row.series_id, row.data_grade, row.first_available_at, row.last_available_at, row.collected_at, row.native_pit]), { widths: [20, 16, 30, 25, 25, 25, 12] });
vintages.getRange(`D4:F${3 + data.vintages.length}`).format.numberFormat = "yyyy-mm-dd hh:mm";

const features = workbook.worksheets.add("Features");
title(features, "Feature Lineage", "Every active feature is tied to a source series and explicit data grade; missing history is surfaced by indicators.", 6);
table(features, ["Feature", "Source series", "Data grade", "Origins", "Missing", "Missing indicator"], data.features.map((row) => [row.feature_name, row.source_series_id, row.data_grade, row.origin_count, row.missing_count, row.missing_indicator]), { widths: [36, 18, 30, 12, 12, 18] });
features.getRange(`D4:E${3 + data.features.length}`).format.numberFormat = "#,##0";

const forecasts = workbook.worksheets.add("Forecasts");
title(forecasts, "Latest Sealed Research Origins", "Research outputs only. Customer numbers remain hidden whenever any Gate is HOLD.", 13);
table(forecasts, ["Origin", "Horizon", "Candidate", "Feature profile", "Actual", "p10", "p25", "p50", "p75", "p90", "Up probability", "Model CRPS", "Anchor CRPS"], data.forecasts.map((row) => [row.origin, row.horizon, row.candidate_id, row.feature_profile, row.actual, row.p10, row.p25, row.p50, row.p75, row.p90, row.up_probability, row.model_crps, row.baseline_crps]), { widths: [14, 10, 12, 28, 13, 13, 13, 13, 13, 13, 15, 15, 15] });
if (data.forecasts.length) {
  forecasts.getRange(`E4:J${3 + data.forecasts.length}`).format.numberFormat = "0.00%";
  forecasts.getRange(`K4:K${3 + data.forecasts.length}`).format.numberFormat = "0.0%";
  forecasts.getRange(`L4:M${3 + data.forecasts.length}`).format.numberFormat = "0.000000";
}

const backtest = workbook.worksheets.add("Backtest");
title(backtest, "Sealed Backtest Gate", "CRPS improvement and empirical interval coverage by direct forecast horizon.", 7);
table(backtest, ["Horizon", "Origins", "Model CRPS", "Anchor CRPS", "Improvement", "p10-p90 coverage", "p25-p75 coverage"], data.backtest.map((row) => [row.horizon, row.count, row.model_crps, row.baseline_crps, row.improvement, row.p10_p90_coverage, row.p25_p75_coverage]), { widths: [12, 12, 16, 16, 16, 18, 18] });
if (data.backtest.length) {
  backtest.getRange(`C4:D${3 + data.backtest.length}`).format.numberFormat = "0.000000";
  backtest.getRange(`E4:G${3 + data.backtest.length}`).format.numberFormat = "0.0%";
}

const modelCard = workbook.worksheets.add("ModelCard");
title(modelCard, "NASDAQ V6 Model Card", "Frozen research model; no official forecast, scenario, or trading probability is written.", 4);
const cardRows = [
  ["Model ID", data.model_card.model_id, "Registered identifier", ""],
  ["Probability space", data.model_card.probability_space, "Separate from all existing forecasts", ""],
  ["Status", data.model_card.status, "Research Gate result", ""],
  ["Numbers visible", data.model_card.numbers_visible, "Requires all three Gates", ""],
  ["Integrity Gate", data.model_card.integrity_pass, "Raw/receipt/PIT/runtime", ""],
  ["Research Gate", data.model_card.research_pass, "Frozen CRPS/coverage thresholds", ""],
  ["Operational Gate", data.model_card.operational_pass, "Freshness/snapshot compatibility", ""],
  ["Origin count", data.model_card.origin_count, "Weekly XNAS origins", ""],
  ["First origin", data.model_card.first_origin, "Initial-training segment included", ""],
  ["Last mature origin", data.model_card.last_mature_origin, "63-session label matured", ""],
  ["Dataset hash", data.model_card.dataset_hash, "Immutable input identity", ""],
  ["Research HOLD reasons", data.model_card.research_reasons.join(" | "), "No thresholds were weakened", ""],
];
table(modelCard, ["Field", "Value", "Audit meaning", "Check"], cardRows, { widths: [24, 68, 42, 12] });
modelCard.getRange("D4").formulas = [[`=IF(B7=FALSE,"OK","REVIEW")`]];
modelCard.getRange("D4:D15").format.font = { color: green, bold: true };

const runManifest = workbook.worksheets.add("RunManifest");
title(runManifest, "Run Manifest & Checks", "Content hashes for every material research artifact included in this audit view.", 4);
table(runManifest, ["Path", "Bytes", "SHA-256", "Check"], data.run_manifest.map((row, index) => [row.path, row.bytes, row.sha256, index === 0 ? "" : null]), { widths: [68, 14, 66, 14] });
if (data.run_manifest.length) {
  runManifest.getRange(`B4:B${3 + data.run_manifest.length}`).format.numberFormat = "#,##0";
  runManifest.getRange("D4").formulas = [[`=IF(COUNTA(C4:C${3 + data.run_manifest.length})=${data.run_manifest.length},"OK","HOLD")`]];
  runManifest.getRange("D4").format.font = { bold: true, color: green };
}

for (const sheetName of ["Sources", "Observations", "Vintages", "Features", "Forecasts", "Backtest", "ModelCard", "RunManifest"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const used = sheet.getUsedRange();
  used.format.wrapText = false;
  sheet.getRange("A1:Z2").format.wrapText = true;
}
modelCard.getRange("B15:C15").format.wrapText = true;
modelCard.getRange("A15:D15").format.rowHeight = 56;

const previewDir = path.join(outputDir, "workbook_previews");
await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of ["Sources", "Observations", "Vintages", "Features", "Forecasts", "Backtest", "ModelCard", "RunManifest"]) {
  const preview = await workbook.render({ sheetName, range: "A1:M30", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const inspect = await workbook.inspect({ kind: "table", range: "ModelCard!A1:D15", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 8 });
await fs.writeFile(path.join(outputDir, "workbook_inspect.ndjson"), inspect.ndjson, "utf8");
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
await fs.writeFile(path.join(outputDir, "workbook_formula_errors.ndjson"), errors.ndjson, "utf8");

const output = await SpreadsheetFile.exportXlsx(workbook);
const outputPath = path.join(outputDir, "NASDAQ_V6_RESEARCH_AUDIT.xlsx");
await output.save(outputPath);
console.log(JSON.stringify({ output: outputPath, sheets: 8, previewDir }));
