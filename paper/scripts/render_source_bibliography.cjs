const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..', '..');
  const source = path.join(root, 'paper', 'public_source_bibliography.html');
  const outputName = process.env.SOURCE_BIB_OUTPUT_NAME
    || '应用统计硕士择校研究_逐字段公共数据来源目录_V5.pdf';
  const output = path.join(root, 'output', 'pdf', outputName);
  if (!fs.existsSync(source)) throw new Error(`Missing ${source}`);
  fs.mkdirSync(path.dirname(output), { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  await page.goto(pathToFileURL(source).href, { waitUntil: 'networkidle', timeout: 120000 });
  await page.addStyleTag({ content: `
    @page { size: A4 landscape; margin: 11mm 8mm 14mm; }
    html, body { margin: 0 !important; color: #172033; }
    body { font-family: "Noto Serif CJK SC", "Source Han Serif SC", SimSun, serif; }
    h1 { margin: 0 0 4mm; font-size: 17pt; }
    p { margin: 0 0 5mm; font-size: 8.4pt; line-height: 1.55; }
    table { table-layout: fixed; width: 100%; font-size: 6.55pt; line-height: 1.30; }
    thead { display: table-header-group; }
    tr { break-inside: avoid; page-break-inside: avoid; }
    th { position: static !important; background: #eaf0f7 !important; }
    th, td { padding: 2.2px 3px; border-color: #9ca8b8; overflow-wrap: anywhere; }
    th:nth-child(1), td:nth-child(1) { width: 4%; }
    th:nth-child(2), td:nth-child(2) { width: 11%; }
    th:nth-child(3), td:nth-child(3) { width: 19%; }
    th:nth-child(4), td:nth-child(4) { width: 13%; }
    th:nth-child(5), td:nth-child(5) { width: 6%; }
    th:nth-child(6), td:nth-child(6) { width: 19%; }
    th:nth-child(7), td:nth-child(7) { width: 8%; }
    th:nth-child(8), td:nth-child(8) { width: 7%; }
    th:nth-child(9), td:nth-child(9) { width: 13%; }
    a { color: #184f8f; text-decoration: none; }
  ` });
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: output,
    preferCSSPageSize: true,
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: [
      '<div style="font-size:7px;color:#555;width:100%;text-align:center;',
      'font-family:Times New Roman,serif;padding-bottom:2mm;">',
      '<span class="pageNumber"></span> / <span class="totalPages"></span>',
      '</div>',
    ].join(''),
    margin: { top: '0mm', right: '0mm', bottom: '0mm', left: '0mm' },
  });
  await browser.close();
  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
