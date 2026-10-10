const { chromium } = require('playwright');
const path = require('path');
const { pathToFileURL } = require('url');

async function main() {
  const root = path.resolve(__dirname, '..', '..');
  const source = path.join(root, 'paper', 'methods_paper.html');
  const output = path.join(root, 'output', 'pdf', '应用统计择校门槛概率预测_方法论文_初稿.pdf');
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1800 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(source).href, { waitUntil: 'networkidle', timeout: 120000 });
  await page.evaluate(async () => {
    if (window.MathJax?.startup?.promise) await window.MathJax.startup.promise;
    if (document.fonts?.ready) await document.fonts.ready;
  });
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: output,
    format: 'A4',
    preferCSSPageSize: true,
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<div style="font-size:8px;color:#718096;width:100%;padding:0 17mm;font-family:Arial,sans-serif;display:flex;justify-content:space-between"><span>单志愿约束下的硕士研究生择校门槛概率预测</span><span>方法论文初稿 · 2026-10-07</span></div>',
    footerTemplate: '<div style="font-size:8px;color:#718096;width:100%;padding:0 17mm;font-family:Arial,sans-serif;display:flex;justify-content:space-between"><span>应用统计择校风险实验室</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
    margin: { top: '14mm', right: '0mm', bottom: '14mm', left: '0mm' },
  });
  await browser.close();
  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
