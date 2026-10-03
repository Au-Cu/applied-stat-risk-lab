import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = process.cwd();
const workbookPath = path.join(root, "outputs", "01a0fff7-637c-7f00-84ac-e158b4fb55ac", "应用统计择校模型_数据模板与审计.xlsx");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));

const structure = await workbook.inspect({
  kind: "sheet,table,drawing",
  include: "id,name,address,type",
  maxChars: 12000,
});
const summary = await workbook.inspect({
  kind: "table",
  range: "审计总览!A6:F21",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 6,
  maxChars: 10000,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "saved workbook formula error scan",
  maxChars: 5000,
});

console.log(structure.ndjson);
console.log(summary.ndjson);
console.log(errors.ndjson);
