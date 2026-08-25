import fs from "node:fs/promises";

const artifactToolModule = process.env.TSV5_ARTIFACT_TOOL_MODULE || "@oai/artifact-tool";
const { SpreadsheetFile, Workbook } = await import(artifactToolModule);

const [inputPath, outputPath, renderDir] = process.argv.slice(2);
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const navy = "#0F2747", blue = "#DCE9F8", line = "#C8D2E0", green = "#DCFCE7", red = "#FEE2E2";

for (const [sheetName, rows] of Object.entries(payload.sheets)) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  const title = sheet.getRangeByIndexes(0, 0, 1, Math.max(2, rows[0].length));
  title.merge(); title.values = [[`NASDAQ V5 · ${sheetName}`]];
  title.format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 15 }, rowHeight: 28, verticalAlignment: "center" };
  const target = sheet.getRangeByIndexes(2, 0, rows.length, rows[0].length);
  target.values = rows;
  const header = sheet.getRangeByIndexes(2, 0, 1, rows[0].length);
  header.format = { fill: blue, font: { bold: true, color: "#102A43" }, borders: { preset: "all", style: "thin", color: line }, wrapText: true };
  if (rows.length > 1) {
    const body = sheet.getRangeByIndexes(3, 0, rows.length - 1, rows[0].length);
    body.format = { borders: { preset: "all", style: "thin", color: "#E5EAF0" }, verticalAlignment: "top" };
  }
  target.format.autofitColumns();
  target.format.autofitRows();
  for (let col = 0; col < rows[0].length; col++) {
    const column = sheet.getRangeByIndexes(2, col, rows.length, 1);
    if ((column.format.columnWidthPx || 0) > 260) column.format.columnWidthPx = 260;
  }
  sheet.freezePanes.freezeRows(3);
}

const observations = workbook.worksheets.getItem("Observations");
observations.getRangeByIndexes(3, 4, payload.sheets.Observations.length - 1, 3).format.numberFormat = "yyyy-mm-dd";
const features = workbook.worksheets.getItem("Features");
features.getRangeByIndexes(3, 3, payload.sheets.Features.length - 1, 2).format.numberFormat = "yyyy-mm-dd";
const runManifest = workbook.worksheets.getItem("RunManifest");
runManifest.getRange("B4").format.numberFormat = "yyyy-mm-dd hh:mm:ss";

const modelCard = workbook.worksheets.getItem("ModelCard");
modelCard.getRange("D3:E3").values = [["Audit check", "Status"]];
modelCard.getRange("D3:E3").format = { fill: blue, font: { bold: true }, borders: { preset: "all", style: "thin", color: line } };
modelCard.getRange("D4:D7").values = [["Probability unit"], ["Official write disabled"], ["Scenario isolation"], ["Research Gate"]];
modelCard.getRange("E4:E7").formulas = [["=IF('ModelCard'!B5=\"research_timeseries_v5_conditional\",\"OK\",\"FAIL\")"], ["=IF('ModelCard'!B13=FALSE,\"OK\",\"FAIL\")"], ["=IF('ModelCard'!B14=FALSE,\"OK\",\"FAIL\")"], ["=IF('ModelCard'!B7=TRUE,\"PASS\",\"HOLD\")"]];
modelCard.getRange("D4:E7").format = { borders: { preset: "all", style: "thin", color: line } };
modelCard.getRange("E4:E7").conditionalFormats.add("containsText", { text: "OK", format: { fill: green } });
modelCard.getRange("E4:E7").conditionalFormats.add("containsText", { text: "FAIL", format: { fill: red } });
modelCard.getRange("E4:E7").conditionalFormats.add("containsText", { text: "HOLD", format: { fill: "#FEF3C7" } });
modelCard.getRange("D3:E7").format.autofitColumns();
modelCard.getRange("B4:B15").format = { columnWidth: 52, wrapText: true, verticalAlignment: "top" };
modelCard.getRange("B8").format.rowHeight = 72;
modelCard.getRange("D4:D7").format.columnWidth = 24;
modelCard.getRange("E4:E7").format.columnWidth = 12;

await fs.mkdir(renderDir, { recursive: true });
for (const sheetName of Object.keys(payload.sheets)) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const used = sheet.getUsedRange();
  const blob = await workbook.render({ sheetName, range: used.address, scale: 1, format: "png" });
  await fs.writeFile(`${renderDir}/${sheetName}.png`, new Uint8Array(await blob.arrayBuffer()));
}
const check = await workbook.inspect({ kind: "table", range: "ModelCard!A1:E16", include: "values,formulas", tableMaxRows: 16, tableMaxCols: 5 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
await fs.writeFile(`${renderDir}/inspection.ndjson`, `${check.ndjson}\n${errors.ndjson}\n`, "utf8");
const output = await SpreadsheetFile.exportXlsx(workbook);
await fs.mkdir(new URL(".", `file:///${outputPath.replaceAll("\\", "/")}`).pathname, { recursive: true }).catch(() => {});
await output.save(outputPath);
process.stdout.write(`${outputPath}\n`);
process.exit(0);
