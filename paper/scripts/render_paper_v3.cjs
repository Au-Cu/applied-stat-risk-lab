const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright');

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (quoted) {
      if (char === '"' && next === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n') {
      row.push(field.replace(/\r$/, ''));
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += char;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ''));
    rows.push(row);
  }
  const headers = rows.shift().map((value, index) =>
    index === 0 ? value.replace(/^\uFEFF/, '') : value
  );
  return rows
    .filter((values) => values.some((value) => value !== ''))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] || ''])));
}

async function main() {
  const root = path.resolve(__dirname, '..', '..');
  const source = path.join(root, 'paper', 'modeling_paper_v2.html');
  const appendixCsv = path.join(root, 'paper', 'assets', 'v3', 'forecast_appendix.csv');
  const outputName = process.env.PAPER_OUTPUT_NAME || '报名前信息集下应用统计硕士拟录取初试低位分数的概率预测_V3.pdf';
  const output = path.join(root, 'output', 'pdf', outputName);
  fs.mkdirSync(path.dirname(output), { recursive: true });

  if (!fs.existsSync(appendixCsv)) {
    throw new Error('Missing ' + appendixCsv + '. Run build_paper_analysis.py first.');
  }
  const forecasts = parseCsv(fs.readFileSync(appendixCsv, 'utf8'));
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 1800 },
    deviceScaleFactor: 1,
  });
  await page.goto(pathToFileURL(source).href, {
    waitUntil: 'networkidle',
    timeout: 120000,
  });
  await page.evaluate((rows) => {
    const tbody = document.getElementById('forecast-appendix-body');
    tbody.replaceChildren(
      ...rows.map((row, index) => {
        const tr = document.createElement('tr');
        const cells = [
          String(index + 1),
          row['院校'],
          row['是否985'] === 'True' ? '是' : '否',
          row['分区'],
          row['派系'],
          row['中心区间'],
          row['原始P90区间'],
          row['稳健上界区间'],
          row['证据完备度'],
          row['上界可比性'],
        ];
        cells.forEach((value, cellIndex) => {
          const td = document.createElement('td');
          td.textContent = value;
          if ([0, 2, 3, 4, 5, 6, 7, 8].includes(cellIndex)) td.className = 'center';
          tr.appendChild(td);
        });
        return tr;
      })
    );
  }, forecasts);

  await page.evaluate(async () => {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      await window.MathJax.startup.promise;
    }
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const mathAudit = await page.evaluate(() => {
    const unresolved = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const texPattern = /\\\(|\\\[|\\begin\{|\\(?:widehat|mathbf|operatorname|mathcal|frac|sum|Phi|tau|alpha|beta|gamma|sigma)\b/;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!parent || ['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(parent.tagName)) continue;
      const value = node.nodeValue.trim();
      if (value && texPattern.test(value)) unresolved.push(value.slice(0, 160));
    }
    const malformedTags = [...document.body.querySelectorAll('*')]
      .map((element) => element.tagName)
      .filter((tagName) => /[\\{}^]/.test(tagName));
    const errors = [...document.querySelectorAll('mjx-merror')]
      .map((element) => element.textContent.trim())
      .filter(Boolean);
    return {
      mathCount: document.querySelectorAll('mjx-container').length,
      unresolved: [...new Set(unresolved)],
      malformedTags: [...new Set(malformedTags)],
      errors,
    };
  });
  if (mathAudit.unresolved.length || mathAudit.malformedTags.length || mathAudit.errors.length) {
    throw new Error('MathJax QA failed: ' + JSON.stringify(mathAudit));
  }
  console.log('MathJax QA: ' + JSON.stringify(mathAudit));
  await page.emulateMedia({ media: 'print' });
  await page.pdf({
    path: output,
    format: 'A4',
    preferCSSPageSize: true,
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: [
      '<div style="font-size:8px;color:#555;width:100%;text-align:center;',
      'font-family:Times New Roman,serif;padding-bottom:2mm;">',
      '<span class="pageNumber"></span>',
      '</div>',
    ].join(''),
    margin: { top: '0mm', right: '0mm', bottom: '8mm', left: '0mm' },
  });
  await browser.close();
  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
