import fs from "node:fs/promises";
import path from "node:path";
const artifactModuleUrl = process.env.ARTIFACT_TOOL_MODULE_URL;
if (!artifactModuleUrl) {
  throw new Error("ARTIFACT_TOOL_MODULE_URL must point to artifact_tool.mjs");
}
const { FileBlob, SpreadsheetFile } = await import(artifactModuleUrl);

const inputPath = path.resolve("data/timeseries/workbooks/multivariate_timeseries_latest.xlsx");
const outputDir = path.resolve("reports/screenshots/timeseries_260819/workbook");
await fs.mkdir(outputDir, { recursive: true });
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const inspection = await workbook.inspect({
  kind: "workbook,sheet,formula",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 12,
  options: { maxResults: 100 },
});
const rendered = [];
for (const sheetName of ["Sources", "ModelCard", "RunManifest"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  const target = path.join(outputDir, `${sheetName}.png`);
  await fs.writeFile(target, new Uint8Array(await preview.arrayBuffer()));
  rendered.push({ sheetName, target, bytes: (await fs.stat(target)).size });
}
const evidence = {
  schema_version: 1,
  input: inputPath,
  sheet_count: 8,
  rendered,
  inspection: inspection.ndjson ?? inspection,
};
await fs.writeFile(
  path.join(outputDir, "artifact_tool_inspection.json"),
  JSON.stringify(evidence, null, 2) + "\n",
  "utf8",
);
process.stdout.write(JSON.stringify({ sheet_count: evidence.sheet_count, rendered }) + "\n");
