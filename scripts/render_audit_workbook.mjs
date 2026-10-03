import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [sheetName, range] = process.argv.slice(2);
if (!sheetName || !range) throw new Error("Usage: node render_audit_workbook.mjs <sheet> <range>");

const root = process.cwd();
const outputDir = path.join(root, "outputs", "01a0fff7-637c-7f00-84ac-e158b4fb55ac");
const workbookPath = path.join(outputDir, "应用统计择校模型_数据模板与审计.xlsx");
const previewDir = path.join(outputDir, "workbook_previews");
await fs.mkdir(previewDir, { recursive: true });

const blob = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(blob);
const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
const previewPath = path.join(previewDir, `${sheetName}.png`);
await fs.writeFile(previewPath, new Uint8Array(await image.arrayBuffer()));
console.log(previewPath);
