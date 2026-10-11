const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'work', 'v6-web-qa');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.goto(process.env.V6_QA_URL || 'http://127.0.0.1:4174/', { waitUntil: 'networkidle', timeout: 90000 });
  if (response.status() !== 200) throw new Error('HTTP failure: ' + response.status());
  await page.getByRole('tab', { name: '模型原理', exact: true }).click();
  const panel = page.locator('.statistical-research').first();
  await panel.getByRole('tab', { name: '1. 这届完整名单' }).click();
  if (!await panel.locator('.stat-object-detail').textContent().then(v => v.includes('不是随机抽样误差'))) throw new Error('Finite-estimand switch failed');
  await panel.getByRole('button', { name: '院校等权描述', exact: true }).click();
  if (!await panel.locator('.stat-variance-strip').textContent().then(v => v.includes('43.0%'))) throw new Error('Descriptive variance failed');
  await panel.getByRole('button', { name: '年份条件化 REML', exact: true }).click();
  if (!await panel.locator('.stat-variance-strip').textContent().then(v => v.includes('26.9%'))) throw new Error('REML switch failed');
  await panel.getByRole('tab', { name: '3. 下一届未知结果' }).click();
  await page.addStyleTag({ content: '.topbar { position: static !important; }' });
  await panel.screenshot({ path: path.join(output, 'research-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.screenshot({ path: path.join(output, 'research-mobile.png') });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  const ids = await page.evaluate(() => { const all = [...document.querySelectorAll('[id]')].map(x => x.id); return all.filter((id, i) => all.indexOf(id) !== i); });
  await page.getByRole('tab', { name: '回测与校准', exact: true }).click();
  if (!await page.locator('.statistical-research').count()) throw new Error('Backtest research panel missing');
  await browser.close();
  const result = { http: response.status(), runtimeErrors: errors, horizontalOverflow: overflow, duplicateIds: [...new Set(ids)], estimandSwitch: true, varianceSwitch: true, backtestPanel: true };
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  if (errors.length || overflow > 2 || ids.length) process.exit(1);
}
main().catch(e => { console.error(e); process.exit(1); });
